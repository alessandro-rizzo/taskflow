import copy
import importlib.util
import unittest
from pathlib import Path


APPROVAL = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verify_e06_approval", APPROVAL / "scripts/verify_approval.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ApprovalProposalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = MODULE.load(APPROVAL / "approval-packet.json")
        cls.schema = MODULE.load(APPROVAL.parent.parent / "execution-manifest.schema.json")

    def test_repository_proposal_verifies(self):
        MODULE.verify()

    def test_materialized_resolved_fields_match_schema(self):
        MODULE.validate_schema(MODULE.build_schema_specimen(self.packet), self.schema, self.schema)

    def test_default_device_set_is_rejected(self):
        specimen = MODULE.build_schema_specimen(self.packet)
        specimen["paths"]["default_simulator_set_forbidden"] = False
        with self.assertRaises(MODULE.VerificationError):
            MODULE.validate_schema(specimen, self.schema, self.schema)

    def test_broad_cleanup_is_rejected(self):
        specimen = MODULE.build_schema_specimen(self.packet)
        specimen["cleanup_allowlist"]["paths"] = ["/private/tmp"]
        with self.assertRaises(MODULE.VerificationError):
            MODULE.validate_schema(specimen, self.schema, self.schema)

    def test_real_packet_cannot_claim_approval(self):
        changed = copy.deepcopy(self.packet)
        changed["manifest"]["approval"]["approved_by"] = "someone"
        with self.assertRaises(MODULE.VerificationError):
            MODULE.verify_unresolved(changed)


if __name__ == "__main__":
    unittest.main()
