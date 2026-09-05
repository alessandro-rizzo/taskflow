#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("e06_vm_verify", ROOT / "verify_evidence.py")
verify = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(verify)


class EvidenceTests(unittest.TestCase):
    def test_committed_evidence(self):
        verify.verify()

    def test_changed_record_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "evidence"
            import shutil
            shutil.copytree(ROOT, copied)
            target = copied / "retained/attempt-003/failure.json"
            value = json.loads(target.read_text())
            value["error"] = "changed"
            target.write_text(json.dumps(value) + "\n")
            with mock.patch.object(verify, "ROOT", copied):
                with self.assertRaises(verify.EvidenceError):
                    verify.verify()

    def test_unsanitized_device_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "evidence"
            import shutil
            shutil.copytree(ROOT, copied)
            target = copied / "README.md"
            target.write_text(target.read_text() + "00000000-0000-0000-0000-000000000001\n")
            with mock.patch.object(verify, "ROOT", copied):
                with self.assertRaises(verify.EvidenceError):
                    verify.verify_sanitized()


if __name__ == "__main__":
    unittest.main()
