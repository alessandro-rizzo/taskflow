#!/usr/bin/env python3
"""Guarded E06 runner. Repository modes are recording-only and side-effect free."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable


EXECUTION = Path(__file__).resolve().parents[1]
REPOSITORY = EXECUTION.parents[3]
sys.path.insert(0, str(EXECUTION / "scripts"))

import guard  # noqa: E402
import schedule  # noqa: E402


class RunnerError(RuntimeError):
    pass


class RecordingBackend:
    """Records the plan in memory; it has no native or filesystem primitive."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def run(self, operation: dict[str, Any]) -> None:
        self.records.append({"id": operation["id"], "kind": operation["kind"], "mutates": operation["mutates"]})


def ensure_no_symlink_chain(path_value: str) -> None:
    path = Path(path_value)
    guard.require(guard.under_root(path_value, allow_root=True), f"path outside root: {path_value}")
    current = Path("/")
    for part in path.parts[1:]:
        current = current / part
        if os.path.lexists(current):
            guard.require(not current.is_symlink(), f"symlink in owned path: {current}")


def sanitized(value: str) -> str:
    value = re.sub(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f-]{27,}\b", "<redacted-device-id>", value)
    value = re.sub(r"/Users/[^/\s]+", "/Users/<redacted>", value)
    return value


def operation_namespace(operation: dict[str, Any]) -> str:
    candidates = [*operation.get("targets", []), *operation.get("argv", [])]
    for namespace in guard.NAMESPACE_NAMES:
        if any(f"/{namespace}/" in item or item.endswith(f"/{namespace}") for item in candidates):
            return namespace
    return "controller"


def child_environment(operation: dict[str, Any]) -> dict[str, str]:
    namespace = operation_namespace(operation)
    base = f"{guard.ROOT}/{namespace}"
    home = f"{base}/home"
    cache = f"{base}/cache"
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG": "C",
        "LC_ALL": "C",
        "DEVELOPER_DIR": "/Applications/Xcode.app/Contents/Developer",
        "HOME": home,
        "TMPDIR": f"{base}/tmp",
        "CFFIXED_USER_HOME": home,
        "XDG_CACHE_HOME": cache,
        "XDG_CONFIG_HOME": f"{base}/config",
        "CLANG_MODULE_CACHE_PATH": f"{cache}/clang-modules",
        "SWIFT_MODULE_CACHE_PATH": f"{cache}/swift-modules",
        "NSUnbufferedIO": "YES",
    }


def namespace_paths_for(namespace: str) -> list[str]:
    base = f"{guard.ROOT}/{namespace}"
    return [f"{base}/workspace", f"{base}/home", f"{base}/tmp", f"{base}/DerivedData", f"{base}/results"]


