#!/usr/bin/env python3
"""Mutation tests for the E08 Phase A verifier."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


EXPERIMENT = Path(__file__).resolve().parents[1]
REPOSITORY = EXPERIMENT.parents[1]
VERIFIER_PATH = EXPERIMENT / "scripts/verify_contract.py"
SPEC = importlib.util.spec_from_file_location("e08_verify_contract", VERIFIER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load E08 verifier")
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refresh_frozen_hashes(experiment: Path) -> None:
    manifest = load_json(experiment / "frozen-artifacts.json")
    for artifact in manifest["artifacts"]:
        artifact["sha256"] = sha256(experiment / artifact["path"])
    write_json(experiment / "frozen-artifacts.json", manifest)
    (experiment / "protocol.sha256").write_text(
        f"{sha256(experiment / 'frozen-artifacts.json')}  frozen-artifacts.json\n",
        encoding="utf-8",
    )


class ContractMutationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="taskflow-e08-contract-")
        self.experiment = Path(self.temporary.name) / "e08-worker-protocol"
        shutil.copytree(EXPERIMENT, self.experiment, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def assert_rejected(self, expected_message: str) -> None:
        with self.assertRaisesRegex(VERIFIER.VerificationError, expected_message):
            VERIFIER.verify(self.experiment, REPOSITORY)

    def test_frozen_contract_is_valid(self) -> None:
        VERIFIER.verify(self.experiment, REPOSITORY)

    def test_phase_b_go_source_is_rejected(self) -> None:
        (self.experiment / "worker.go").write_text("package worker\n", encoding="utf-8")
        self.assert_rejected("Phase A fileset mismatch")

    def test_rehashed_threshold_relaxation_is_rejected(self) -> None:
        thresholds = load_json(self.experiment / "thresholds.json")
        thresholds["timing_metrics"][0]["threshold"]["milliseconds"] = 301
        write_json(self.experiment / "thresholds.json", thresholds)
        refresh_frozen_hashes(self.experiment)
        self.assert_rejected("ready-hit threshold drifted")

    def test_rehashed_fault_removal_is_rejected(self) -> None:
        matrix = load_json(self.experiment / "fault-matrix.json")
        matrix["cases"].pop()
        write_json(self.experiment / "fault-matrix.json", matrix)
        refresh_frozen_hashes(self.experiment)
        self.assert_rejected("fault case set/order drifted")

    def test_rehashed_provider_options_are_rejected(self) -> None:
        schema = load_json(self.experiment / "envelopes.schema.json")
        definition = schema["$defs"]["tryReserve"]
        definition["properties"]["provider_options"] = {"type": "object"}
        write_json(self.experiment / "envelopes.schema.json", schema)
        refresh_frozen_hashes(self.experiment)
        self.assert_rejected("forbidden open or secret field")

    def test_rehashed_premature_decision_is_rejected(self) -> None:
        decision = load_json(self.experiment / "decision-matrix.json")
        decision["selected_branch"] = "one-typed-core-with-capability-extensions"
        write_json(self.experiment / "decision-matrix.json", decision)
        refresh_frozen_hashes(self.experiment)
        self.assert_rejected("Phase A cannot select a branch")

    def test_rehashed_ssh_safety_relaxation_is_rejected(self) -> None:
        schema = load_json(self.experiment / "ssh-availability-manifest.schema.json")
        schema["properties"]["endpoint"]["properties"]["strict_host_key_checking"] = {"type": "boolean"}
        write_json(self.experiment / "ssh-availability-manifest.schema.json", schema)
        refresh_frozen_hashes(self.experiment)
        self.assert_rejected("strict host-key checking")

    def test_rehashed_invalid_state_transition_is_rejected(self) -> None:
        machines = load_json(self.experiment / "state-machines.json")
        machines["machines"][0]["transitions"][0]["to"] = "not-a-state"
        write_json(self.experiment / "state-machines.json", machines)
        refresh_frozen_hashes(self.experiment)
        self.assert_rejected("transition references unknown state")

    def test_rehashed_repository_binding_drift_is_rejected(self) -> None:
        bindings = load_json(self.experiment / "fixture-bindings.json")
        bindings["bindings"][0]["files"][0]["sha256"] = "0" * 64
        write_json(self.experiment / "fixture-bindings.json", bindings)
        refresh_frozen_hashes(self.experiment)
        self.assert_rejected("bound input drifted")


if __name__ == "__main__":
    unittest.main()
