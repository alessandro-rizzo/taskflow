#!/usr/bin/env python3
"""Focused negative tests for the E02 Phase A contract verifier."""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("verify_contract.py")
SPEC = importlib.util.spec_from_file_location("e02_verify_contract", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class ContractVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.protocol = VERIFY.load_json(VERIFY.PROTOCOL)

    def assert_semantic_rejection(self, mutate) -> None:
        protocol = copy.deepcopy(self.protocol)
        mutate(protocol)
        with self.assertRaises(VERIFY.ContractError):
            VERIFY.validate_protocol_semantics(protocol)

    def test_rejects_relaxed_w1_latency(self) -> None:
        self.assert_semantic_rejection(
            lambda protocol: protocol["performance_gates"]["w1_plan"].__setitem__("p95_seconds_exclusive", 0.5)
        )

    def test_rejects_reduced_determinism_samples(self) -> None:
        self.assert_semantic_rejection(
            lambda protocol: protocol["hard_gates"].__setitem__("fresh_processes_per_fixture", 2)
        )

    def test_rejects_open_ended_canonicalization_heuristic(self) -> None:
        self.assert_semantic_rejection(
            lambda protocol: protocol["canonical_json"].__setitem__("open_ended_key_name_heuristic_allowed", True)
        )

    def test_rejects_changed_bound_input_hash(self) -> None:
        self.assert_semantic_rejection(
            lambda protocol: protocol["scope"]["bindings"][0].__setitem__("sha256", "0" * 64)
        )

    def test_rejects_discretionary_reruns(self) -> None:
        self.assert_semantic_rejection(
            lambda protocol: protocol["rerun_rules"].__setitem__("other_discretionary_reruns_allowed", True)
        )

    def test_rejects_mandatory_empty_declaration_arrays(self) -> None:
        self.assert_semantic_rejection(
            lambda protocol: protocol["plan_grammar"]["objects"]["plan"].__setitem__(
                "required",
                protocol["plan_grammar"]["objects"]["plan"]["required"] + ["services", "secrets", "effects"],
            )
        )

    def test_rejects_materializing_unproduced_e01_diagnostics(self) -> None:
        self.assert_semantic_rejection(
            lambda protocol: protocol["compatibility_corrections"]["e01_w1_optional_diagnostics"].__setitem__(
                "plan_artifact_emitted", True
            )
        )

    def test_strict_json_rejects_duplicate_members(self) -> None:
        with self.assertRaisesRegex(VERIFY.ContractError, "duplicate JSON object member"):
            VERIFY.load_json_bytes(b'{"value":1,"value":2}', "duplicate.json")

    def test_strict_json_rejects_non_finite_and_negative_zero(self) -> None:
        for raw in (b'{"value":NaN}', b'{"value":-0}'):
            with self.subTest(raw=raw), self.assertRaises(VERIFY.ContractError):
                VERIFY.load_json_bytes(raw, "number.json")

    def test_scope_hash_detects_mutated_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bound.txt"
            path.write_text("before", encoding="utf-8")
            expected = VERIFY.sha256_file(path)
            path.write_text("after", encoding="utf-8")
            with self.assertRaisesRegex(VERIFY.ContractError, "scope hash drift"):
                VERIFY.verify_file_hash(path, expected, "scope hash drift: bound.txt")

    def test_protocol_round_trips_as_strict_json(self) -> None:
        encoded = json.dumps(self.protocol, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.assertEqual(VERIFY.load_json_bytes(encoded, "roundtrip.json"), self.protocol)


if __name__ == "__main__":
    unittest.main()
