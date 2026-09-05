"""Repository-only regression checks for E06 VM preparation."""

import copy
import importlib.util
import io
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("e06_vm_contract", Path(__file__).resolve().parents[1] / "contract.py")
vm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vm)


class VMContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = vm.load("contract.json")
        self.pins = vm.load("pins.json")

    def test_recording_never_reaches_native_or_network_primitives(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("native primitive reached")
        with patch.object(subprocess, "run", forbidden), patch.object(subprocess, "Popen", forbidden), \
                patch.object(os, "system", forbidden), patch.object(os, "kill", forbidden), \
                patch.object(os, "mkdir", forbidden), patch.object(os, "unlink", forbidden), \
                patch.object(socket, "socket", forbidden), patch.object(Path, "write_text", forbidden), \
                patch.object(Path, "write_bytes", forbidden):
            first = vm.record_plan(self.contract, self.pins)
            second = vm.record_plan(self.contract, self.pins)
        self.assertEqual(first, second)
        self.assertEqual(first["execution_count"], 0)
        self.assertEqual(first["benchmark_samples"], 0)
        self.assertGreater(first["operations_recorded"], 0)

    def test_tags_cannot_replace_digest_pins(self):
        self.pins["image"]["reference"] = "ghcr.io/cirruslabs/macos-tahoe-xcode:latest"
        with self.assertRaises(vm.ContractError):
            vm.verify(self.contract, self.pins)

    def test_controller_checksum_and_url_cannot_drift(self):
        for field, value in (("sha256", "0" * 64), ("url", "https://example.com/tart.tar.gz")):
            with self.subTest(field=field):
                bad = copy.deepcopy(self.pins)
                bad["controller"][field] = value
                with self.assertRaises(vm.ContractError):
                    vm.verify(self.contract, bad)

    def test_metadata_cannot_claim_guest_attestation_or_native_equivalence(self):
        for field, value in (("attested", True), ("native_profile_equivalent", True), ("xcode_build", "17F113")):
            with self.subTest(field=field):
                bad = copy.deepcopy(self.pins)
                bad["guest_profile"][field] = value
                with self.assertRaises(vm.ContractError):
                    vm.verify(self.contract, bad)

    def test_host_safety_boundaries_cannot_be_relaxed(self):
        for field, value in (("automatic_pruning", True), ("host_CoreSimulator_forbidden", False),
                             ("shares", ["/Users"]), ("host_privilege_changes", True)):
            with self.subTest(field=field):
                bad = copy.deepcopy(self.contract)
                bad["policies"][field] = value
                with self.assertRaises(vm.ContractError):
                    vm.verify(bad, self.pins)

    def test_capacity_cannot_silently_shrink_the_namespace_ramp(self):
        self.contract["resources"]["concurrency_levels"] = [1, 2]
        with self.assertRaises(vm.ContractError):
            vm.verify(self.contract, self.pins)

    def test_changed_command_removed_check_or_default_storage_rejected(self):
        for mutation in ("command", "omit", "environment", "target"):
            with self.subTest(mutation=mutation):
                ledger = vm.acquisition_ledger()
                if mutation == "command":
                    ledger["operations"][-2]["arguments"] = [vm.TART, "run", "existing-vm"]
                elif mutation == "omit":
                    ledger["operations"].pop(4)
                elif mutation == "environment":
                    ledger["controller_environment"].pop("TART_HOME")
                else:
                    ledger["operations"][1]["targets"] = ["/Users"]
                with self.assertRaises(vm.ContractError):
                    vm.verify_ledger(ledger)

    def test_path_traversal_prefix_confusion_and_globs_rejected(self):
        for path in (vm.ROOT + "/../other", vm.ROOT + "-other/a", vm.ROOT + "/a//b",
                     vm.ROOT + "/a/./b", vm.ROOT + "/a/*", "/Users/admin"):
            with self.subTest(path=path), self.assertRaises(vm.ContractError):
                vm.owned_path(path)
        self.assertEqual(vm.owned_path(vm.ROOT + "/tart"), vm.ROOT + "/tart")

    def test_existing_root_and_broken_symlink_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            absent = base / "new"
            vm.require_absent_root(absent)
            absent.mkdir()
            with self.assertRaises(vm.ContractError):
                vm.require_absent_root(absent)
            link = base / "link"
            link.symlink_to(base / "missing", target_is_directory=True)
            with self.assertRaises(vm.ContractError):
                vm.require_absent_root(link)

    def test_ordinary_verification_is_independent_of_acquired_disk_state(self):
        with patch.object(vm, "require_absent_root", side_effect=vm.ContractError("root exists")) as absence, \
                patch.object(sys, "argv", ["contract.py", "verify"]), patch("sys.stdout", new_callable=io.StringIO):
            vm.main()
            absence.assert_not_called()
            with patch.object(sys, "argv", ["contract.py", "check-acquisition-readiness"]), \
                    self.assertRaises(vm.ContractError):
                vm.main()

    def test_foundation_cache_and_license_stay_within_task_storage(self):
        ledger = vm.acquisition_ledger()
        self.assertEqual(ledger["controller_environment"]["CFFIXED_USER_HOME"], vm.ROOT)
        extract = next(row for row in ledger["operations"] if row["arguments"][0] == "/usr/bin/tar")
        for target in extract["targets"]:
            self.assertEqual(vm.owned_path(target), target)
        ledger["controller_environment"].pop("CFFIXED_USER_HOME")
        with self.assertRaises(vm.ContractError):
            vm.verify_ledger(ledger)

    def test_frozen_input_hash_drift_rejected(self):
        self.contract["inputs"]["measurement-plan.json"] = "0" * 64
        with self.assertRaises(vm.ContractError):
            vm.verify(self.contract, self.pins)

    def test_frozen_inputs_cannot_be_omitted(self):
        self.contract["inputs"].clear()
        with self.assertRaises(vm.ContractError):
            vm.verify(self.contract, self.pins)

    def test_vm_specific_requirements_survive_native_to_vm_pivot(self):
        matrix = vm.measurement_contract()["contract"]
        metrics = {m["id"]: m for m in matrix["timing_metrics"]}
        self.assertEqual(metrics["cold-vm-boot"]["sample_count"], 15)
        self.assertEqual(metrics["image-import-update"]["sample_count"], 15)
        self.assertEqual(metrics["warm-workspace-ready"]["threshold"],
                         {"operator": "strictly-less-than", "p95_seconds": 3.0})
        self.assertEqual(metrics["simulator-ready-to-install"]["threshold"],
                         {"operator": "strictly-less-than", "p95_seconds": 15.0})
        faults = {p["id"]: p["repetitions"] for p in matrix["failure_recovery_probes"]}
        self.assertEqual(faults, {"vm-loss": 5, "simulator-loss": 5, "cancellation": 5, "caller-loss": 5})
        self.assertFalse(vm.measurement_contract()["execution_supported"])


if __name__ == "__main__":
    unittest.main()
