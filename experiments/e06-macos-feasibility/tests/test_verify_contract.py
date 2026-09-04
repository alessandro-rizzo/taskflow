#!/usr/bin/env python3
"""Mutation tests for the frozen E06 Phase A contract."""

from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


EXPERIMENT = Path(__file__).resolve().parents[1]
REPOSITORY = EXPERIMENT.parents[1]
VERIFY_PATH = EXPERIMENT / "scripts/verify_contract.py"
COLLECT_PATH = EXPERIMENT / "scripts/collect_inventory.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify_contract = load_module("e06_verify_contract_tests", VERIFY_PATH)
collect_inventory = load_module("e06_collect_inventory_tests", COLLECT_PATH)


class ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="taskflow-e06-contract-")
        self.experiment = Path(self.temporary.name) / "e06"
        shutil.copytree(EXPERIMENT, self.experiment, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def rewrite_json(self, relative: str, mutate) -> None:
        path = self.experiment / relative
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def assert_rejected(self, expected: str) -> None:
        with self.assertRaisesRegex(verify_contract.VerificationError, expected):
            verify_contract.verify(self.experiment, REPOSITORY)

    def test_canonical_contract_passes(self) -> None:
        verify_contract.verify(EXPERIMENT, REPOSITORY)

    def test_phase_b_artifact_is_rejected(self) -> None:
        (self.experiment / "evidence").mkdir()
        self.assert_rejected("Phase B artifact is forbidden")

    def test_inventory_uuid_is_rejected(self) -> None:
        def mutate(value):
            value["default_device_set"]["leaked_device"] = "12345678-1234-1234-1234-123456789abc"

        self.rewrite_json("inventory/simulator.json", mutate)
        self.assert_rejected("inventory leaked a UUID")

    def test_metric_threshold_drift_is_rejected(self) -> None:
        def mutate(value):
            value["timing_metrics"][1]["threshold"]["p95_seconds"] = 3.1

        self.rewrite_json("measurement-plan.json", mutate)
        self.assert_rejected("workspace threshold drifted")

    def test_missing_candidate_procedure_is_rejected(self) -> None:
        def mutate(value):
            value["worker_candidates"][0]["procedure"] = "PROC:missing"

        self.rewrite_json("candidate-matrix.json", mutate)
        self.assert_rejected("candidate procedure missing")

    def test_reservation_is_rejected(self) -> None:
        def mutate(value):
            value["reservation"] = {"id": "unexpected"}

        self.rewrite_json("infrastructure-status.json", mutate)
        self.assert_rejected("Phase A must not record a reservation")

    def test_default_simulator_permission_is_rejected(self) -> None:
        def mutate(value):
            value["properties"]["paths"]["properties"]["default_simulator_set_forbidden"]["const"] = False

        self.rewrite_json("execution-manifest.schema.json", mutate)
        self.assert_rejected("manifest must forbid default simulator set")

    def test_parent_path_traversal_permission_is_rejected(self) -> None:
        def mutate(value):
            del value["$defs"]["mutablePath"]["not"]

        self.rewrite_json("execution-manifest.schema.json", mutate)
        self.assert_rejected("manifest mutable paths must reject parent traversal")

    def test_fixture_digest_drift_is_rejected(self) -> None:
        def mutate(value):
            value["bindings"][0]["files"][0]["sha256"] = "0" * 64

        self.rewrite_json("fixture-bindings.json", mutate)
        self.assert_rejected("fixture drift")

    def test_frozen_artifact_drift_is_rejected(self) -> None:
        with (self.experiment / "README.md").open("a", encoding="utf-8") as handle:
            handle.write("\ndrift\n")
        self.assert_rejected("frozen artifact drift")

    def test_collector_query_allowlist_rejects_lifecycle_command(self) -> None:
        with self.assertRaisesRegex(ValueError, "not allowlisted"):
            collect_inventory.query(("simctl", "list"))

    def test_collector_sanitizes_device_udid(self) -> None:
        sanitized = collect_inventory.sanitized_device(
            {"name": "test", "UDID": "secret-device-id", "state": 1}
        )
        self.assertNotIn("UDID", sanitized)
        self.assertNotIn("secret-device-id", json.dumps(sanitized))


if __name__ == "__main__":
    unittest.main(verbosity=2)