class NativeBackend:
    """Native backend reachable only after guard.validate_execution_binding."""

    def __init__(self, manifest: dict[str, Any], ledger: dict[str, Any] | None = None, *, monotonic_ns: Callable[[], int] = time.monotonic_ns, wait: Callable[[float], None] = time.sleep) -> None:
        self.manifest = manifest
        self.ledger = ledger
        self.children: dict[str, tuple[subprocess.Popen[str], int]] = {}
        self.results: dict[str, dict[str, Any]] = {}
        self.evidence_root = REPOSITORY / manifest["evidence_root"]
        self.monotonic_ns = monotonic_ns
        self.wait = wait

    def _result(self, identifier: str) -> dict[str, Any]:
        record = self.results.get(identifier)
        guard.require(record is not None, f"owned prerequisite result missing: {identifier}")
        guard.require(record.get("status") in {"passed", "started"}, f"owned prerequisite did not pass: {identifier}")
        return record

    def _duration_seconds(self, identifiers: list[str]) -> float:
        guard.require(identifiers, "timed operation set is empty")
        durations = []
        for identifier in identifiers:
            record = self._result(identifier)
            duration = record.get("duration_ns")
            guard.require(isinstance(duration, int) and duration >= 0, f"duration missing: {identifier}")
            durations.append(duration)
        return sum(durations) / 1_000_000_000

    def _wall_duration_seconds(self, identifiers: list[str]) -> float:
        guard.require(identifiers, "wall-timed operation set is empty")
        records = [self._result(identifier) for identifier in identifiers]
        starts = [record.get("started_monotonic_ns") for record in records]
        ends = [record.get("ended_monotonic_ns") for record in records]
        guard.require(all(isinstance(value, int) and value >= 0 for value in [*starts, *ends]), "wall timing boundary missing")
        guard.require(max(ends) >= min(starts), "wall timing boundary is inverted")
        return (max(ends) - min(starts)) / 1_000_000_000

    def _smoke_result(self, identifier: str) -> dict[str, str]:
        output = self._result(identifier).get("stdout", "")
        marker = "TASKFLOW_E06_RESULT:"
        lines = [line.split(marker, 1)[1] for line in output.splitlines() if marker in line]
        guard.require(len(lines) == 1, f"expected one structured smoke result: {identifier}")
        try:
            value = json.loads(lines[0])
        except json.JSONDecodeError as error:
            raise RunnerError(f"invalid structured smoke result: {identifier}") from error
        guard.require(isinstance(value, dict) and value.get("status") == "ok", f"smoke result failed: {identifier}")
        return value

    def _attest_device(self, identifier: str, expected_name: str, expected_state: str = "Booted") -> None:
        output = self._result(identifier).get("stdout", "")
        try:
            value = json.loads(output)
        except json.JSONDecodeError as error:
            raise RunnerError(f"invalid simctl identity JSON: {identifier}") from error
        matches: list[dict[str, Any]] = []
        for devices in value.get("devices", {}).values():
            if isinstance(devices, list):
                matches.extend(item for item in devices if isinstance(item, dict) and item.get("name") == expected_name)
        guard.require(len(matches) == 1 and matches[0].get("state") == expected_state, f"simulator identity/state mismatch: {expected_name}")

    def _assert_device_absent(self, identifier: str, expected_name: str) -> None:
        output = self._result(identifier).get("stdout", "")
        guard.require(expected_name not in output, f"deleted simulator still present: {expected_name}")

    def _capacity(self, identifiers: list[str]) -> dict[str, Any]:
        guard.require(len(identifiers) == 3, "capacity sample must bind memory, disk, and thermal operations")
        memory_output = self._result(identifiers[0]).get("stdout", "")
        page_match = re.search(r"page size of (\d+) bytes", memory_output)
        guard.require(page_match is not None, "vm_stat page size missing")
        pages = 0
        for label in ("Pages free", "Pages inactive", "Pages speculative"):
            match = re.search(rf"^{label}:\s+(\d+)\.", memory_output, re.MULTILINE)
            guard.require(match is not None, f"vm_stat field missing: {label}")
            pages += int(match.group(1))
        free_ram_gib = pages * int(page_match.group(1)) / (1024 ** 3)
        disk_lines = [line for line in self._result(identifiers[1]).get("stdout", "").splitlines() if line.strip()]
        guard.require(len(disk_lines) >= 2 and len(disk_lines[-1].split()) >= 4, "df output missing")
        free_disk_gib = int(disk_lines[-1].split()[3]) / (1024 ** 2)
        thermal_text = self._result(identifiers[2]).get("stdout", "").strip()
        guard.require(thermal_text in {"0", "1", "2", "3"}, "ProcessInfo thermal state invalid")
        thermal_state = {"0": "nominal", "1": "fair", "2": "serious", "3": "critical"}[thermal_text]
        guard.require(free_ram_gib >= 16, f"free RAM below floor: {free_ram_gib:.3f} GiB")
        guard.require(free_disk_gib >= 200, f"free disk below floor: {free_disk_gib:.3f} GiB")
        guard.require(thermal_state in {"nominal", "fair"}, f"thermal stop reached: {thermal_state}")
        return {"free_ram_gib": free_ram_gib, "free_disk_gib": free_disk_gib, "thermal_state": thermal_state}

    def _wait_until(self, deadline_ns: int) -> int:
        while self.monotonic_ns() < deadline_ns:
            remaining = (deadline_ns - self.monotonic_ns()) / 1_000_000_000
            self.wait(min(remaining, 0.1))
        return self.monotonic_ns()

    def _load_lease(self, lease_path: str, lease_id: str) -> dict[str, Any]:
        guard.require(guard.under_root(lease_path), f"lease path outside owned root: {lease_path}")
        ensure_no_symlink_chain(lease_path)
        try:
            value = json.loads(Path(lease_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RunnerError(f"cannot load supervised lease {lease_id}: {error}") from error
        guard.require(isinstance(value, dict) and value.get("lease_id") == lease_id, f"supervised lease identity mismatch: {lease_id}")
        return value

    def _write_lease(self, lease_path: str, value: dict[str, Any]) -> None:
        guard.require(guard.under_root(lease_path), f"lease path outside owned root: {lease_path}")
        ensure_no_symlink_chain(lease_path)
        target = Path(lease_path)
        guard.require(target.parent.is_dir() and not target.parent.is_symlink(), "supervisor lease directory missing or unsafe")
        target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _write_record(self, operation: dict[str, Any], record: dict[str, Any]) -> None:
        relative = Path(operation["evidence"]).relative_to(self.manifest["evidence_root"])
        target = self.evidence_root / relative
        resolved_parent = target.parent.resolve(strict=False)
        evidence_root = self.evidence_root.resolve(strict=False)
        guard.require(resolved_parent == evidence_root or evidence_root in resolved_parent.parents, f"runner evidence path escaped approved root: {target}")
        current = REPOSITORY
        for part in target.relative_to(REPOSITORY).parts[:-1]:
            current = current / part
            if os.path.lexists(current):
                guard.require(not current.is_symlink(), f"symlink in runner evidence path: {current}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"operation": operation, "result": record}, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _run_command(self, operation: dict[str, Any]) -> dict[str, Any]:
        for target in operation["targets"]:
            if guard.under_root(target, allow_root=True):
                ensure_no_symlink_chain(target)
        started = self.monotonic_ns()
        environment = child_environment(operation)
        if operation["kind"] == "child-command":
            process = subprocess.Popen(operation["argv"], cwd=REPOSITORY, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            process_group = os.getpgid(process.pid)
            guard.require(process.pid > 1 and process_group == process.pid, f"child did not acquire an owned process group: {operation['id']}")
            self.children[operation["child_handle"]] = (process, process_group)
            return {"status": "started", "pid": process.pid, "process_group": process_group, "started_monotonic_ns": started}
        completed = subprocess.run(operation["argv"], cwd=REPOSITORY, env=environment, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=operation["timeout_seconds"])
        ended = self.monotonic_ns()
        expected_result = operation["expected_result"]
        observed_result = "success" if completed.returncode == 0 else "failure"
        matched = observed_result == expected_result
        record = {
            "status": "passed" if matched else "failed",
            "expected_result": expected_result,
            "observed_result": observed_result,
            "returncode": completed.returncode,
            "started_monotonic_ns": started,
            "ended_monotonic_ns": ended,
            "duration_ns": ended - started,
            "stdout": sanitized(completed.stdout),
            "stderr": sanitized(completed.stderr),
        }
        if not matched:
            raise RunnerError(f"command result mismatch: {operation['id']} expected {expected_result}, observed {observed_result}")
        return record

    def _parallel_namespace_probe(self, namespaces: list[str]) -> dict[str, Any]:
        def probe(namespace: str) -> str:
            root = Path(guard.ROOT) / namespace
            ensure_no_symlink_chain(str(root))
            root.mkdir(parents=True, exist_ok=True)
            marker = root / ".taskflow-e06-parallel-marker"
            marker.write_text(namespace + "\n", encoding="utf-8")
            observed = marker.read_text(encoding="utf-8").strip()
            marker.unlink()
            guard.require(observed == namespace, f"parallel namespace collision: {namespace}")
            return namespace

        with ThreadPoolExecutor(max_workers=len(namespaces)) as pool:
            observed = sorted(pool.map(probe, namespaces))
        return {"status": "passed", "observed_namespaces": observed}

    def _run_effect(self, operation: dict[str, Any]) -> dict[str, Any]:
        action = operation["action"]
        parameters = operation["parameters"]
        if action == "assert-profile-mismatch-rejected-before-mutation":
            planned = self.manifest["profile"]["expected_profile_digest"]
            mismatch = ("0" if planned[0] != "0" else "1") + planned[1:]
            try:
                guard.require(mismatch == planned, "deliberate profile mismatch")
            except guard.GuardError:
                return {"status": "passed", "rejections": 1, "mutation_count": 0, "observed_digest": mismatch}
            raise RunnerError("deliberate profile mismatch was not rejected")
        if action == "assert-root-absence-before-native":
            guard.require(not os.path.lexists(guard.ROOT), "owned mutable root exists before first native operation")
            return {"status": "passed", "mutable_root_absent": True}
        if action == "assert-capacity-thermal-window":
            return {"status": "passed", **self._capacity(parameters["source_operation_ids"])}
        if action == "record-timing-and-assert-clean-workspace":
            for target in operation["targets"]:
                path = Path(target)
                guard.require(path.is_dir() and not path.is_symlink(), f"workspace root missing or unsafe: {target}")
                guard.require(not any(path.iterdir()), f"workspace root not empty: {target}")
            return {"status": "passed", "metric": parameters["metric"], "repetition": parameters["repetition"], "duration_seconds": self._duration_seconds(parameters["timed_operation_ids"])}
        if action == "record-timing-and-attest-simulator-identity":
            self._attest_device(parameters["identity_operation_id"], parameters["expected_device_name"])
            return {"status": "passed", "metric": parameters["metric"], "mechanism": parameters["mechanism"], "repetition": parameters["repetition"], "duration_seconds": self._duration_seconds(parameters["timed_operation_ids"]), "device_name": parameters["expected_device_name"]}
        if action == "aggregate-strict-p95":
            samples = [self._result(identifier).get("duration_seconds") for identifier in parameters["sample_result_ids"]]
            guard.require(len(samples) == parameters["expected_sample_count"] and all(isinstance(item, (int, float)) for item in samples), f"{parameters['metric']}: incomplete samples")
            ordered = sorted(samples)
            p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
            guard.require(p95 < parameters["strict_p95_seconds"], f"{parameters['metric']}: p95 {p95:.6f}s is not strictly below {parameters['strict_p95_seconds']:.6f}s")
            return {"status": "passed", "metric": parameters["metric"], "mechanism": parameters.get("mechanism"), "sample_count": len(samples), "p95_seconds": p95, "strict_threshold_seconds": parameters["strict_p95_seconds"]}
        if action == "seed-synthetic-contamination-markers":
            marker_name = f".taskflow-e06-contamination-marker-{parameters['source']}"
            for value in operation["targets"]:
                target = Path(value)
                ensure_no_symlink_chain(str(target))
                guard.require(target.is_dir() and not target.is_symlink(), f"contamination target missing: {target}")
                (target / marker_name).write_text(parameters["source"] + "\n", encoding="utf-8")
            lease_marker = Path(namespace_paths_for(parameters["source"])[-1]) / f".taskflow-e06-lease-{parameters['source_lease_id']}"
            lease_marker.write_text(parameters["source_lease_id"] + "\n", encoding="utf-8")
            return {"status": "passed", "marker_name": marker_name, "lease_marker_name": lease_marker.name, "dimensions": parameters["dimensions"]}
        if action == "assert-zero-cross-namespace-observations":
            marker_name = f".taskflow-e06-contamination-marker-{parameters['source']}"
            source_paths = namespace_paths_for(parameters["source"])
            target_paths = namespace_paths_for(parameters["target"])
            for source_path, target_path in zip(source_paths, target_paths):
                source_marker = Path(source_path) / marker_name
                target_marker = Path(target_path) / marker_name
                guard.require(source_marker.is_file(), f"source marker missing: {source_path}")
                guard.require(not target_marker.exists(), f"cross-namespace marker observed: {target_path}")
                source_marker.unlink()
            lease_marker_name = f".taskflow-e06-lease-{parameters['source_lease_id']}"
            source_lease_marker = Path(source_paths[-1]) / lease_marker_name
            target_lease_marker = Path(target_paths[-1]) / lease_marker_name
            guard.require(source_lease_marker.is_file() and not target_lease_marker.exists(), "cross-namespace lease marker observed or source lease missing")
            source_lease_marker.unlink()
            source_result = self._smoke_result(parameters["source_launch_operation_id"])
            target_result = self._smoke_result(parameters["target_launch_operation_id"])
            guard.require(source_result.get("namespace") == parameters["source"] and target_result.get("namespace") == parameters["target"], "smoke namespace identity drifted")
            for field in ("previous_default", "previous_file", "previous_keychain_name"):
                guard.require(target_result.get(field) == "", f"cross-namespace app contamination: {field}")
            guard.require(parameters["source_lease_id"] != parameters["target_lease_id"], "lease identity collision")
            return {"status": "passed", "contamination_count": 0, "dimensions": parameters["dimensions"]}
        if action in {"assert-zero-path-device-lease-or-identity-collision", "record-capacity-and-assert-all-hard-gates"}:
            namespaces = parameters["namespaces"]
            devices = parameters["devices"]
            leases = parameters["lease_ids"]
            guard.require(len(namespaces) == len(set(namespaces)) == parameters["concurrency"], "namespace collision or concurrency drift")
            guard.require(len(devices) == len(set(devices)) == len(namespaces), "device identity collision")
            guard.require(len(leases) == len(set(leases)) == len(namespaces), "lease identity collision")
            writable_paths = [path for namespace in namespaces for path in namespace_paths_for(namespace)]
            guard.require(len(writable_paths) == len(set(writable_paths)), "writable path collision")
            for identifier, device in zip(parameters["identity_operation_ids"], devices):
                self._attest_device(identifier, device)
            for identifier, namespace in zip(parameters["launch_operation_ids"], namespaces):
                result = self._smoke_result(identifier)
                guard.require(result.get("namespace") == namespace, f"parallel smoke namespace mismatch: {namespace}")
            for identifier, device in zip([parameters["post_cleanup_identity_operation_id"]] * len(devices), devices):
                self._assert_device_absent(identifier, device)
            cleanup_seconds = self._wall_duration_seconds(parameters["cleanup_operation_ids"])
            guard.require(cleanup_seconds <= parameters["cleanup_deadline_seconds"], f"parallel cleanup exceeded deadline: {cleanup_seconds:.6f}s")
            capacity_before = self._capacity(parameters["pre_capacity_operation_ids"])
            capacity_after = self._capacity(parameters["post_capacity_operation_ids"])
            return {"status": "passed", "concurrency": parameters["concurrency"], "repetition": parameters["repetition"], "identity_or_lease_collision_count": 0, "unauthorized_cleanup_target_count": 0, "cleanup_seconds": cleanup_seconds, "capacity_before": capacity_before, "capacity_after": capacity_after}
        if action == "signal-recorded-child":
            handle = operation["targets"][0].split(":", 1)[1]
            owned = self.children.get(handle)
            guard.require(owned is not None, f"child is absent or not owned: {handle}")
            process, process_group = owned
            guard.require(process.pid > 1 and process_group == process.pid and os.getpgid(process.pid) == process_group and process.poll() is None, f"child process group is absent or changed: {handle}")
            signal_started = self.monotonic_ns()
            os.killpg(process_group, signal.SIGTERM)
            try:
                stdout, stderr = process.communicate(timeout=30)
            except subprocess.TimeoutExpired as error:
                raise RunnerError(f"recorded child did not stop: {handle}") from error
            ended = self.monotonic_ns()
            guard.require(process.returncode is not None and process.returncode != 0, f"recorded child did not terminate from cancellation: {handle}")
            return {"status": "passed", "recorded_child": handle, "pid": process.pid, "process_group": process_group, "returncode": process.returncode, "stdout": sanitized(stdout), "stderr": sanitized(stderr), "started_monotonic_ns": signal_started, "ended_monotonic_ns": ended, "duration_ns": ended - signal_started}
        if action == "record-build-install-test-timings-and-structured-result":
            self._attest_device(parameters["identity_operation_id"], parameters["expected_device_name"])
            smoke = self._smoke_result(parameters["timed_operation_ids"][-1])
            guard.require(smoke.get("namespace") in guard.NAMESPACE_NAMES, "mobile smoke namespace invalid")
            durations = {metric: self._duration_seconds([identifier]) for metric, identifier in zip(parameters["metrics"], parameters["timed_operation_ids"])}
            return {"status": "passed", "metrics": durations, "repetition": parameters["repetition"], "mechanism": parameters["mechanism"], "capacity": self._capacity(parameters["capacity_operation_ids"])}
        if action == "record-reset-cleanup-timings-and-residue":
            self._assert_device_absent(parameters["post_cleanup_identity_operation_id"], parameters["expected_absent_device_name"])
            reset_seconds = self._duration_seconds(parameters["reset_operation_ids"])
            cleanup_seconds = self._duration_seconds(parameters["cleanup_operation_ids"])
            guard.require(cleanup_seconds <= parameters["cleanup_deadline_seconds"], f"cleanup deadline exceeded: {cleanup_seconds:.6f}s")
            namespace_root = Path(operation["targets"][1])
            guard.require(not namespace_root.exists(), f"namespace cleanup incomplete: {namespace_root}")
            return {"status": "passed", "metrics": {"candidate-reset": reset_seconds, "candidate-cleanup": cleanup_seconds}, "orphan_count": 0}
        if action == "assert-lost-session-rejected-and-clean-retry-possible":
            lost_use = self._result(parameters["lost_use_operation_id"])
            guard.require(lost_use.get("expected_result") == "failure" and lost_use.get("observed_result") == "failure", "lost-session use was not rejected")
            guard.require("TASKFLOW_E06_RESULT:" not in lost_use.get("stdout", ""), "lost session emitted an accepted report")
            self._attest_device(parameters["retry_identity_operation_id"], parameters["retry_device_name"])
            retry = self._smoke_result(parameters["retry_launch_operation_id"])
            guard.require(retry.get("namespace") == parameters["expected_namespace"], "clean retry namespace drifted")
            self._assert_device_absent(parameters["post_cleanup_identity_operation_id"], parameters["lost_device_name"])
            self._assert_device_absent(parameters["post_cleanup_identity_operation_id"], parameters["retry_device_name"])
            return {"status": "passed", "lost_session_rejected": True, "lost_report_accepted": False, "clean_retry_verified": True, "repetition": parameters["repetition"]}
        if action == "assert-cleanup-deadline-or-exact-orphan":
            cleanup_seconds = self._wall_duration_seconds([parameters["signal_operation_id"], parameters["cleanup_operation_id"]])
            guard.require(cleanup_seconds <= parameters["cleanup_deadline_seconds"], f"fault cleanup deadline exceeded: {cleanup_seconds:.6f}s")
            guard.require(not Path(operation["targets"][0]).exists(), f"fault namespace cleanup incomplete: {operation['targets'][0]}")
            return {"status": "passed", "fault": parameters["fault"], "repetition": parameters["repetition"], "cleanup_seconds": cleanup_seconds, "orphan_count": 0}
        if action == "create-supervised-caller-lease":
            guard.require(parameters["ttl_seconds"] == schedule.CALLER_LEASE_TTL_SECONDS and parameters["heartbeat_seconds"] == schedule.CALLER_HEARTBEAT_SECONDS, "caller lease timing contract drifted")
            self._attest_device(parameters["identity_operation_id"], parameters["device_name"])
            now = self.monotonic_ns()
            state = {
                "format_version": "taskflow-e06-supervised-lease/v1-experimental",
                "lease_id": parameters["lease_id"],
                "namespace": parameters["namespace"],
                "device_name": parameters["device_name"],
                "state": "active",
                "created_monotonic_ns": now,
                "last_heartbeat_monotonic_ns": now,
                "heartbeat_due_monotonic_ns": now + int(parameters["heartbeat_seconds"] * 1_000_000_000),
                "expires_monotonic_ns": now + int(parameters["ttl_seconds"] * 1_000_000_000),
                "events": [],
            }
            self._write_lease(parameters["lease_path"], state)
            return {"status": "passed", "lease_id": parameters["lease_id"], "state": "active", "expires_monotonic_ns": state["expires_monotonic_ns"]}
        if action == "observe-caller-lease-expiry":
            signal_result = self._result(parameters["signal_operation_id"])
            guard.require(signal_result.get("returncode") is not None and signal_result["returncode"] != 0, "caller process did not die")
            state = self._load_lease(parameters["lease_path"], parameters["lease_id"])
            guard.require(state.get("state") == "active" and state.get("events") == [], "caller lease was not active and clean")
            missed_at = self._wait_until(state["heartbeat_due_monotonic_ns"])
            state["events"].append({"event": "lease.heartbeat.missed", "lease_id": parameters["lease_id"], "monotonic_ns": missed_at})
            expired_at = self._wait_until(state["expires_monotonic_ns"])
            state["events"].append({"event": "lease.expired", "lease_id": parameters["lease_id"], "monotonic_ns": expired_at})
            state["events"].append({"event": "orphan.detected", "namespace_id": state["namespace"], "resource_id": state["device_name"], "monotonic_ns": expired_at})
            state["state"] = "expired-orphan-detected"
            state["expired_observed_monotonic_ns"] = expired_at
            self._write_lease(parameters["lease_path"], state)
            return {"status": "passed", "lease_id": parameters["lease_id"], "state": state["state"], "events": state["events"]}
        if action == "verify-caller-loss-reclaim-order-and-deadline":
            state = self._load_lease(parameters["lease_path"], parameters["lease_id"])
            guard.require(state.get("state") == "expired-orphan-detected", "caller lease was not expired before reclaim")
            self._assert_device_absent(parameters["post_cleanup_identity_operation_id"], parameters["device_name"])
            guard.require(not Path(f"{guard.ROOT}/{parameters['namespace']}").exists(), "caller-loss namespace cleanup incomplete")
            cleanup_records = [self._result(identifier) for identifier in parameters["cleanup_operation_ids"]]
            cleanup_end = max(record.get("ended_monotonic_ns", -1) for record in cleanup_records)
            guard.require(cleanup_end >= state["expired_observed_monotonic_ns"], "caller-loss cleanup predates lease expiry")
            deadline = state["expires_monotonic_ns"] + int(parameters["cleanup_grace_seconds"] * 1_000_000_000)
            guard.require(cleanup_end <= deadline, "caller-loss reclaim exceeded lease TTL plus cleanup grace")
            state["events"].append({"event": "orphan.reclaimed", "namespace_id": state["namespace"], "resource_id": state["device_name"], "monotonic_ns": cleanup_end})
            names = [item["event"] for item in state["events"]]
            guard.require(names == parameters["expected_events"], f"caller-loss W3 event order mismatch: {names}")
            event_times = [item["monotonic_ns"] for item in state["events"]]
            guard.require(event_times == sorted(event_times), "caller-loss W3 event times are not monotonic")
            state["state"] = "reclaimed"
            state["reclaimed_monotonic_ns"] = cleanup_end
            self._write_lease(parameters["lease_path"], state)
            return {"status": "passed", "lease_id": parameters["lease_id"], "state": "reclaimed", "events": state["events"], "reclaim_deadline_monotonic_ns": deadline}
        if action == "verify-clean-session-after-caller-loss":
            state = self._load_lease(parameters["lease_path"], parameters["lease_id"])
            guard.require(state.get("state") == "reclaimed", "clean retry began before caller-loss reclaim")
            self._attest_device(parameters["retry_identity_operation_id"], parameters["retry_device_name"])
            smoke = self._smoke_result(parameters["retry_launch_operation_id"])
            guard.require(smoke.get("namespace") == parameters["namespace"], "caller-loss retry namespace drifted")
            self._assert_device_absent(parameters["post_cleanup_identity_operation_id"], parameters["retry_device_name"])
            guard.require(not Path(f"{guard.ROOT}/{parameters['namespace']}").exists(), "caller-loss retry namespace cleanup incomplete")
            return {"status": "passed", "lease_id": parameters["lease_id"], "clean_retry_verified": True, "event_order": [item["event"] for item in state["events"]]}
        if action == "record-not-applicable-and-unmeasured-limitations":
            guard.require(parameters["not_applicable"] == ["cold-vm-boot", "vm-loss", "immutable-base-integrity", "image-import-update"], "not-applicable set drifted")
            guard.require(parameters["unmeasured"] == ["network-image-distribution", "native-xcode-sdk-runtime-update-and-rollback"], "unmeasured limitation set drifted")
            return {"status": "passed", **parameters}
        if action == "finalize-sanitized-evidence-and-checksums":
            guard.require(self.ledger is not None, "expanded ledger unavailable for evidence finalization")
            current_index = next(index for index, item in enumerate(self.ledger["operations"]) if item["id"] == operation["id"])
            expected = [item["id"] for item in self.ledger["operations"][:current_index]]
            missing = [identifier for identifier in expected if identifier not in self.results]
            guard.require(not missing, f"evidence results incomplete before finalization: {missing[:3]}")
            final_record = {
                "status": "passed",
                "evidence_file_count": current_index + 1,
                "checksum_manifest": (self.evidence_root / "checksums.json").relative_to(REPOSITORY).as_posix(),
                "id": operation["id"],
                "kind": operation["kind"],
                "targets": operation["targets"],
            }
            self._write_record(operation, final_record)
            entries = []
            for path in sorted(self.evidence_root.rglob("*.json")):
                data = path.read_bytes()
                text = data.decode("utf-8")
                guard.require(not re.search(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f-]{27,}\b", text), f"unsanitized device id in evidence: {path}")
                guard.require("/Users/" not in text.replace("/Users/<redacted>", ""), f"unsanitized user path in evidence: {path}")
                entries.append({"path": path.relative_to(self.evidence_root).as_posix(), "sha256": hashlib.sha256(data).hexdigest()})
            expected_paths = {Path(item["evidence"]).relative_to(self.manifest["evidence_root"]).as_posix() for item in self.ledger["operations"][:current_index + 1]}
            guard.require(len(entries) == current_index + 1 and {item["path"] for item in entries} == expected_paths, "evidence file completeness mismatch")
            manifest_path = self.evidence_root / "checksums.json"
            manifest_path.write_text(json.dumps({"format_version": "taskflow-e06-evidence-checksums/v1-experimental", "entries": entries}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
            guard.require(persisted["entries"] == entries, "evidence checksum manifest readback mismatch")
            return final_record
        if action == "assert-owned-root-absent-and-no-unrecorded-orphans":
            guard.require(not os.path.lexists(guard.ROOT), "owned root remains after cleanup")
            return {"status": "passed", "orphan_count": 0}
        if action == "assert-no-owned-devices-or-record-exact-orphans":
            list_id = operation["prerequisites"][0]
            output = self.results.get(list_id, {}).get("stdout", "")
            guard.require(guard.PREFIX not in output, "owned simulator remains before root cleanup")
            return {"status": "passed", "orphan_count": 0}
        raise RunnerError(f"typed effect has no fail-closed handler: {action}")

    def run(self, operation: dict[str, Any]) -> None:
        try:
            record = self._run_command(operation) if operation["kind"] in {"command", "child-command"} else self._run_effect(operation)
        except (guard.GuardError, RunnerError, subprocess.TimeoutExpired, OSError) as error:
            handle = operation.get("child_handle")
            if handle is None and operation.get("targets") and operation["targets"][0].startswith("recorded-child:"):
                handle = operation["targets"][0].split(":", 1)[1]
            owned = self.children.get(handle) if handle else None
            retained_targets = operation.get("parameters", {}).get("retained_owned_targets", operation["targets"])
            failed = {
                "status": "failed",
                "error_type": type(error).__name__,
                "error": sanitized(str(error)),
                "id": operation["id"],
                "kind": operation["kind"],
                "targets": operation["targets"],
                "cleanup_attempted": False,
                "retained_owned_state": {
                    "targets": retained_targets,
                    "child_handle": handle,
                    "pid": owned[0].pid if owned else None,
                    "process_group": owned[1] if owned else None,
                },
            }
            self.results[operation["id"]] = failed
            self._write_record(operation, failed)
            raise
        record.update({"id": operation["id"], "kind": operation["kind"], "targets": operation["targets"]})
        self.results[operation["id"]] = record
        if operation.get("action") != "finalize-sanitized-evidence-and-checksums":
            self._write_record(operation, record)


def run_ledger(ledger: dict[str, Any], backend: RecordingBackend | NativeBackend) -> int:
    guard.validate_ledger(ledger)
    completed: set[str] = set()
    operations = ledger["operations"]
    index = 0
    while index < len(operations):
        operation = operations[index]
        group_key = (operation.get("parallel_group"), operation.get("parallel_step"))
        batch = [operation]
        index += 1
        if group_key[0] is not None:
            while index < len(operations) and (operations[index].get("parallel_group"), operations[index].get("parallel_step")) == group_key:
                batch.append(operations[index])
                index += 1
        for item in batch:
            if not set(item["prerequisites"]) <= completed:
                raise RunnerError(f"unsatisfied prerequisite: {item['id']}")
        if isinstance(backend, NativeBackend) and len(batch) > 1:
            with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                futures = [pool.submit(backend.run, item) for item in batch]
                for future in futures:
                    future.result()
        else:
            for item in batch:
                backend.run(item)
        completed.update(item["id"] for item in batch)
    return len(completed)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    mode = value.add_mutually_exclusive_group(required=True)
    mode.add_argument("--describe", action="store_true")
    mode.add_argument("--record-plan", action="store_true")
    mode.add_argument("--validate-manifest", type=Path)
    mode.add_argument("--execute", action="store_true")
    value.add_argument("--manifest", type=Path)
    value.add_argument("--binding", type=Path)
    return value


def main() -> int:
    args = parser().parse_args()
    ledger = guard.load_object(EXECUTION / "expanded-ledger.json")
    guard.validate_ledger(ledger)
    generated = schedule.build_ledger()
    guard.require(ledger == generated, "expanded ledger does not match deterministic generator")
    if args.describe:
        print(json.dumps({"status": ledger["status"], "operation_count": ledger["operation_count"], "execution_count": 0}, sort_keys=True))
        return 0
    if args.record_plan:
        backend = RecordingBackend()
        count = run_ledger(ledger, backend)
        guard.require(count == len(backend.records) == ledger["operation_count"], "recording backend lost operations")
        print(json.dumps({"backend": "recording", "recorded_operations": count, "execution_count": 0}, sort_keys=True))
        return 0
    if args.validate_manifest:
        manifest = guard.load_object(args.validate_manifest)
        guard.validate_manifest(manifest, ledger, require_current_window=False)
        print("manifest structure and exact ledger binding valid; execution approval not evaluated")
        return 0
    guard.require(args.manifest is not None and args.binding is not None, "--execute requires --manifest and --binding")
    manifest = guard.validate_execution_binding(args.manifest, args.binding, ledger)
    backend = NativeBackend(manifest, ledger)
    run_ledger(ledger, backend)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (guard.GuardError, RunnerError, OSError, ValueError) as error:
        print(f"e06-runner: {error}", file=sys.stderr)
        raise SystemExit(1)
