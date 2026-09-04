import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest


EXPERIMENT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "e03_verify_contract", EXPERIMENT / "scripts/verify_contract.py"
)
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = VERIFY.load_json(EXPERIMENT / "protocol.json")
        cls.attacks = VERIFY.load_json(EXPERIMENT / "attacks.json")
        cls.limits = VERIFY.load_json(EXPERIMENT / "policies/limits.json")
        cls.policy = VERIFY.load_json(
            EXPERIMENT / "policies/untrusted-plan-policy.json"
        )
        cls.container = VERIFY.load_json(EXPERIMENT / "policies/container.json")
        cls.native = (EXPERIMENT / "policies/native.sb.in").read_text(
            encoding="utf-8"
        )

    def test_live_phase_a_contract_verifies(self):
        protocol = VERIFY.verify(phase_a_only=True)
        self.assertEqual(protocol["status"], "phase-a-contract-only")

    def test_duplicate_json_member_is_rejected(self):
        with tempfile.NamedTemporaryFile(suffix=".json") as handle:
            handle.write(b'{"version":1,"version":2}')
            handle.flush()
            with self.assertRaisesRegex(VERIFY.ContractError, "duplicate JSON member"):
                VERIFY.load_json(Path(handle.name))

    def test_threshold_drift_is_rejected(self):
        protocol = copy.deepcopy(self.protocol)
        protocol["performance_gate"]["p95_seconds_exclusive"] = 0.251
        with self.assertRaisesRegex(VERIFY.ContractError, "threshold drift"):
            VERIFY.verify_contract_invariants(
                protocol,
                self.attacks,
                self.limits,
                self.policy,
                self.container,
                self.native,
            )

    def test_catalogue_metadata_drift_is_rejected(self):
        attacks = copy.deepcopy(self.attacks)
        attacks["catalogue_entries"][0]["expected_outcome"] = "bounded"
        with self.assertRaisesRegex(VERIFY.ContractError, "catalogue metadata"):
            VERIFY.verify_catalogue(attacks)

    def test_phase_b_path_is_rejected(self):
        allowed = list(self.protocol["phase_a"]["allowed_files"])
        actual = allowed + ["evidence/result.json"]
        with self.assertRaisesRegex(VERIFY.ContractError, "tree mismatch"):
            VERIFY.verify_phase_a_paths(
                actual,
                allowed,
                self.protocol["phase_a"]["forbidden_before_contract_commit"],
            )

    def test_wrappers_are_descriptive_only_in_phase_a(self):
        attack = VERIFY.wrapper_description(EXPERIMENT / "scripts/run_attacks.py")
        benchmark = VERIFY.wrapper_description(
            EXPERIMENT / "scripts/run_benchmarks.py"
        )
        self.assertFalse(attack["phase_a_execution_allowed"])
        self.assertFalse(benchmark["phase_a_execution_allowed"])
        self.assertEqual(attack["candidate_order"], benchmark["candidate_order"])


if __name__ == "__main__":
    unittest.main()
