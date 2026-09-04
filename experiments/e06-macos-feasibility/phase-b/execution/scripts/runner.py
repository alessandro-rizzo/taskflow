#!/usr/bin/env python3
"""Guarded E06 runner. Repository modes are recording-only and side-effect free."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import plistlib
import re
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
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

    def __init__(self, manifest: dict[str, Any], ledger: dict[str, Any] | None = None, *, source_revision: str = "repository-test-revision", monotonic_ns: Callable[[], int] = time.monotonic_ns, wait: Callable[[float], None] = time.sleep) -> None:
        self.manifest = manifest
        self.ledger = ledger
        self.children: dict[str, tuple[subprocess.Popen[str], int]] = {}
        self.results: dict[str, dict[str, Any]] = {}
        self.evidence_root = REPOSITORY / manifest["evidence_root"]
        self.monotonic_ns = monotonic_ns
        self.wait = wait
        self.source_revision = source_revision

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

    def _compare_profile(self, profile: dict[str, Any], expected_digest: str) -> str:
        observed = guard.canonical_sha256(profile)
        guard.require(observed == expected_digest, f"live profile digest mismatch: expected {expected_digest}, observed {observed}")
        return observed

    def _live_profile(self, identifiers: list[str]) -> dict[str, Any]:
        guard.require(len(identifiers) == 9, "profile attestation requires nine owned command results")
        outputs = [self._result(identifier).get("stdout", "").strip() for identifier in identifiers]
        guard.require(all(outputs), "profile attestation command output missing")
        xcode = outputs[3].splitlines()
        guard.require(len(xcode) == 2 and xcode[0].startswith("Xcode ") and xcode[1].startswith("Build version "), "Xcode identity output invalid")
        try:
            runtime_json = json.loads(outputs[8])
        except json.JSONDecodeError as error:
            raise RunnerError("runtime profile JSON invalid") from error
        matches = [item for item in runtime_json.get("runtimes", []) if isinstance(item, dict) and item.get("identifier") == "com.apple.CoreSimulator.SimRuntime.iOS-26-5"]
        guard.require(len(matches) == 1, "approved simulator runtime missing or duplicated")
        runtime = matches[0]
        architectures = runtime.get("supportedArchitectures")
        guard.require(isinstance(architectures, list) and architectures and all(isinstance(item, str) for item in architectures), "runtime architectures missing")
        components = guard.implementation_component_hashes()
        profile = {
            "mechanism_id": "trusted-native-host",
            "mechanism_version": f"native-macos-{outputs[1]}-xcode-{xcode[1].removeprefix('Build version ')}",
            "base_image_digest": None,
            "macos_version": outputs[0],
            "macos_build": outputs[1],
            "architecture": outputs[2],
            "xcode_version": xcode[0].removeprefix("Xcode "),
            "xcode_build": xcode[1].removeprefix("Build version "),
            "sdk_identifiers_and_builds": [f"iphoneos{outputs[4]}@{outputs[5]}", f"iphonesimulator{outputs[6]}@{outputs[7]}"],
            "simulator_runtime_identifier_build_and_architectures": f"{runtime['identifier']}@{runtime.get('buildversion')}@{','.join(sorted(architectures))}",
            "runner_digest": components["execution_files_sha256"],
            "sandbox_policy_digest": components["sandbox_policy_sha256"],
            "reset_policy_digest": components["reset_policy_sha256"],
        }
        guard.require(profile["mechanism_version"] == "native-macos-25F84-xcode-17F113", "live mechanism version drifted")
        return profile

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
        started_at_utc = datetime.now(timezone.utc).isoformat()
        environment = child_environment(operation)
        if operation["kind"] == "child-command":
            process = subprocess.Popen(operation["argv"], cwd=REPOSITORY, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            process_group = os.getpgid(process.pid)
            guard.require(process.pid > 1 and process_group == process.pid, f"child did not acquire an owned process group: {operation['id']}")
            self.children[operation["child_handle"]] = (process, process_group)
            return {"status": "started", "pid": process.pid, "process_group": process_group, "started_monotonic_ns": started, "started_at_utc": started_at_utc}
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
            "started_at_utc": started_at_utc,
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
            try:
                self._compare_profile({"deliberate": "profile-mismatch"}, planned)
            except guard.GuardError:
                return {"status": "passed", "rejections": 1, "mutation_count": 0, "comparison_path": "canonical-live-profile-digest"}
            raise RunnerError("deliberate profile mismatch was not rejected")
        if action == "attest-live-profile":
            profile = self._live_profile(parameters["source_operation_ids"])
            observed = self._compare_profile(profile, self.manifest["profile"]["expected_profile_digest"])
            return {"status": "passed", "profile": profile, "observed_profile_digest": observed, "repetition": parameters["repetition"]}
        if action == "assert-root-absence-before-native":
            guard.require(not os.path.lexists(guard.ROOT), "owned mutable root exists before first native operation")
            return {"status": "passed", "mutable_root_absent": True}
        if action == "assert-capacity-thermal-window":
            return {"status": "passed", **self._capacity(parameters["source_operation_ids"])}
        if action == "record-timing-and-assert-clean-workspace":
            guard.require(parameters["reset_policy_sha256"] == guard.implementation_component_hashes()["reset_policy_sha256"], "warm workspace reset policy digest drifted")
            for target in operation["targets"]:
                path = Path(target)
                guard.require(path.is_dir() and not path.is_symlink(), f"workspace root missing or unsafe: {target}")
                guard.require(not any(path.iterdir()), f"workspace root not empty: {target}")
            return {"status": "passed", "metric": parameters["metric"], "repetition": parameters["repetition"], "duration_seconds": self._duration_seconds(parameters["timed_operation_ids"]), "sample_started_at_utc": self._result(parameters["timed_operation_ids"][0]).get("started_at_utc"), "preparation_operation_ids": parameters["preparation_operation_ids"]}
        if action == "record-timing-and-attest-simulator-identity":
            self._attest_device(parameters["identity_operation_id"], parameters["expected_device_name"])
            service = self._result(parameters["installation_service_operation_id"])
            guard.require(service.get("observed_result") == "success", "installation service is not reachable")
            guard.require(parameters["timed_operation_ids"][-2:] == [parameters["identity_operation_id"], parameters["installation_service_operation_id"]], "simulator-ready boundary omits identity or installation service")
            return {"status": "passed", "metric": parameters["metric"], "mechanism": parameters["mechanism"], "repetition": parameters["repetition"], "duration_seconds": self._wall_duration_seconds(parameters["timed_operation_ids"]), "sample_started_at_utc": self._result(parameters["timed_operation_ids"][0]).get("started_at_utc"), "preparation_operation_ids": parameters["preparation_operation_ids"], "device_name": parameters["expected_device_name"], "installation_service_reachable": True}
        if action == "seed-reset-contamination-markers":
            guard.require(parameters["reset_policy_sha256"] == guard.implementation_component_hashes()["reset_policy_sha256"], "reset contamination policy digest drifted")
            created = []
            for target_value in operation["targets"]:
                target = Path(target_value)
                ensure_no_symlink_chain(str(target))
                guard.require(target.is_dir() and not target.is_symlink(), f"reset contamination target missing: {target}")
                marker = target / ".taskflow-e06-reset-canary"
                marker.write_text(parameters["namespace"] + "\n", encoding="utf-8")
                created.append(str(marker))
            return {"status": "passed", "marker_paths": created, "reset_policy_sha256": parameters["reset_policy_sha256"]}
        if action == "probe-reset-residue":
            guard.require(parameters["reset_policy_sha256"] == guard.implementation_component_hashes()["reset_policy_sha256"], "reset residue policy digest drifted")
            empty_paths = parameters["expected_empty_paths"]
            canaries = parameters["reset_canary_paths"]
            guard.require(empty_paths and all(guard.under_root(path) for path in [*empty_paths, *canaries]), "reset residue paths invalid")
            for path_value in empty_paths:
                path = Path(path_value)
                guard.require(path.is_dir() and not path.is_symlink() and not any(path.iterdir()), f"reset residue remains: {path_value}")
            guard.require(not any(os.path.lexists(path) for path in canaries), "reset canary remains after namespace recreation")
            return {"status": "passed", "namespace": parameters["namespace"], "empty_path_count": len(empty_paths), "canary_count": 0}
        if action == "verify-build-output-manifest":
            app = Path(parameters["app_path"])
            manifest = Path(parameters["output_manifest_path"])
            ensure_no_symlink_chain(str(app))
            ensure_no_symlink_chain(str(manifest))
            guard.require(app.is_dir() and not app.is_symlink(), "declared app build output missing or unsafe")
            info = app / "Info.plist"
            guard.require(info.is_file() and not info.is_symlink(), "built app Info.plist missing")
            with info.open("rb") as stream:
                plist = plistlib.load(stream)
            guard.require(plist.get("CFBundleIdentifier") == parameters["bundle_identifier"], "built app bundle identifier drifted")
            files = [{"path": path.relative_to(app).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(app.rglob("*")) if path.is_file() and not path.is_symlink()]
            guard.require(files, "built app output manifest is empty")
            payload = {"format_version": "taskflow-e06-build-output/v1-experimental", "bundle_identifier": parameters["bundle_identifier"], "files": files}
            manifest.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            guard.require(json.loads(manifest.read_text(encoding="utf-8")) == payload, "build output manifest readback mismatch")
            return {"status": "passed", "app_path": str(app), "output_manifest_path": str(manifest), "file_count": len(files), "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()}
        if action == "verify-installed-bundle-identity":
            output = self._result(parameters["container_operation_id"]).get("stdout", "").strip()
            guard.require(output and guard.under_root(output), "installed bundle container is absent or outside custom device set")
            guard.require(output.startswith(guard.DEVICE_SET + "/"), "installed bundle did not resolve inside the approved custom set")
            return {"status": "passed", "device_name": parameters["device_name"], "bundle_identifier": parameters["bundle_identifier"], "container_path": output}
        if action == "attest-reset-reusable-state":
            components = guard.implementation_component_hashes()
            guard.require(parameters["reset_policy_sha256"] == components["reset_policy_sha256"], "reset policy digest drifted")
            if parameters["expected_device_state"] == "absent":
                self._assert_device_absent(parameters["identity_operation_id"], parameters["device_name"])
            else:
                guard.require(parameters["expected_device_state"] == "Shutdown", "reset device-state contract invalid")
                self._attest_device(parameters["identity_operation_id"], parameters["device_name"], expected_state="Shutdown")
            guard.require(parameters["reset_operation_ids"], "reset operation set missing")
            namespace_root = parameters.get("namespace_root")
            empty_paths = parameters.get("expected_empty_paths")
            canaries = parameters.get("reset_canary_paths")
            guard.require(namespace_root is None or (isinstance(namespace_root, str) and guard.under_root(namespace_root)), "reset namespace root invalid")
            guard.require(isinstance(empty_paths, list) and isinstance(canaries, list) and all(isinstance(path, str) and guard.under_root(path) for path in [*empty_paths, *canaries]), "reset residue paths invalid")
            if namespace_root is not None:
                guard.require(Path(namespace_root).is_dir() and not Path(namespace_root).is_symlink(), f"reset namespace was not recreated: {namespace_root}")
                for path_value in empty_paths:
                    path = Path(path_value)
                    guard.require(path.is_dir() and not path.is_symlink() and not any(path.iterdir()), f"reset residue remains at attestation: {path_value}")
            guard.require(not any(os.path.lexists(path) for path in canaries), "reset canary contamination remains")
            return {"status": "passed", "device_name": parameters["device_name"], "reusable_state": parameters["expected_device_state"], "reset_policy_sha256": parameters["reset_policy_sha256"], "reset_seconds": self._wall_duration_seconds(parameters["reset_operation_ids"])}
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
            boundaries = parameters.get("timed_operation_boundaries")
            guard.require(isinstance(boundaries, list) and len(boundaries) == len(parameters["metrics"]), "mobile timing boundaries missing")
            durations = {metric: self._wall_duration_seconds(identifiers) for metric, identifiers in zip(parameters["metrics"], boundaries)}
            preparation_by_metric = parameters.get("preparation_operation_ids_by_metric")
            guard.require(isinstance(preparation_by_metric, dict) and set(preparation_by_metric) == set(parameters["metrics"]), "mobile preparation boundaries missing")
            expected_preparation = list(preparation_by_metric[parameters["metrics"][0]])
            for metric, boundary in zip(parameters["metrics"], boundaries):
                preparation = preparation_by_metric[metric]
                guard.require(isinstance(preparation, list) and preparation == expected_preparation, f"{metric}: preparation chain does not end immediately before sample boundary")
                guard.require(set(preparation).isdisjoint(boundary), f"{metric}: measured boundary is incorrectly included in preparation")
                guard.require(all(identifier in self.results for identifier in preparation), f"{metric}: preparation result missing")
                expected_preparation.extend(boundary)
            return {
                "status": "passed",
                "metrics": durations,
                "repetition": parameters["repetition"],
                "mechanism": parameters["mechanism"],
                "sample_started_at_utc_by_metric": {
                    metric: self._result(boundary[0]).get("started_at_utc")
                    for metric, boundary in zip(parameters["metrics"], boundaries)
                },
                "preparation_operation_ids_by_metric": preparation_by_metric,
                "capacity": self._capacity(parameters["capacity_operation_ids"]),
            }
        if action == "record-reset-cleanup-timings-and-residue":
            self._assert_device_absent(parameters["post_cleanup_identity_operation_id"], parameters["expected_absent_device_name"])
            reset_seconds = self._wall_duration_seconds(parameters["reset_operation_ids"])
            cleanup_seconds = self._wall_duration_seconds(parameters["cleanup_operation_ids"])
            guard.require(cleanup_seconds <= parameters["cleanup_deadline_seconds"], f"cleanup deadline exceeded: {cleanup_seconds:.6f}s")
            namespace_root = Path(operation["targets"][1])
            guard.require(not namespace_root.exists(), f"namespace cleanup incomplete: {namespace_root}")
            return {"status": "passed", "metrics": {"candidate-reset": reset_seconds}, "reset_teardown_seconds": cleanup_seconds, "mechanism": parameters["mechanism"], "repetition": parameters["repetition"], "sample_started_at_utc": self._result(parameters["reset_operation_ids"][0]).get("started_at_utc"), "preparation_operation_ids": parameters.get("preparation_operation_ids", []), "orphan_count": 0}
        if action == "record-cleanup-timing-and-residue":
            self._assert_device_absent(parameters["post_cleanup_identity_operation_id"], parameters["expected_absent_device_name"])
            cleanup_seconds = self._wall_duration_seconds(parameters["cleanup_operation_ids"])
            guard.require(cleanup_seconds <= parameters["cleanup_deadline_seconds"], f"cleanup deadline exceeded: {cleanup_seconds:.6f}s")
            guard.require(not os.path.lexists(parameters["namespace_root"]), f"cleanup namespace remains: {parameters['namespace_root']}")
            return {"status": "passed", "metrics": {"candidate-cleanup": cleanup_seconds}, "mechanism": parameters["mechanism"], "repetition": parameters["repetition"], "sample_started_at_utc": self._result(parameters["cleanup_operation_ids"][0]).get("started_at_utc"), "preparation_operation_ids": parameters["preparation_operation_ids"], "orphan_count": 0}
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
        if action == "emit-benchmark-v2-and-decision":
            guard.require(parameters["adr_edit_forbidden"] is True, "evidence generation may not edit the ADR")
            final_cleanup = [self._result(identifier) for identifier in parameters["final_cleanup_operation_ids"]]
            guard.require(all(result.get("status") == "passed" for result in final_cleanup), "final cleanup did not pass")
            cpu, cores, ram = [self._result(identifier).get("stdout", "").strip() for identifier in parameters["hardware_operation_ids"]]
            guard.require(cpu and cores.isdigit() and ram.isdigit() and int(cores) > 0 and int(ram) > 0, "benchmark hardware attestation incomplete")
            profile_result = self._result(parameters["profile_operation_id"])
            profile = profile_result.get("profile")
            guard.require(isinstance(profile, dict), "benchmark profile attestation missing")

            def statistics(samples: list[float]) -> tuple[float, float]:
                guard.require(samples and all(isinstance(value, (int, float)) and value >= 0 for value in samples), "benchmark samples missing or invalid")
                ordered = sorted(float(value) for value in samples)
                middle = len(ordered) // 2
                median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
                p95 = ordered[int(math.floor(0.95 * (len(ordered) - 1) + 0.5))]
                return median, p95

            sample_sets: list[tuple[str, str | None, list[dict[str, Any]]]] = []
            warm = [result for result in self.results.values() if result.get("metric") == "warm-workspace-ready" and "duration_seconds" in result]
            sample_sets.append(("warm-workspace-ready", None, warm))
            for mechanism in schedule.MECHANISMS:
                ready = [result for result in self.results.values() if result.get("metric") == "simulator-ready-to-install" and result.get("mechanism") == mechanism and "duration_seconds" in result]
                sample_sets.append(("simulator-ready-to-install", mechanism, ready))
                lifecycle = [result for result in self.results.values() if result.get("mechanism") == mechanism and isinstance(result.get("metrics"), dict)]
                for metric in ("xcode-build", "simulator-install", "mobile-test", "candidate-reset", "candidate-cleanup"):
                    sample_sets.append((metric, mechanism, [result for result in lifecycle if metric in result["metrics"]]))
            output_paths = parameters["output_paths"]
            record_paths = output_paths[:-2]
            guard.require(len(sample_sets) == len(record_paths) and parameters["series"] == [[metric, mechanism] for metric, mechanism, _ in sample_sets], "benchmark output ledger series is incomplete or misordered")
            generated: list[str] = []
            records = []
            for path_value, (metric, mechanism, sample_results) in zip(record_paths, sample_sets):
                expected_count = 30 if metric in {"warm-workspace-ready", "simulator-ready-to-install"} else 15
                repetitions = [result.get("repetition") for result in sample_results]
                guard.require(len(sample_results) == expected_count and sorted(repetitions) == list(range(1, expected_count + 1)), f"{metric}/{mechanism or 'native-host'}: sample count or repetitions incomplete/duplicated")
                samples = [result["duration_seconds"] if "duration_seconds" in result else result["metrics"][metric] for result in sample_results]
                median, p95 = statistics(samples)
                timestamps = [
                    result.get("sample_started_at_utc_by_metric", {}).get(metric, result.get("sample_started_at_utc"))
                    for result in sample_results
                ]
                guard.require(all(isinstance(value, str) and value for value in timestamps), f"{metric}: sample UTC start missing")
                preparation_sequences = [
                    result.get("preparation_operation_ids_by_metric", {}).get(metric, result.get("preparation_operation_ids", []))
                    for result in sample_results
                ]
                guard.require(len(preparation_sequences) == len(samples) and all(isinstance(sequence, list) and sequence and all(isinstance(identifier, str) and identifier for identifier in sequence) for sequence in preparation_sequences), f"{metric}: exact per-sample preparation sequence missing")
                record = {
                    "schema_version": "taskflow-t1-benchmark/v2",
                    "experiment_id": "E06",
                    "fixture_id": "w3-isolated-native-mobile-stack",
                    "source_revision": self.source_revision,
                    "timestamp": min(timestamps),
                    "hardware": {"cpu": cpu, "cores": int(cores), "ram_gib": int(ram) / (1024 ** 3)},
                    "os": {"name": "macOS", "version": profile["macos_version"], "build": profile["macos_build"], "arch": profile["architecture"]},
                    "toolchain": [{"name": "Xcode", "version": f"{profile['xcode_version']} ({profile['xcode_build']})"}],
                    "state": "warm",
                    "preparation_command": "python3 experiments/e06-macos-feasibility/phase-b/execution/scripts/runner.py --execute --manifest experiments/e06-macos-feasibility/phase-b/execution-approval/execution-manifest.approved.json --binding experiments/e06-macos-feasibility/phase-b/execution-approval/implementation-binding.approved.json",
                    "sample_preparation_operation_ids": preparation_sequences,
                    "cache_dimensions": {"workspace": "recreated", "derived_data": "namespace-private", "simulator": mechanism or "not-applicable"},
                    "samples": samples,
                    "sample_count": len(samples),
                    "median": median,
                    "p95": p95,
                    "reservation_count": 1,
                    "lease_count": 1 if mechanism else 0,
                    "raw_result_location": "../raw",
                }
                records.append(record)
                target = REPOSITORY / path_value
                target.parent.mkdir(parents=True, exist_ok=True)
                encoded = json.dumps(record, indent=2, sort_keys=True) + "\n"
                target.write_text(encoded, encoding="utf-8")
                guard.require(target.read_text(encoding="utf-8") == encoded, f"benchmark reproduction mismatch: {path_value}")
                generated.append(path_value)
            hard_ok = all(result.get("status") in {"passed", "started"} for result in self.results.values()) and all(result.get("contamination_count", 0) == 0 and result.get("identity_or_lease_collision_count", 0) == 0 and result.get("orphan_count", 0) == 0 for result in self.results.values()) and all(result.get("status") == "passed" for result in final_cleanup)
            highest_clean = max((result["concurrency"] for result in self.results.values() if result.get("status") == "passed" and isinstance(result.get("concurrency"), int)), default=0)
            latency_ok = all(record["p95"] < (3.0 if "warm-workspace-ready" in path else 15.0) for path, record in zip(record_paths, records) if "warm-workspace-ready" in path or "simulator-ready-to-install" in path)
            recommendation = "stop-or-narrow" if not hard_ok or not latency_ok else ("serialized-macos-capacity" if highest_clean < 2 else "trusted-native-host")
            decision = {"format_version": "taskflow-e06-decision-recommendation/v1-experimental", "precedence": parameters["decision_precedence"], "hard_gates_passed": hard_ok, "latency_gates_passed": latency_ok, "highest_clean_concurrency": highest_clean, "recommendation": recommendation, "adr_edit_performed": False}
            summary = {"format_version": "taskflow-e06-summary/v1-experimental", "record_count": len(records), "record_sha256": [hashlib.sha256((REPOSITORY / path).read_bytes()).hexdigest() for path in record_paths], "decision": decision}
            for path_value, value in zip(output_paths[-2:], [summary, decision]):
                target = REPOSITORY / path_value
                encoded = json.dumps(value, indent=2, sort_keys=True) + "\n"
                target.write_text(encoded, encoding="utf-8")
                guard.require(target.read_text(encoding="utf-8") == encoded, f"summary reproduction mismatch: {path_value}")
                generated.append(path_value)
            return {"status": "passed", "generated_evidence_paths": generated, "record_count": len(records), "recommendation": recommendation, "adr_edit_performed": False}
        if action == "finalize-sanitized-evidence-and-checksums":
            guard.require(self.ledger is not None, "expanded ledger unavailable for evidence finalization")
            current_index = next(index for index, item in enumerate(self.ledger["operations"]) if item["id"] == operation["id"])
            expected = [item["id"] for item in self.ledger["operations"][:current_index]]
            missing = [identifier for identifier in expected if identifier not in self.results]
            guard.require(not missing, f"evidence results incomplete before finalization: {missing[:3]}")
            generated_prior = [path for result in self.results.values() for path in result.get("generated_evidence_paths", [])]
            final_record = {
                "status": "passed",
                "evidence_file_count": current_index + 1 + len(generated_prior),
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
            for result in self.results.values():
                for generated_path in result.get("generated_evidence_paths", []):
                    expected_paths.add(Path(generated_path).relative_to(self.manifest["evidence_root"]).as_posix())
            guard.require({item["path"] for item in entries} == expected_paths, "evidence file completeness mismatch")
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
        effect_started = self.monotonic_ns() if operation["kind"] == "effect" else None
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
        if effect_started is not None:
            effect_ended = self.monotonic_ns()
            record.setdefault("started_monotonic_ns", effect_started)
            record.setdefault("ended_monotonic_ns", effect_ended)
            record.setdefault("duration_ns", effect_ended - effect_started)
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
    binding = guard.load_object(args.binding)
    backend = NativeBackend(manifest, ledger, source_revision=binding["implementation_commit"])
    run_ledger(ledger, backend)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (guard.GuardError, RunnerError, OSError, ValueError) as error:
        print(f"e06-runner: {error}", file=sys.stderr)
        raise SystemExit(1)
