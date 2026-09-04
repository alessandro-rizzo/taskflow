#!/usr/bin/env python3
"""Mutation tests for result-free E06 Phase-B preparation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


PHASE_B = Path(__file__).resolve().parents[1]
REPOSITORY = PHASE_B.parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify_phase_b = load_module("e06_verify_phase_b_tests", PHASE_B / "scripts/verify_phase_b.py")
guard = load_module("e06_guard_tests", PHASE_B / "scripts/guard.py")


class PhaseBContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="taskflow-e06-phase-b-")
        self.phase_b = Path(self.temporary.name) / "phase-b"
        shutil.copytree(PHASE_B, self.phase_b, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def rewrite_json(self, relative: str, mutate) -> None:
        path = self.phase_b / relative
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def rehash(self) -> None:
        manifest_path = self.phase_b / "frozen-artifacts.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in manifest["artifacts"]:
            item["sha256"] = hashlib.sha256((self.phase_b / item["path"]).read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        (self.phase_b / "protocol.sha256").write_text(f"{digest}  frozen-artifacts.json\n", encoding="utf-8")

    def assert_rejected(self, expected: str) -> None:
        with self.assertRaisesRegex(verify_phase_b.VerificationError, expected):
            verify_phase_b.verify_phase_b(self.phase_b, REPOSITORY, verify_anchor=False)

    def test_canonical_contract_passes(self) -> None:
        verify_phase_b.verify_phase_b(PHASE_B, REPOSITORY)

    def test_result_directory_is_rejected(self) -> None:
        (self.phase_b / "evidence").mkdir()
        self.assert_rejected("premature Phase-B result")

    def test_selected_decision_is_rejected_after_rehash(self) -> None:
        self.rewrite_json("decision-matrix.json", lambda value: value.__setitem__("selected_branch", "trusted-native-host"))
        self.rehash()
        self.assert_rejected("decision selected prematurely")

    def test_default_simulator_permission_is_rejected_after_rehash(self) -> None:
        def mutate(value):
            value["resolved"]["paths"]["default_simulator_set_forbidden"] = False

        self.rewrite_json("manifest-resolution.json", mutate)
        self.rehash()
        with self.assertRaisesRegex(guard.GuardError, "default simulator set"):
            guard.validate(self.phase_b)

    def test_simctl_without_custom_set_is_rejected_after_rehash(self) -> None:
        def mutate(value):
            argv = next(command["argv"] for command in value["commands"] if command["id"] == "create-device-a")
            index = argv.index("--set")
            del argv[index:index + 2]

        self.rewrite_json("command-ledger.json", mutate)
        self.rehash()
        with self.assertRaisesRegex(guard.GuardError, "lacks --set"):
            guard.validate(self.phase_b)

    def test_cleanup_escape_is_rejected(self) -> None:
        ledger = json.loads((PHASE_B / "command-ledger.json").read_text(encoding="utf-8"))
        ledger["cleanup_allowlist"]["paths"].append("/private/tmp/unowned")
        with self.assertRaisesRegex(guard.GuardError, "escapes mutable root"):
            guard.validate_ledger(ledger)

    def test_guard_and_runner_have_no_execution_primitive(self) -> None:
        for relative in ("scripts/guard.py", "scripts/runner.py"):
            source = (PHASE_B / relative).read_text(encoding="utf-8")
            for forbidden in ("subprocess", "os.kill", "shutil.rmtree", "os.remove", "os.unlink"):
                self.assertNotIn(forbidden, source, f"{relative} contains {forbidden}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
