#!/usr/bin/env python3
"""Mutation tests for the frozen E07 Phase A contract."""

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
VERIFY_PATH = EXPERIMENT / "scripts/verify_contract.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify_contract = load_module("e07_verify_contract_tests", VERIFY_PATH)


class ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="taskflow-e07-contract-")
        self.experiment = Path(self.temporary.name) / "e07"
        shutil.copytree(EXPERIMENT, self.experiment, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def rewrite_json(self, relative: str, mutate) -> None:
        path = self.experiment / relative
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def rehash(self) -> None:
        artifacts = []
        for relative in sorted(verify_contract.FROZEN_FILES):
            digest = hashlib.sha256((self.experiment / relative).read_bytes()).hexdigest()
            artifacts.append({"path": relative, "sha256": digest})
        manifest = {
            "format_version": "taskflow-e07-frozen-artifacts/v1-experimental",
            "hash_algorithm": "sha256",
            "artifacts": artifacts,
        }
        manifest_path = self.experiment / "frozen-artifacts.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        (self.experiment / "protocol.sha256").write_text(f"{digest}  frozen-artifacts.json\n", encoding="utf-8")

    def assert_rejected(self, expected: str) -> None:
        with self.assertRaisesRegex(verify_contract.VerificationError, expected):
            verify_contract.verify(self.experiment, REPOSITORY)

    def test_canonical_contract_passes(self) -> None:
        verify_contract.verify(EXPERIMENT, REPOSITORY)

    def test_phase_b_controller_is_rejected(self) -> None:
        (self.experiment / "controller.py").write_text("raise SystemExit\n", encoding="utf-8")
        self.assert_rejected("Phase A fileset mismatch")

    def test_rehashed_threshold_relaxation_is_rejected(self) -> None:
        self.rewrite_json("thresholds.json", lambda value: value["caller_loss_cleanup"].__setitem__("cleanup_after_expiry_max_seconds_max", 3.0))
        self.rehash()
        self.assert_rejected("caller_loss_cleanup thresholds drifted")

    def test_rehashed_project_port_leak_is_rejected(self) -> None:
        self.rewrite_json("contract.json", lambda value: value["workload"]["subsets"][0]["project_visible_request"].__setitem__("port", 41001))
        self.rehash()
        self.assert_rejected("project-visible request leaked a field")

    def test_rehashed_branch_selection_is_rejected(self) -> None:
        def mutate(value):
            value["status"] = "selected"
            value["selected_branch"] = "typed-endpoint-manager"
        self.rewrite_json("decision-matrix.json", mutate)
        self.rehash()
        self.assert_rejected("Phase A must not select a branch")

    def test_rehashed_unapproved_compose_credit_is_rejected(self) -> None:
        self.rewrite_json("decision-matrix.json", lambda value: value["candidate_credit_rules"].__setitem__("unapproved_shared_runtime_is_eligible", True))
        self.rehash()
        self.assert_rejected("candidate credit rules drifted")

    def test_rehashed_raw_token_permission_is_rejected(self) -> None:
        self.rewrite_json("event-schema.json", lambda value: value["credential_policy"].__setitem__("raw_tokens_allowed", True))
        self.rehash()
        self.assert_rejected("credential evidence policy drifted")

    def test_rehashed_missing_raw_trace_is_rejected(self) -> None:
        self.rewrite_json("event-schema.json", lambda value: value["phase_b_evidence"]["required_paths"].pop(0))
        self.rehash()
        self.assert_rejected("required evidence paths drifted")

    def test_fixture_digest_drift_is_rejected(self) -> None:
        self.rewrite_json("fixture-bindings.json", lambda value: value["bindings"][0]["files"][0].__setitem__("sha256", "0" * 64))
        self.rehash()
        self.assert_rejected("fixture binding set or declared digest drifted")

    def test_frozen_file_drift_is_rejected(self) -> None:
        with (self.experiment / "README.md").open("a", encoding="utf-8") as handle:
            handle.write("\ndrift\n")
        self.assert_rejected("frozen artifact drift")


if __name__ == "__main__":
    unittest.main(verbosity=2)
