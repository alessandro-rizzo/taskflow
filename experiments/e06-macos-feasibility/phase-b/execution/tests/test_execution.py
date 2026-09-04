import copy
import hashlib
import json
import os
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
            "runner_digest": "b" * 64,
            "sandbox_policy_digest": "6a8defba7731fc5a3e560be9cd80e815930b77bab61e07b2b94f2f95ffda07c3",
            "reset_policy_digest": "978219e5255d47a79df6a8161a8df0ec73066fb3b9852923d2ee3e69cc43907c",
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
        self.assertEqual(3733, self.ledger["operation_count"])

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
        operation = next(item for item in changed["operations"] if "/usr/bin/xcrun" in item.get("argv", []))
        operation["argv"] = operation["argv"][:3] + ["/usr/bin/xcrun", "simctl", "list", "devices"]
        with self.assertRaises(guard.GuardError):
            guard.validate_ledger(changed)

    def test_mismatched_device_set_is_rejected(self):
        changed = copy.deepcopy(self.ledger)
        operation = next(item for item in changed["operations"] if "/usr/bin/xcrun" in item.get("argv", []))
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
            binding = {
                "format_version": "taskflow-e06-implementation-binding/v1-experimental",
                "implementation_commit": "1" * 40,
                "implementation_tree": "2" * 40,
                "manifest_sha256": manifest_digest,
                "expanded_ledger_sha256": guard.sha256(EXECUTION / "expanded-ledger.json"),
                "execution_files_sha256": "b" * 64,
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
                manifest["approval"]["approved_by"] = "changed-reviewer"
                manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
                with self.assertRaises(guard.GuardError):
                    guard.validate_execution_binding(manifest_path, binding_path, self.ledger)

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
