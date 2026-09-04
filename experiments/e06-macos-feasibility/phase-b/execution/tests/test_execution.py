import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


EXECUTION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXECUTION / "scripts"))

import guard
import runner
import schedule
import verify_execution


def future_manifest(ledger):
    now = datetime.now(timezone.utc)
    approved = (now - timedelta(minutes=2)).isoformat()
    start = (now - timedelta(minutes=1)).isoformat()
    end = (now + timedelta(minutes=10)).isoformat()
    return {
        "format_version": "taskflow-e06-execution-manifest/v1-experimental",
        "manifest_id": "taskflow-e06-native-a",
        "phase_b_ticket": "TF-003.14",
        "candidate_id": "trusted-native-host",
        "operator": {"id": "@codex-tf-003-14"},
        "approval": {
            "approved_by": "reviewer",
            "approved_at": approved,
            "exact_mutation_scope": [
                f"Child writes under {guard.ROOT}",
                f"Runner evidence writes under {guard.EVIDENCE}",
                "CoreSimulatorService writes under /private/tmp/taskflow-e06-service-state",
            ],
            "plan_approval_is_not_execution_approval": True,
        },
        "host": {
            "resource_id": "taskflow-e06-local-mac17-7",
            "inventory_snapshot_sha256": "9e021a326cba6e3b3b92c6cfa9f274c531d5f9cf13b95a4f314f2afc95d80630",
            "exclusive_window_start": start,
            "exclusive_window_end": end,
        },
        "profile": {
            "expected_profile_digest": "a" * 64,
            "base_image_digest": None,
            "runner_digest": guard.implementation_component_hashes()["execution_files_sha256"],
            "sandbox_policy_digest": guard.implementation_component_hashes()["sandbox_policy_sha256"],
            "reset_policy_digest": guard.implementation_component_hashes()["reset_policy_sha256"],
        },
        "paths": {
            "mutable_root": guard.ROOT,
            "workspace_roots": [f"{guard.ROOT}/{name}/workspace" for name in guard.NAMESPACE_NAMES],
            "derived_data_roots": [f"{guard.ROOT}/{name}/DerivedData" for name in guard.NAMESPACE_NAMES],
            "custom_device_set_root": guard.DEVICE_SET,
            "default_simulator_set_forbidden": True,
        },
        "resources": {
            "concurrency_levels": [1, 2, 3, 4],
            "min_free_ram_gib": 16,
            "min_free_disk_gib": 200,
            "thermal_stop_signal": "serious",
            "per_command_timeout_seconds": 900,
        },
        "commands": guard.manifest_commands(ledger),
        "cleanup_allowlist": {
            "paths": [guard.ROOT, guard.DEVICE_SET, *[f"{guard.ROOT}/{name}" for name in guard.NAMESPACE_NAMES]],
            "vm_names": [],
            "simulator_name_prefix": guard.PREFIX,
            "immutable_base_delete_forbidden": True,
            "broad_process_kill_forbidden": True,
        },
        "evidence_root": guard.EVIDENCE,
    }


class ExecutionPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = guard.load_object(EXECUTION / "expanded-ledger.json")

    def test_repository_verifier(self):
        verify_execution.verify()

    def test_expanded_ledger_is_deterministic(self):
        self.assertEqual(self.ledger, schedule.build_ledger())
        self.assertEqual(9032, self.ledger["operation_count"])

    def test_recording_backend_reaches_no_native_or_filesystem_primitive(self):
        backend = runner.RecordingBackend()
        before_root = os.path.lexists(guard.ROOT)
        before_evidence = (verify_execution.REPOSITORY / guard.EVIDENCE).exists()
        with mock.patch("subprocess.run", side_effect=AssertionError("subprocess forbidden")), mock.patch("subprocess.Popen", side_effect=AssertionError("subprocess forbidden")), mock.patch("os.kill", side_effect=AssertionError("signal forbidden")), mock.patch("os.killpg", side_effect=AssertionError("group signal forbidden")), mock.patch.object(Path, "mkdir", side_effect=AssertionError("mkdir forbidden")), mock.patch.object(Path, "write_text", side_effect=AssertionError("write forbidden")), mock.patch.object(Path, "unlink", side_effect=AssertionError("unlink forbidden")):
            count = runner.run_ledger(self.ledger, backend)
        self.assertEqual(self.ledger["operation_count"], count)
        self.assertEqual(count, len(backend.records))
        self.assertEqual(before_root, os.path.lexists(guard.ROOT))
        self.assertEqual(before_evidence, (verify_execution.REPOSITORY / guard.EVIDENCE).exists())

    def test_path_traversal_is_rejected(self):
        self.assertFalse(guard.under_root(f"{guard.ROOT}/../outside"))
        changed = copy.deepcopy(self.ledger)
        changed["operations"][8]["targets"] = [f"{guard.ROOT}/../outside"]
        with self.assertRaises(guard.GuardError):
            guard.validate_ledger(changed)

    def test_default_device_set_is_rejected(self):
        changed = copy.deepcopy(self.ledger)
        operation = next(item for item in changed["operations"] if "--set" in item.get("argv", []))
        operation["argv"] = operation["argv"][:3] + ["/usr/bin/xcrun", "simctl", "list", "devices"]
        with self.assertRaises(guard.GuardError):
            guard.validate_ledger(changed)

    def test_mismatched_device_set_is_rejected(self):
        changed = copy.deepcopy(self.ledger)
        operation = next(item for item in changed["operations"] if "--set" in item.get("argv", []))
        index = operation["argv"].index("--set")
        operation["argv"][index + 1] = f"{guard.ROOT}/OtherCoreSimulator"
        with self.assertRaises(guard.GuardError):
            guard.validate_ledger(changed)

    def test_missing_network_denial_wrapper_is_rejected(self):
        changed = copy.deepcopy(self.ledger)
        operation = next(item for item in changed["operations"] if item["kind"] == "command")
        operation["argv"] = operation["argv"][3:]
        with self.assertRaises(guard.GuardError):
            guard.validate_ledger(changed)

    def test_old_allow_default_profile_is_rejected(self):
        changed = copy.deepcopy(self.ledger)
        operation = next(item for item in changed["operations"] if item["kind"] == "command")
        operation["argv"][2] = "(version 1) (allow default) (deny network*)"
        with self.assertRaises(guard.GuardError):
            guard.validate_ledger(changed)

    def test_every_child_command_has_deny_default_owned_write_profile(self):
        commands = [item for item in self.ledger["operations"] if item["kind"] in {"command", "child-command"}]
        self.assertTrue(commands)
        for operation in commands:
            self.assertEqual(["/usr/bin/sandbox-exec", "-p", guard.CHILD_SANDBOX_PROFILE], operation["argv"][:3])
        self.assertIn("(deny default)", guard.CHILD_SANDBOX_PROFILE)
        self.assertNotIn("(allow default)", guard.CHILD_SANDBOX_PROFILE)
        self.assertIn(f'(literal "{guard.ROOT}")', guard.CHILD_SANDBOX_PROFILE)
        self.assertIn(f'(subpath "{guard.ROOT}")', guard.CHILD_SANDBOX_PROFILE)

    def test_child_environment_is_sanitized_and_owned(self):
        operation = next(item for item in self.ledger["operations"] if item["kind"] == "child-command")
        environment = runner.child_environment(operation)
        self.assertEqual("/usr/bin:/bin:/usr/sbin:/sbin", environment["PATH"])
        self.assertNotIn("SSH_AUTH_SOCK", environment)
        self.assertNotIn("GITHUB_TOKEN", environment)
        for key in ("HOME", "TMPDIR", "CFFIXED_USER_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "CLANG_MODULE_CACHE_PATH", "SWIFT_MODULE_CACHE_PATH"):
            self.assertTrue(guard.under_root(environment[key]))

    def test_recorded_child_owns_new_process_group(self):
        operation = next(item for item in self.ledger["operations"] if item["kind"] == "child-command")
        backend = runner.NativeBackend(future_manifest(self.ledger))
        process = mock.Mock(pid=4242)
        with mock.patch("subprocess.Popen", return_value=process) as popen, mock.patch("os.getpgid", return_value=4242):
            record = backend._run_command(operation)
        self.assertEqual(4242, record["process_group"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(runner.child_environment(operation), popen.call_args.kwargs["env"])

    def test_signal_targets_only_recorded_unchanged_process_group(self):
        operation = next(item for item in self.ledger["operations"] if item.get("action") == "signal-recorded-child")
        handle = operation["targets"][0].split(":", 1)[1]
        process = mock.Mock(pid=4242, returncode=-15)
        process.poll.return_value = None
        process.communicate.return_value = ("", "")
        backend = runner.NativeBackend(future_manifest(self.ledger))
        backend.children[handle] = (process, 4242)
        with mock.patch("os.getpgid", return_value=4242), mock.patch("os.killpg") as kill_group:
            backend._run_effect(operation)
        kill_group.assert_called_once_with(4242, runner.signal.SIGTERM)

    def test_xcodebuild_without_explicit_derived_data_is_rejected(self):
        changed = copy.deepcopy(self.ledger)
        operation = next(item for item in changed["operations"] if "/usr/bin/xcodebuild" in item.get("argv", []) and "-project" in item["argv"])
        index = operation["argv"].index("-derivedDataPath")
        del operation["argv"][index:index + 2]
        with self.assertRaises(guard.GuardError):
            guard.validate_ledger(changed)

    def test_unrecorded_pid_handle_is_rejected(self):
        changed = copy.deepcopy(self.ledger)
        operation = next(item for item in changed["operations"] if item.get("action") == "signal-recorded-child")
        operation["targets"] = ["recorded-child:not-owned"]
        with self.assertRaises(guard.GuardError):
            guard.validate_ledger(changed)

    def test_changed_schedule_or_threshold_is_detectable(self):
        changed = copy.deepcopy(self.ledger)
        changed["operations"].pop()
        changed["operation_count"] -= 1
        self.assertNotEqual(schedule.build_ledger(), changed)
        spec = guard.load_object(EXECUTION / "schedule-spec.json")
        changed_spec = copy.deepcopy(spec)
        changed_spec["thresholds"]["warm-workspace-ready"]["p95_seconds"] = 3.1
        self.assertNotEqual(spec, changed_spec)

    def test_manifest_requires_exact_commands_and_approval(self):
        manifest = future_manifest(self.ledger)
        guard.validate_manifest(manifest, self.ledger, require_current_window=True)
        manifest["commands"] = manifest["commands"][:-1]
        with self.assertRaises(guard.GuardError):
            guard.validate_manifest(manifest, self.ledger, require_current_window=False)
        manifest = future_manifest(self.ledger)
        manifest["approval"]["approved_by"] = ""
        with self.assertRaises(guard.GuardError):
            guard.validate_manifest(manifest, self.ledger, require_current_window=False)

    def test_stale_approval_window_is_rejected(self):
        manifest = future_manifest(self.ledger)
        manifest["host"]["exclusive_window_start"] = "2000-01-01T00:00:00Z"
        manifest["host"]["exclusive_window_end"] = "2000-01-01T01:00:00Z"
        with self.assertRaises(guard.GuardError):
            guard.validate_manifest(manifest, self.ledger, require_current_window=True)

    def test_manifest_digest_binding_rejects_changed_bytes(self):
        manifest = future_manifest(self.ledger)
        with tempfile.TemporaryDirectory(prefix="taskflow-e06-binding-test-") as temporary:
            root = Path(temporary)
            manifest_path = root / "execution-manifest.approved.json"
            binding_path = root / "implementation-binding.approved.json"
            host_path = root / "host-attestation.approved.json"
            core_path = root / "coresimulator-attestation.approved.json"
            manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
            host_path.write_text(json.dumps({
                "format_version": "taskflow-e06-host-attestation/v1-experimental",
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "resource_id": "taskflow-e06-local-mac17-7",
                "expected_profile_digest": "a" * 64,
                "free_ram_gib": 32,
                "free_disk_gib": 300,
                "thermal_state": "nominal",
                "exclusive_window_confirmed": True,
                "mutable_root_absent": True,
            }, sort_keys=True) + "\n", encoding="utf-8")
            core_path.write_text(json.dumps({
                "format_version": "taskflow-e06-coresimulator-attestation/v1-experimental",
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "custom_device_set_root": guard.DEVICE_SET,
                "runtime_identifier": "com.apple.CoreSimulator.SimRuntime.iOS-26-5",
                "runtime_build": "23F77",
                "architectures": ["arm64"],
                "device_type": "com.apple.CoreSimulator.SimDeviceType.iPhone-17",
                "custom_set_accessible": True,
                "default_device_set_accessed": False,
                "preexisting_experiment_devices": [],
                "service_side_boundary_verified": True,
                "service_side_boundary_mechanism": "dedicated-host",
                "service_side_write_paths": ["/private/tmp/taskflow-e06-service-state"],
                "service_side_cleanup_policy_sha256": "6" * 64,
            }, sort_keys=True) + "\n", encoding="utf-8")
            manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            components = guard.implementation_component_hashes()
            binding = {
                "format_version": "taskflow-e06-implementation-binding/v1-experimental",
                "implementation_commit": "1" * 40,
                "implementation_tree": "2" * 40,
                "manifest_sha256": manifest_digest,
                **components,
                "host_attestation_sha256": hashlib.sha256(host_path.read_bytes()).hexdigest(),
                "coresimulator_attestation_sha256": hashlib.sha256(core_path.read_bytes()).hexdigest(),
                "approved_by": manifest["approval"]["approved_by"],
                "approved_at": manifest["approval"]["approved_at"],
                "exclusive_window_start": manifest["host"]["exclusive_window_start"],
                "exclusive_window_end": manifest["host"]["exclusive_window_end"],
            }
            binding_path.write_text(json.dumps(binding, sort_keys=True) + "\n", encoding="utf-8")
            def fake_git(*arguments):
                return "2" * 40 if arguments[-1] == "HEAD^{tree}" else "1" * 40
            with mock.patch.object(guard, "APPROVED_MANIFEST", manifest_path), mock.patch.object(guard, "APPROVED_BINDING", binding_path), mock.patch.object(guard, "APPROVED_HOST_ATTESTATION", host_path), mock.patch.object(guard, "APPROVED_CORESIMULATOR_ATTESTATION", core_path), mock.patch.object(guard, "git_value", side_effect=fake_git):
                guard.validate_execution_binding(manifest_path, binding_path, self.ledger)
                for field in components:
                    drifted = dict(components)
                    drifted[field] = ("0" if components[field][0] != "0" else "1") + components[field][1:]
                    with self.subTest(component=field), mock.patch.object(guard, "implementation_component_hashes", return_value=drifted):
                        with self.assertRaisesRegex(guard.GuardError, "component digest drifted"):
                            guard.validate_execution_binding(manifest_path, binding_path, self.ledger)
                manifest["approval"]["approved_by"] = "changed-reviewer"
                manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
                with self.assertRaises(guard.GuardError):
                    guard.validate_execution_binding(manifest_path, binding_path, self.ledger)

    def test_inventory_digest_binds_path_and_changed_bytes(self):
        with tempfile.TemporaryDirectory(prefix="taskflow-e06-inventory-") as temporary:
            repository = Path(temporary)
            (repository / "component").write_bytes(b"one\n")
            before = guard.inventory_sha256(("component",), repository)
            (repository / "component").write_bytes(b"two\n")
            self.assertNotEqual(before, guard.inventory_sha256(("component",), repository))
        self.assertEqual("experiments/e06-macos-feasibility/phase-b/frozen-artifacts.json", guard.COMPONENT_PATHS["phase_b_frozen_artifacts_sha256"])

    def test_every_operation_has_exact_scope_and_semantic_cleanup(self):
        for operation in self.ledger["operations"]:
            self.assertIn("namespace", operation)
            self.assertIsInstance(operation["repetition"], int)
            self.assertIn("cleanup_action", operation)
        create = next(item for item in self.ledger["operations"] if item.get("argv", [None] * 8)[7:8] == ["create"])
        cleanup_ids = create["cleanup_action"]["on_success"]["operation_ids"]
        cleanups = [next(item for item in self.ledger["operations"] if item["id"] == identifier) for identifier in cleanup_ids]
        self.assertTrue(any(item.get("argv", [None] * 8)[7:8] == ["delete"] and create["targets"][0] in item["targets"] for item in cleanups))
        build = next(item for item in self.ledger["operations"] if item.get("argv", [None] * 4)[3:4] == ["/usr/bin/xcodebuild"] and item["kind"] == "command" and "build" in item["argv"])
        build_cleanup = [next(item for item in self.ledger["operations"] if item["id"] == identifier) for identifier in build["cleanup_action"]["on_success"]["operation_ids"]]
        self.assertTrue(any(item.get("argv", [])[3:6] == ["/bin/rm", "-rf", "--"] for item in build_cleanup))
        identity = next(item for item in self.ledger["operations"] if item["id"].endswith(".identity"))
        self.assertEqual("retain-orphan", identity["cleanup_action"]["on_failure"]["disposition"])
        evidence = next(item for item in self.ledger["operations"] if item.get("action") == "emit-benchmark-v2-and-decision")
        self.assertEqual("approved-evidence-retained", evidence["cleanup_action"]["on_success"]["reason"])

    def test_invalid_cleanup_mappings_are_rejected(self):
        for mutate in ("missing", "nonexistent", "earlier", "noncleanup"):
            changed = copy.deepcopy(self.ledger)
            operation = next(item for item in changed["operations"] if item["id"].endswith(".create") and item["cleanup_action"]["on_success"]["disposition"] == "later-operations")
            if mutate == "missing":
                del operation["cleanup_action"]
            elif mutate == "nonexistent":
                operation["cleanup_action"]["on_success"]["operation_ids"] = ["not-present"]
            elif mutate == "earlier":
                operation["cleanup_action"]["on_success"]["operation_ids"] = ["setup.controller-roots"]
            else:
                operation["cleanup_action"]["on_success"]["operation_ids"] = [next(item["id"] for item in changed["operations"] if item["id"] > operation["id"] and item["kind"] == "command" and item["mutates"])]
            with self.subTest(mutation=mutate), self.assertRaises(guard.GuardError):
                guard.validate_ledger(changed)

    def test_builds_have_live_profile_and_output_install_reset_attestations(self):
        operations = self.ledger["operations"]
        by_id = {item["id"]: item for item in operations}
        builds = [item for item in operations if item.get("argv", [None] * 4)[3:4] == ["/usr/bin/xcodebuild"] and "build" in item.get("argv", [])]
        self.assertTrue(builds)
        for build in builds:
            self.assertEqual(1, len(build["prerequisites"]))
            profile = by_id[build["prerequisites"][0]]
            self.assertEqual("attest-live-profile", profile.get("action"))
            self.assertEqual(9, len(profile["parameters"]["source_operation_ids"]))
            if build["kind"] == "command":
                self.assertIn(build["id"] + ".verify-output", by_id)
        self.assertTrue(all(item["parameters"]["timed_operation_ids"][-2:] == [item["parameters"]["identity_operation_id"], item["parameters"]["installation_service_operation_id"]] for item in operations if item.get("action") == "record-timing-and-attest-simulator-identity"))
        self.assertTrue(any(item.get("action") == "verify-installed-bundle-identity" for item in operations))
        reset = [item for item in operations if item.get("action") == "attest-reset-reusable-state"]
        self.assertTrue(reset)
        for item in reset:
            self.assertEqual(guard.implementation_component_hashes()["reset_policy_sha256"], item["parameters"]["reset_policy_sha256"])

    def test_live_profile_is_derived_and_missing_or_drifted_output_fails(self):
        identifiers = [f"profile-{index}" for index in range(9)]
        outputs = [
            "26.5.2", "25F84", "arm64", "Xcode 26.6\nBuild version 17F113",
            "26.5", "23F81a", "26.5", "23F81a",
            json.dumps({"runtimes": [{"identifier": "com.apple.CoreSimulator.SimRuntime.iOS-26-5", "buildversion": "23F77", "supportedArchitectures": ["arm64"]}]}),
        ]
        backend = runner.NativeBackend(future_manifest(self.ledger))
        backend.results.update({identifier: {"status": "passed", "stdout": output} for identifier, output in zip(identifiers, outputs)})
        profile = backend._live_profile(identifiers)
        expected = guard.canonical_sha256(profile)
        self.assertEqual(expected, backend._compare_profile(profile, expected))
        with self.assertRaisesRegex(guard.GuardError, "digest mismatch"):
            backend._compare_profile(profile, "0" * 64)
        backend.results[identifiers[0]]["stdout"] = ""
        with self.assertRaisesRegex(guard.GuardError, "output missing"):
            backend._live_profile(identifiers)

    def test_simulator_ready_wall_boundary_requires_identity_and_install_service(self):
        operation = next(item for item in self.ledger["operations"] if item.get("action") == "record-timing-and-attest-simulator-identity")
        parameters = operation["parameters"]
        backend = runner.NativeBackend(future_manifest(self.ledger))
        for index, identifier in enumerate(parameters["timed_operation_ids"]):
            backend.results[identifier] = {"status": "passed", "started_monotonic_ns": index * 1_000_000_000, "ended_monotonic_ns": (index + 1) * 1_000_000_000, "duration_ns": 1_000_000_000, "started_at_utc": "2026-09-04T10:00:00+00:00", "stdout": ""}
        backend.results[parameters["identity_operation_id"]]["stdout"] = json.dumps({"devices": {"runtime": [{"name": parameters["expected_device_name"], "state": "Booted"}]}})
        backend.results[parameters["installation_service_operation_id"]]["observed_result"] = "success"
        result = backend._run_effect(operation)
        self.assertEqual(float(len(parameters["timed_operation_ids"])), result["duration_seconds"])
        changed = copy.deepcopy(operation)
        changed["parameters"]["timed_operation_ids"] = changed["parameters"]["timed_operation_ids"][:-1]
        with self.assertRaisesRegex(guard.GuardError, "omits"):
            backend._run_effect(changed)

    def test_build_install_and_reset_handlers_fail_closed(self):
        backend = runner.NativeBackend(future_manifest(self.ledger))
        build = next(item for item in self.ledger["operations"] if item.get("action") == "verify-build-output-manifest")
        with self.assertRaises(guard.GuardError):
            backend._run_effect(build)
        install = next(item for item in self.ledger["operations"] if item.get("action") == "verify-installed-bundle-identity")
        backend.results[install["parameters"]["container_operation_id"]] = {"status": "passed", "stdout": "/unowned/app"}
        with self.assertRaisesRegex(guard.GuardError, "outside"):
            backend._run_effect(install)
        reset = copy.deepcopy(next(item for item in self.ledger["operations"] if item.get("action") == "attest-reset-reusable-state"))
        reset["parameters"]["reset_policy_sha256"] = "0" * 64
        with self.assertRaisesRegex(guard.GuardError, "policy digest"):
            backend._run_effect(reset)

    def test_reset_attestation_success_has_no_self_reference_and_rejects_canary(self):
        operation = copy.deepcopy(next(item for item in self.ledger["operations"] if item.get("action") == "attest-reset-reusable-state" and item["phase"] == "timing.mobile-lifecycle"))
        self.assertNotIn(operation["id"], operation["parameters"]["reset_operation_ids"])
        with tempfile.TemporaryDirectory(prefix="taskflow-e06-reset-success-", dir="/private/tmp") as temporary, mock.patch.object(guard, "ROOT", temporary):
            namespace_root = Path(temporary) / "namespace-a"
            empty_paths = [namespace_root / name for name in ("workspace", "home", "tmp", "DerivedData", "results")]
            for path in empty_paths:
                path.mkdir(parents=True, exist_ok=True)
            canaries = [str(path / ".taskflow-e06-reset-canary") for path in empty_paths]
            operation["parameters"].update({"namespace_root": str(namespace_root), "expected_empty_paths": [str(path) for path in empty_paths], "reset_canary_paths": canaries})
            backend = runner.NativeBackend(future_manifest(self.ledger))
            for index, identifier in enumerate(operation["parameters"]["reset_operation_ids"]):
                backend.results[identifier] = {"status": "passed", "started_monotonic_ns": index, "ended_monotonic_ns": index + 1, "duration_ns": 1}
            expected_state = operation["parameters"]["expected_device_state"]
            devices = [] if expected_state == "absent" else [{"name": operation["parameters"]["device_name"], "state": "Shutdown"}]
            backend.results[operation["parameters"]["identity_operation_id"]] = {"status": "passed", "stdout": json.dumps({"devices": {"runtime": devices}})}
            self.assertEqual(expected_state, backend._run_effect(operation)["reusable_state"])
            Path(canaries[0]).write_text("retained\n", encoding="utf-8")
            with self.assertRaisesRegex(guard.GuardError, "residue|canary"):
                backend._run_effect(operation)

    def test_reset_policy_order_and_independent_cleanup_samples(self):
        operations = self.ledger["operations"]
        positions = {item["id"]: index for index, item in enumerate(operations)}
        reset_results = [item for item in operations if item.get("action") == "record-reset-cleanup-timings-and-residue"]
        cleanup_results = [item for item in operations if item.get("action") == "record-cleanup-timing-and-residue"]
        self.assertEqual(45, len(reset_results))
        self.assertEqual(45, len(cleanup_results))
        for result in reset_results:
            ids = result["parameters"]["reset_operation_ids"]
            rows = [operations[positions[identifier]] for identifier in ids]
            self.assertEqual("shutdown", rows[0]["argv"][7])
            self.assertIn(rows[1]["argv"][7], {"erase", "delete"})
            self.assertEqual(["/bin/rm", "-rf", "--"], rows[2]["argv"][3:6])
            self.assertEqual("/bin/mkdir", rows[3]["argv"][3])
            self.assertEqual("probe-reset-residue", rows[4]["action"])
            self.assertEqual("attest-reset-reusable-state", rows[-1]["action"])
            cleanup_ids = set(result["parameters"]["cleanup_operation_ids"])
            self.assertFalse(set(ids) & cleanup_ids)
        for result in cleanup_results:
            self.assertTrue(result["parameters"]["preparation_operation_ids"])
            self.assertTrue(all(positions[identifier] < positions[result["parameters"]["cleanup_operation_ids"][0]] for identifier in result["parameters"]["preparation_operation_ids"]))

    def test_lifecycle_metrics_keep_distinct_utc_starts_and_verified_preparation_chains(self):
        operation = copy.deepcopy(next(item for item in self.ledger["operations"] if item.get("action") == "record-build-install-test-timings-and-structured-result"))
        parameters = operation["parameters"]
        expected_times = {
            "xcode-build": "2026-09-04T10:00:01Z",
            "simulator-install": "2026-09-04T10:00:02Z",
            "mobile-test": "2026-09-04T10:00:03Z",
        }
        backend = runner.NativeBackend(future_manifest(self.ledger))
        for metric, boundary in zip(parameters["metrics"], parameters["timed_operation_boundaries"]):
            for offset, identifier in enumerate(boundary):
                backend.results[identifier] = {
                    "status": "passed",
                    "started_at_utc": expected_times[metric] if offset == 0 else "2026-09-04T10:00:09Z",
                    "started_monotonic_ns": offset,
                    "ended_monotonic_ns": offset + 1,
                    "duration_ns": 1,
                }
        for preparation in parameters["preparation_operation_ids_by_metric"].values():
            for identifier in preparation:
                backend.results.setdefault(identifier, {"status": "passed"})
        backend.results[parameters["identity_operation_id"]] = {"status": "passed", "stdout": json.dumps({"devices": {"runtime": [{"name": parameters["expected_device_name"], "state": "Booted"}]}})}
        backend.results[parameters["timed_operation_ids"][-1]].update({"stdout": 'TASKFLOW_E06_RESULT:{"status":"ok","namespace":"namespace-a"}\n'})
        memory, disk, thermal = parameters["capacity_operation_ids"]
        backend.results[memory] = {"status": "passed", "stdout": "Mach Virtual Memory Statistics: (page size of 4096 bytes)\nPages free: 5000000.\nPages inactive: 1.\nPages speculative: 1.\n"}
        backend.results[disk] = {"status": "passed", "stdout": "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/test 1 1 314572800 1% /\n"}
        backend.results[thermal] = {"status": "passed", "stdout": "0\n"}
        result = backend._run_effect(operation)
        self.assertEqual(expected_times, result["sample_started_at_utc_by_metric"])
        chains = result["preparation_operation_ids_by_metric"]
        build_boundary, install_boundary, launch_boundary = parameters["timed_operation_boundaries"]
        self.assertTrue(chains["xcode-build"])
        self.assertTrue(set(chains["xcode-build"]).isdisjoint(build_boundary))
        self.assertEqual(chains["xcode-build"] + build_boundary, chains["simulator-install"])
        self.assertEqual(chains["simulator-install"] + install_boundary, chains["mobile-test"])
        self.assertIn(next(identifier for identifier in build_boundary if identifier.endswith("verify-output")), chains["simulator-install"])
        self.assertIn(next(identifier for identifier in install_boundary if identifier.endswith("verify-installed")), chains["mobile-test"])
        self.assertTrue(set(chains["mobile-test"]).isdisjoint(launch_boundary))

    def test_benchmark_records_align_validate_and_reproduce_deterministically(self):
        operation = next(item for item in self.ledger["operations"] if item.get("action") == "emit-benchmark-v2-and-decision")
        manifest = future_manifest(self.ledger)
        backend = runner.NativeBackend(manifest, self.ledger, source_revision="e" * 40)
        timestamp = "2026-09-04T10:00:00Z"
        backend.results.update({
            "attest.hardware-cpu": {"status": "passed", "stdout": "Apple M4 Max"},
            "attest.hardware-cores": {"status": "passed", "stdout": "12"},
            "attest.hardware-ram": {"status": "passed", "stdout": str(64 * 1024 ** 3)},
            "attestation.initial.profile.compare": {"status": "passed", "profile": {"macos_version": "26.5.2", "macos_build": "25F84", "architecture": "arm64", "xcode_version": "26.6", "xcode_build": "17F113"}},
            "concurrency": {"status": "passed", "concurrency": 4},
            "cleanup.assert-no-owned-devices-or-record-orphans": {"status": "passed", "orphan_count": 0},
            "cleanup.remove-owned-root": {"status": "passed"},
            "cleanup.verify-absence": {"status": "passed", "orphan_count": 0},
        })
        for repetition in range(1, 31):
            backend.results[f"warm-{repetition}"] = {"status": "passed", "metric": "warm-workspace-ready", "repetition": repetition, "duration_seconds": 1.0, "sample_started_at_utc": timestamp, "preparation_operation_ids": [f"warm-{repetition}-remove", f"warm-{repetition}-mkdir"]}
        for mechanism in schedule.MECHANISMS:
            for repetition in range(1, 31):
                backend.results[f"ready-{mechanism}-{repetition}"] = {"status": "passed", "metric": "simulator-ready-to-install", "mechanism": mechanism, "repetition": repetition, "duration_seconds": 2.0, "sample_started_at_utc": timestamp, "preparation_operation_ids": [f"ready-{mechanism}-{repetition}-prepare"]}
            for repetition in range(1, 16):
                common = {"status": "passed", "mechanism": mechanism, "repetition": repetition, "sample_started_at_utc": timestamp, "preparation_operation_ids": [f"lifecycle-{mechanism}-{repetition}-prepare"]}
                lifecycle_metrics = {"xcode-build": 3.0, "simulator-install": 1.0, "mobile-test": 1.0}
                backend.results[f"lifecycle-{mechanism}-{repetition}"] = {
                    "status": "passed",
                    "mechanism": mechanism,
                    "repetition": repetition,
                    "metrics": lifecycle_metrics,
                    "sample_started_at_utc_by_metric": {metric: timestamp for metric in lifecycle_metrics},
                    "preparation_operation_ids_by_metric": {metric: [f"lifecycle-{mechanism}-{repetition}-{metric}-prepare"] for metric in lifecycle_metrics},
                }
                backend.results[f"reset-{mechanism}-{repetition}"] = {**common, "metrics": {"candidate-reset": 1.0, "candidate-cleanup": 1.0}, "orphan_count": 0}
        with tempfile.TemporaryDirectory(prefix="taskflow-e06-benchmark-") as temporary, mock.patch.object(runner, "REPOSITORY", Path(temporary)):
            missing_cleanup = backend.results.pop("cleanup.verify-absence")
            with self.assertRaisesRegex(guard.GuardError, "result missing"):
                backend._run_effect(operation)
            self.assertFalse(any((Path(temporary) / path).exists() for path in operation["parameters"]["output_paths"]))
            backend.results["cleanup.verify-absence"] = missing_cleanup
            missing_sample = backend.results.pop("warm-30")
            with self.assertRaisesRegex(guard.GuardError, "incomplete/duplicated"):
                backend._run_effect(operation)
            backend.results["warm-30"] = missing_sample
            backend.results["warm-30"]["repetition"] = 29
            with self.assertRaisesRegex(guard.GuardError, "incomplete/duplicated"):
                backend._run_effect(operation)
            backend.results["warm-30"]["repetition"] = 30
            result = backend._run_effect(operation)
            self.assertEqual(19, result["record_count"])
            record_paths = operation["parameters"]["output_paths"][:-2]
            before = {path: (Path(temporary) / path).read_bytes() for path in operation["parameters"]["output_paths"]}
            backend._run_effect(operation)
            self.assertEqual(before, {path: (Path(temporary) / path).read_bytes() for path in operation["parameters"]["output_paths"]})
            for path, (metric, mechanism) in zip(record_paths, schedule.BENCHMARK_SERIES):
                record = json.loads((Path(temporary) / path).read_text(encoding="utf-8"))
                self.assertEqual("taskflow-t1-benchmark/v2", record["schema_version"])
                self.assertIn(metric, path)
                if mechanism:
                    self.assertIn(mechanism, path)
                self.assertEqual(30 if metric in {"warm-workspace-ready", "simulator-ready-to-install"} else 15, record["sample_count"])
                self.assertNotEqual(manifest["approval"]["approved_at"], record["timestamp"])
                self.assertTrue(record["preparation_command"].startswith("python3 experiments/e06-macos-feasibility/phase-b/execution/scripts/runner.py --execute"))
                self.assertEqual(record["sample_count"], len(record["sample_preparation_operation_ids"]))
            validator = Path(temporary) / "validator"
            validator.mkdir()
            (validator / "go.mod").write_text(f"module taskflow-e06-record-validator\n\ngo 1.25.12\n\nrequire github.com/alessandro-rizzo/taskflow/fixtures/t1-benchmark-harness v0.0.0\nreplace github.com/alessandro-rizzo/taskflow/fixtures/t1-benchmark-harness => {verify_execution.REPOSITORY / 'fixtures/t1-benchmark-harness'}\n", encoding="utf-8")
            (validator / "main.go").write_text('package main\nimport ("encoding/json"; "os"; benchmark "github.com/alessandro-rizzo/taskflow/fixtures/t1-benchmark-harness")\nfunc main(){ for _, p := range os.Args[1:] { f,e:=os.Open(p); if e!=nil { panic(e) }; var r benchmark.Record; if e=json.NewDecoder(f).Decode(&r); e!=nil { panic(e) }; if e=benchmark.Validate(r); e!=nil { panic(e) } } }\n', encoding="utf-8")
            environment = {"PATH": os.environ["PATH"], "HOME": temporary, "GOCACHE": str(Path(temporary) / "go-cache"), "GOMODCACHE": str(Path(temporary) / "go-mod-cache")}
            completed = subprocess.run(["go", "run", ".", *[str(Path(temporary) / path) for path in record_paths]], cwd=validator, env=environment, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(0, completed.returncode, completed.stderr)
            decision = json.loads((Path(temporary) / operation["parameters"]["output_paths"][-1]).read_text())
            self.assertEqual("trusted-native-host", decision["recommendation"])
            self.assertFalse(decision["adr_edit_performed"])

    def test_caller_loss_lease_uses_injected_clock_and_w3_order(self):
        class FakeClock:
            def __init__(self):
                self.now = 10_000_000_000
                self.waits = []
            def __call__(self):
                return self.now
            def wait(self, seconds):
                self.waits.append(seconds)
                self.now += int(seconds * 1_000_000_000)

        clock = FakeClock()
        with tempfile.TemporaryDirectory(prefix="taskflow-e06-lease-test-", dir="/private/tmp") as temporary, mock.patch.object(guard, "ROOT", temporary):
            lease_dir = Path(temporary) / "controller" / "leases"
            lease_dir.mkdir(parents=True)
            lease_path = str(lease_dir / "lease.json")
            backend = runner.NativeBackend(future_manifest(self.ledger), monotonic_ns=clock, wait=clock.wait)
            backend.results["identity"] = {"status": "passed", "stdout": json.dumps({"devices": {"runtime": [{"name": "taskflow-e06-native-a-test", "state": "Booted"}]}})}
            create = {"action": "create-supervised-caller-lease", "parameters": {"lease_id": "lease-test", "lease_path": lease_path, "namespace": "namespace-a", "device_name": "taskflow-e06-native-a-test", "identity_operation_id": "identity", "ttl_seconds": 1.0, "heartbeat_seconds": 0.25}, "targets": [lease_path]}
            backend._run_effect(create)
            backend.results["signal"] = {"status": "passed", "returncode": -15}
            expire = {"action": "observe-caller-lease-expiry", "parameters": {"lease_id": "lease-test", "lease_path": lease_path, "signal_operation_id": "signal", "ttl_seconds": 1.0, "heartbeat_seconds": 0.25}, "targets": [lease_path]}
            result = backend._run_effect(expire)
            self.assertEqual(["lease.heartbeat.missed", "lease.expired", "orphan.detected"], [item["event"] for item in result["events"]])
            self.assertTrue(clock.waits)
            backend.results.update({
                "shutdown": {"status": "passed", "started_monotonic_ns": 11_000_000_000, "ended_monotonic_ns": 11_100_000_000, "duration_ns": 100_000_000},
                "delete": {"status": "passed", "started_monotonic_ns": 11_100_000_000, "ended_monotonic_ns": 11_200_000_000, "duration_ns": 100_000_000},
                "remove": {"status": "passed", "started_monotonic_ns": 11_200_000_000, "ended_monotonic_ns": 11_300_000_000, "duration_ns": 100_000_000},
                "list": {"status": "passed", "stdout": json.dumps({"devices": {}})},
            })
            reclaim = {"action": "verify-caller-loss-reclaim-order-and-deadline", "parameters": {"lease_id": "lease-test", "lease_path": lease_path, "namespace": "namespace-a", "device_name": "taskflow-e06-native-a-test", "expiry_operation_id": "expire", "cleanup_operation_ids": ["shutdown", "delete", "remove"], "post_cleanup_identity_operation_id": "list", "cleanup_grace_seconds": 30.0, "expected_events": ["lease.heartbeat.missed", "lease.expired", "orphan.detected", "orphan.reclaimed"]}, "targets": [lease_path]}
            backend.results["remove"]["ended_monotonic_ns"] = 41_000_000_001
            with self.assertRaisesRegex(guard.GuardError, "exceeded"):
                backend._run_effect(reclaim)
            backend.results["remove"]["ended_monotonic_ns"] = 11_300_000_000
            reclaimed = backend._run_effect(reclaim)
            self.assertEqual("reclaimed", reclaimed["state"])
            self.assertEqual(reclaim["parameters"]["expected_events"], [item["event"] for item in reclaimed["events"]])

    def test_failed_effect_records_exact_owned_state_and_stops(self):
        backend = runner.NativeBackend(future_manifest(self.ledger))
        evidence = []
        with mock.patch.object(backend, "_run_effect", side_effect=guard.GuardError("forced failure")), mock.patch.object(backend, "_write_record", side_effect=lambda operation, record: evidence.append((operation, record))):
            with self.assertRaises(guard.GuardError):
                runner.run_ledger(self.ledger, backend)
        self.assertEqual(1, len(evidence))
        operation, record = evidence[0]
        self.assertEqual("gate.profile-mismatch", operation["id"])
        self.assertEqual("failed", record["status"])
        self.assertEqual(operation["targets"], record["retained_owned_state"]["targets"])
        self.assertNotIn(self.ledger["operations"][1]["id"], backend.results)

    def test_signal_timeout_records_exact_pid_and_process_group(self):
        operation = next(item for item in self.ledger["operations"] if item.get("action") == "signal-recorded-child")
        handle = operation["targets"][0].split(":", 1)[1]
        process = mock.Mock(pid=4242)
        process.poll.return_value = None
        process.communicate.side_effect = runner.subprocess.TimeoutExpired(cmd="owned-child", timeout=30)
        backend = runner.NativeBackend(future_manifest(self.ledger))
        backend.children[handle] = (process, 4242)
        backend.results[operation["prerequisites"][0]] = {"status": "started", "started_monotonic_ns": 1}
        evidence = []
        with mock.patch("os.getpgid", return_value=4242), mock.patch("os.killpg"), mock.patch.object(backend, "_write_record", side_effect=lambda item, record: evidence.append(record)):
            with self.assertRaises(runner.RunnerError):
                backend.run(operation)
        self.assertEqual(1, len(evidence))
        self.assertEqual((handle, 4242, 4242), (evidence[0]["retained_owned_state"]["child_handle"], evidence[0]["retained_owned_state"]["pid"], evidence[0]["retained_owned_state"]["process_group"]))
        self.assertEqual(operation["parameters"]["retained_owned_targets"], evidence[0]["retained_owned_state"]["targets"])
        self.assertFalse(evidence[0]["cleanup_attempted"])

    def test_expected_failure_is_typed_and_mismatch_rejected(self):
        operation = next(item for item in self.ledger["operations"] if item.get("expected_result") == "failure")
        backend = runner.NativeBackend(future_manifest(self.ledger))
        completed = mock.Mock(returncode=1, stdout="rejected", stderr="")
        with mock.patch("subprocess.run", return_value=completed):
            record = backend._run_command(operation)
        self.assertEqual(("failure", "passed"), (record["observed_result"], record["status"]))
        completed.returncode = 0
        with mock.patch("subprocess.run", return_value=completed), mock.patch.object(backend, "_write_record"):
            with self.assertRaisesRegex(runner.RunnerError, "result mismatch"):
                backend._run_command(operation)

    def test_strict_p95_equal_threshold_is_rejected(self):
        operation = next(item for item in self.ledger["operations"] if item.get("action") == "aggregate-strict-p95")
        backend = runner.NativeBackend(future_manifest(self.ledger))
        for identifier in operation["parameters"]["sample_result_ids"]:
            backend.results[identifier] = {"status": "passed", "duration_seconds": operation["parameters"]["strict_p95_seconds"]}
        with self.assertRaises(guard.GuardError):
            backend._run_effect(operation)

    def test_parallel_cleanup_uses_wall_interval_not_duration_sum(self):
        operation = next(item for item in self.ledger["operations"] if item.get("action") == "record-capacity-and-assert-all-hard-gates" and item["parameters"]["concurrency"] == 4)
        backend = runner.NativeBackend(future_manifest(self.ledger))
        for identifier in operation["parameters"]["cleanup_operation_ids"]:
            backend.results[identifier] = {"status": "passed", "started_monotonic_ns": 1_000_000_000, "ended_monotonic_ns": 11_000_000_000, "duration_ns": 10_000_000_000}
        self.assertEqual(10.0, backend._wall_duration_seconds(operation["parameters"]["cleanup_operation_ids"]))
        self.assertEqual(10.0 * len(operation["parameters"]["cleanup_operation_ids"]), backend._duration_seconds(operation["parameters"]["cleanup_operation_ids"]))

    def test_simulator_identity_mismatch_is_rejected(self):
        backend = runner.NativeBackend(future_manifest(self.ledger))
        backend.results["identity"] = {"status": "passed", "stdout": json.dumps({"devices": {"runtime": [{"name": "wrong", "state": "Booted"}]}})}
        with self.assertRaises(guard.GuardError):
            backend._attest_device("identity", "expected")

    def test_capacity_threshold_and_thermal_stop_are_rejected(self):
        backend = runner.NativeBackend(future_manifest(self.ledger))
        backend.results.update({
            "memory": {"status": "passed", "stdout": "Mach Virtual Memory Statistics: (page size of 4096 bytes)\nPages free: 1.\nPages inactive: 1.\nPages speculative: 1.\n"},
            "disk": {"status": "passed", "stdout": "Filesystem 1024-blocks Used Available Capacity Mounted on\nx 1 1 314572800 1% /private/tmp\n"},
            "thermal": {"status": "passed", "stdout": "2\n"},
        })
        with self.assertRaises(guard.GuardError):
            backend._capacity(["memory", "disk", "thermal"])

    def test_lost_session_requires_failed_use_clean_retry_and_absence(self):
        operation = next(item for item in self.ledger["operations"] if item.get("action") == "assert-lost-session-rejected-and-clean-retry-possible")
        parameters = operation["parameters"]
        backend = runner.NativeBackend(future_manifest(self.ledger))
        backend.results[parameters["lost_use_operation_id"]] = {"status": "passed", "expected_result": "failure", "observed_result": "success", "stdout": ""}
        with self.assertRaises(guard.GuardError):
            backend._run_effect(operation)

    def test_reset_and_cleanup_metrics_have_distinct_operation_sets(self):
        operations = [item for item in self.ledger["operations"] if item.get("action") == "record-reset-cleanup-timings-and-residue"]
        self.assertEqual(45, len(operations))
        for operation in operations:
            reset = set(operation["parameters"]["reset_operation_ids"])
            cleanup = set(operation["parameters"]["cleanup_operation_ids"])
            self.assertTrue(reset)
            self.assertTrue(cleanup)
            self.assertFalse(reset & cleanup)

    def test_parallel_groups_are_actually_dispatched_concurrently(self):
        first_group = next(item["parallel_group"] for item in self.ledger["operations"] if "parallel_group" in item)
        first_step = next(item["parallel_step"] for item in self.ledger["operations"] if item.get("parallel_group") == first_group)
        grouped_ids = [item["id"] for item in self.ledger["operations"] if item.get("parallel_group") == first_group and item.get("parallel_step") == first_step]
        barrier = threading.Barrier(len(grouped_ids), timeout=2)
        backend = runner.NativeBackend(future_manifest(self.ledger))
        observed = []
        def record(operation):
            if operation["id"] in grouped_ids:
                observed.append(operation["id"])
                barrier.wait()
        with mock.patch.object(backend, "run", side_effect=record):
            runner.run_ledger(self.ledger, backend)
        self.assertEqual(set(grouped_ids), set(observed))

    def test_collision_and_cleanup_deadline_fail_closed(self):
        collision = copy.deepcopy(next(item for item in self.ledger["operations"] if item.get("action") == "assert-zero-path-device-lease-or-identity-collision"))
        collision["parameters"]["lease_ids"][1] = collision["parameters"]["lease_ids"][0]
        backend = runner.NativeBackend(future_manifest(self.ledger))
        with self.assertRaises(guard.GuardError):
            backend._run_effect(collision)

        cleanup = next(item for item in self.ledger["operations"] if item.get("action") == "assert-cleanup-deadline-or-exact-orphan")
        signal_id = cleanup["parameters"]["signal_operation_id"]
        cleanup_id = cleanup["parameters"]["cleanup_operation_id"]
        backend.results[signal_id] = {"status": "passed", "started_monotonic_ns": 0, "ended_monotonic_ns": 1}
        backend.results[cleanup_id] = {"status": "passed", "started_monotonic_ns": 1, "ended_monotonic_ns": 31_000_000_001, "duration_ns": 31_000_000_000}
        with self.assertRaisesRegex(guard.GuardError, "deadline"):
            backend._run_effect(cleanup)

    def test_cross_namespace_app_observation_is_rejected(self):
        operation = copy.deepcopy(next(item for item in self.ledger["operations"] if item.get("action") == "assert-zero-cross-namespace-observations"))
        backend = runner.NativeBackend(future_manifest(self.ledger))
        with tempfile.TemporaryDirectory(prefix="taskflow-e06-contamination-test-") as temporary:
            root = Path(temporary)
            paths = {}
            for namespace in (operation["parameters"]["source"], operation["parameters"]["target"]):
                paths[namespace] = []
                for name in ("workspace", "home", "tmp", "DerivedData", "results"):
                    path = root / namespace / name
                    path.mkdir(parents=True)
                    paths[namespace].append(str(path))
            marker = f".taskflow-e06-contamination-marker-{operation['parameters']['source']}"
            for path in paths[operation["parameters"]["source"]]:
                (Path(path) / marker).write_text("source\n", encoding="utf-8")
            lease = f".taskflow-e06-lease-{operation['parameters']['source_lease_id']}"
            (Path(paths[operation["parameters"]["source"]][-1]) / lease).write_text("lease\n", encoding="utf-8")
            source = {"status": "ok", "namespace": operation["parameters"]["source"]}
            target = {"status": "ok", "namespace": operation["parameters"]["target"], "previous_default": "leaked", "previous_file": "", "previous_keychain_name": ""}
            with mock.patch.object(runner, "namespace_paths_for", side_effect=lambda namespace: paths[namespace]), mock.patch.object(backend, "_smoke_result", side_effect=[source, target]):
                with self.assertRaises(guard.GuardError):
                    backend._run_effect(operation)

    def test_manifest_requires_distinct_evidence_and_service_boundaries(self):
        manifest = future_manifest(self.ledger)
        manifest["approval"]["exact_mutation_scope"] = [f"Child writes under {guard.ROOT}"]
        with self.assertRaises(guard.GuardError):
            guard.validate_manifest(manifest, self.ledger, require_current_window=False)

    def test_execute_mode_requires_exact_manifest_and_binding(self):
        with mock.patch.object(sys, "argv", ["runner.py", "--execute"]):
            with self.assertRaises(guard.GuardError):
                runner.main()


if __name__ == "__main__":
    unittest.main()
