#!/usr/bin/env python3
"""Fail-closed guards for the E06 native execution implementation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


EXECUTION = Path(__file__).resolve().parents[1]
PHASE_B = EXECUTION.parent
REPOSITORY = PHASE_B.parents[2]
ROOT = "/private/tmp/taskflow-e06-native-a"
DEVICE_SET = f"{ROOT}/CoreSimulator"
PREFIX = "taskflow-e06-native-a-"
EVIDENCE = "experiments/e06-macos-feasibility/evidence/taskflow-e06-native-a"
CHILD_SANDBOX_PROFILE = "(version 1) (deny default) (allow file-read*) (allow file-write* (literal \"/private/tmp/taskflow-e06-native-a\") (subpath \"/private/tmp/taskflow-e06-native-a\")) (allow process-exec process-fork) (allow mach-lookup) (allow ipc-posix*) (allow sysctl-read)"
APPROVAL = PHASE_B / "execution-approval"
APPROVED_MANIFEST = APPROVAL / "execution-manifest.approved.json"
APPROVED_BINDING = APPROVAL / "implementation-binding.approved.json"
APPROVED_HOST_ATTESTATION = APPROVAL / "host-attestation.approved.json"
APPROVED_CORESIMULATOR_ATTESTATION = APPROVAL / "coresimulator-attestation.approved.json"
EXECUTION_MANIFEST_SCHEMA = PHASE_B.parent / "execution-manifest.schema.json"
EXECUTION_INVENTORY_PATHS = (
    "experiments/e06-macos-feasibility/phase-b/execution/README.md",
    "experiments/e06-macos-feasibility/phase-b/execution/Taskfile.yml",
    "experiments/e06-macos-feasibility/phase-b/execution/contract.json",
    "experiments/e06-macos-feasibility/phase-b/execution/expanded-ledger.json",
    "experiments/e06-macos-feasibility/phase-b/execution/schedule-spec.json",
    "experiments/e06-macos-feasibility/phase-b/execution/scripts/guard.py",
    "experiments/e06-macos-feasibility/phase-b/execution/scripts/runner.py",
    "experiments/e06-macos-feasibility/phase-b/execution/scripts/schedule.py",
    "experiments/e06-macos-feasibility/phase-b/execution/scripts/verify_execution.py",
    "experiments/e06-macos-feasibility/phase-b/execution/tests/test_execution.py",
)
FIXTURE_INVENTORY_PATHS = (
    "experiments/e06-macos-feasibility/phase-b/fixture/E06SmokeApp/E06SmokeApp.xcodeproj/project.pbxproj",
    "experiments/e06-macos-feasibility/phase-b/fixture/E06SmokeApp/E06SmokeApp.xcodeproj/xcshareddata/xcschemes/E06SmokeApp.xcscheme",
    "experiments/e06-macos-feasibility/phase-b/fixture/E06SmokeApp/E06SmokeApp/AppDelegate.swift",
)
COMPONENT_PATHS = {
    "expanded_ledger_sha256": "experiments/e06-macos-feasibility/phase-b/execution/expanded-ledger.json",
    "sandbox_policy_sha256": "experiments/e06-macos-feasibility/phase-b/sandbox-policy.json",
    "reset_policy_sha256": "experiments/e06-macos-feasibility/phase-b/reset-policy.json",
    "execution_manifest_schema_sha256": "experiments/e06-macos-feasibility/execution-manifest.schema.json",
    "phase_b_frozen_artifacts_sha256": "experiments/e06-macos-feasibility/phase-b/frozen-artifacts.json",
    "phase_b_protocol_file_sha256": "experiments/e06-macos-feasibility/phase-b/protocol.sha256",
    "phase_b_scope_hashes_sha256": "experiments/e06-macos-feasibility/phase-b/scope-hashes.json",
}
ALLOWED_EFFECTS = {
    "assert-profile-mismatch-rejected-before-mutation",
    "assert-root-absence-before-native",
    "assert-capacity-thermal-window",
    "record-timing-and-assert-clean-workspace",
    "record-timing-and-attest-simulator-identity",
    "aggregate-strict-p95",
    "record-build-install-test-timings-and-structured-result",
    "record-reset-cleanup-timings-and-residue",
    "seed-synthetic-contamination-markers",
    "assert-zero-cross-namespace-observations",
    "assert-zero-path-device-lease-or-identity-collision",
    "record-capacity-and-assert-all-hard-gates",
    "assert-lost-session-rejected-and-clean-retry-possible",
    "signal-recorded-child",
    "assert-cleanup-deadline-or-exact-orphan",
    "create-supervised-caller-lease",
    "observe-caller-lease-expiry",
    "verify-caller-loss-reclaim-order-and-deadline",
    "verify-clean-session-after-caller-loss",
    "record-not-applicable-and-unmeasured-limitations",
    "finalize-sanitized-evidence-and-checksums",
    "assert-no-owned-devices-or-record-exact-orphans",
    "assert-owned-root-absent-and-no-unrecorded-orphans",
    "attest-live-profile",
    "verify-build-output-manifest",
    "verify-installed-bundle-identity",
    "attest-reset-reusable-state",
    "emit-benchmark-v2-and-decision",
    "seed-reset-contamination-markers",
    "probe-reset-residue",
    "record-cleanup-timing-and-residue",
}


class GuardError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GuardError(message)


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GuardError(f"cannot read {path}: {error}") from error
    require(isinstance(value, dict), f"{path}: expected object")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def inventory_sha256(paths: tuple[str, ...], repository: Path = REPOSITORY) -> str:
    """Hash a fixed, ordered path-to-content inventory; paths and bytes are bound."""
    require(tuple(sorted(paths)) == paths and len(set(paths)) == len(paths), "inventory path set is not canonical")
    files = []
    for relative in paths:
        path = repository / relative
        require(path.is_file() and not path.is_symlink(), f"bound component missing or unsafe: {relative}")
        files.append({"path": relative, "sha256": sha256(path)})
    return canonical_sha256({"format_version": "taskflow-e06-file-inventory/v1-experimental", "files": files})


def implementation_component_hashes(repository: Path = REPOSITORY) -> dict[str, str]:
    values = {
        "execution_files_sha256": inventory_sha256(EXECUTION_INVENTORY_PATHS, repository),
        "fixture_files_sha256": inventory_sha256(FIXTURE_INVENTORY_PATHS, repository),
    }
    for field, relative in COMPONENT_PATHS.items():
        path = repository / relative
        require(path.is_file() and not path.is_symlink(), f"bound component missing or unsafe: {relative}")
        values[field] = sha256(path)
    protocol = (repository / COMPONENT_PATHS["phase_b_protocol_file_sha256"]).read_text(encoding="utf-8").split()
    require(len(protocol) >= 1 and re.fullmatch(r"[0-9a-f]{64}", protocol[0]) is not None, "Phase-B protocol digest missing")
    values["phase_b_protocol_digest"] = protocol[0]
    return values


def under_root(value: str, allow_root: bool = False) -> bool:
    path = PurePosixPath(value)
    root = PurePosixPath(ROOT)
    return ".." not in path.parts and (root in path.parents or (allow_root and path == root))


def safe_evidence(value: str) -> bool:
    path = PurePosixPath(value)
    base = PurePosixPath(EVIDENCE)
    return ".." not in path.parts and (path == base or base in path.parents)


def validate_target(target: str) -> None:
    allowed = (
        under_root(target, allow_root=True)
        or safe_evidence(target)
        or target.startswith(PREFIX)
        or target.startswith("recorded-child:")
        or target in {"namespace-a", "namespace-b", "namespace-c", "namespace-d"}
    )
    require(allowed, f"target outside experiment ownership: {target}")


def validate_command(operation: dict[str, Any]) -> None:
    argv = operation.get("argv")
    require(isinstance(argv, list) and argv and all(isinstance(item, str) for item in argv), f"{operation.get('id')}: invalid argv")
    require(argv[:3] == ["/usr/bin/sandbox-exec", "-p", CHILD_SANDBOX_PROFILE], f"{operation['id']}: deny-default owned-write sandbox missing")
    argv = argv[3:]
    require(argv, f"{operation['id']}: wrapped command missing")
    executable = argv[0]
    require(executable in {"/bin/mkdir", "/bin/rm", "/bin/df", "/bin/sleep", "/usr/bin/ditto", "/usr/bin/xcodebuild", "/usr/bin/xcrun", "/usr/bin/sw_vers", "/usr/bin/uname", "/usr/bin/vm_stat", "/usr/bin/swift", "/usr/sbin/sysctl"}, f"{operation['id']}: executable forbidden")
    require(not any("*" in item or "?" in item for item in argv), f"{operation['id']}: glob forbidden")
    if executable == "/bin/mkdir":
        require(argv[1] == "-p" and all(under_root(item) for item in argv[2:]), f"{operation['id']}: unsafe mkdir")
    elif executable == "/bin/rm":
        require(argv[1:3] == ["-rf", "--"] and len(argv) == 4 and under_root(argv[3], allow_root=True), f"{operation['id']}: unsafe removal")
    elif executable == "/usr/bin/ditto":
        require(len(argv) == 3 and argv[1] == "experiments/e06-macos-feasibility/phase-b/fixture/E06SmokeApp" and under_root(argv[2]), f"{operation['id']}: unsafe fixture copy")
    elif executable == "/usr/bin/xcodebuild":
        if argv == ["/usr/bin/xcodebuild", "-version"]:
            require(operation["mutates"] is False, f"{operation['id']}: version query marked mutating")
        else:
            require("-derivedDataPath" in argv and "CODE_SIGNING_ALLOWED=NO" in argv, f"{operation['id']}: unbounded xcodebuild")
            derived = argv[argv.index("-derivedDataPath") + 1]
            project = argv[argv.index("-project") + 1] if "-project" in argv else ""
            require(under_root(derived) and under_root(project), f"{operation['id']}: xcode path outside root")
            require("-allowProvisioningUpdates" not in argv, f"{operation['id']}: provisioning/network forbidden")
    elif executable == "/usr/bin/xcrun":
        if len(argv) == 4 and argv[1] in {"--sdk"} and argv[2] in {"iphoneos", "iphonesimulator"} and argv[3] in {"--show-sdk-version", "--show-sdk-build-version"}:
            require(operation["mutates"] is False, f"{operation['id']}: SDK query marked mutating")
            return
        require(len(argv) >= 6 and argv[1:4] == ["simctl", "--set", DEVICE_SET], f"{operation['id']}: default or mismatched device set")
        action = argv[4]
        require(action in {"create", "clone", "boot", "bootstatus", "install", "launch", "shutdown", "erase", "delete", "list", "listapps", "get_app_container"}, f"{operation['id']}: simctl action forbidden")
        if action not in {"list", "listapps", "get_app_container"}:
            names = [item for item in argv[5:] if item.startswith("taskflow-e06-")]
            require(names and all(item.startswith(PREFIX) for item in names), f"{operation['id']}: simulator ownership prefix missing")
        if action == "listapps":
            require(len(argv) == 6 and argv[5].startswith(PREFIX) and operation["mutates"] is False, f"{operation['id']}: unsafe installation-service probe")
    elif executable == "/usr/bin/sw_vers":
        require(argv in [["/usr/bin/sw_vers", "-productVersion"], ["/usr/bin/sw_vers", "-buildVersion"]], f"{operation['id']}: unexpected sw_vers query")
    elif executable == "/usr/bin/uname":
        require(argv == ["/usr/bin/uname", "-m"], f"{operation['id']}: unexpected uname query")
    elif executable == "/usr/bin/vm_stat":
        require(argv == ["/usr/bin/vm_stat"] and operation["mutates"] is False, f"{operation['id']}: unexpected vm_stat query")
    elif executable == "/bin/df":
        require(argv == ["/bin/df", "-Pk", "/private/tmp"] and operation["mutates"] is False, f"{operation['id']}: unexpected disk query")
    elif executable == "/bin/sleep":
        require(argv == ["/bin/sleep", "30"] and operation["kind"] == "child-command" and operation["mutates"] is False, f"{operation['id']}: caller child must be the exact bounded sleep")
    elif executable == "/usr/bin/swift":
        require(argv == ["/usr/bin/swift", "-e", "import Foundation; print(ProcessInfo.processInfo.thermalState.rawValue)"], f"{operation['id']}: unexpected thermal query")
        require(operation["mutates"] is True and operation["targets"] == [f"{ROOT}/controller/cache"], f"{operation['id']}: thermal compiler cache boundary missing")
    elif executable == "/usr/sbin/sysctl":
        require(argv in [["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"], ["/usr/sbin/sysctl", "-n", "hw.physicalcpu"], ["/usr/sbin/sysctl", "-n", "hw.memsize"]] and operation["mutates"] is False, f"{operation['id']}: unexpected hardware query")


def validate_ledger(ledger: dict[str, Any]) -> None:
    require(ledger.get("format_version") == "taskflow-e06-expanded-ledger/v1-experimental", "ledger format drifted")
    require(ledger.get("status") == "repository-generated-not-approved-not-executed", "ledger status drifted")
    operations = ledger.get("operations")
    require(isinstance(operations, list) and operations, "ledger operations missing")
    require(ledger.get("operation_count") == len(operations), "ledger operation count drifted")
    require(ledger.get("execution_count") == 0, "ledger contains execution evidence")
    all_ids = [item.get("id") for item in operations]
    require(all(isinstance(item, str) and item for item in all_ids) and len(set(all_ids)) == len(all_ids), "operation id missing or duplicated")
    positions = {identifier: index for index, identifier in enumerate(all_ids)}
    all_operations = {item["id"]: item for item in operations}
    seen: dict[str, dict[str, Any]] = {}
    child_handles: dict[str, str] = {}
    for operation in operations:
        identifier = operation.get("id")
        require(isinstance(identifier, str) and identifier and identifier not in seen, "operation id missing or duplicated")
        require(operation.get("kind") in {"command", "child-command", "effect"}, f"{identifier}: invalid kind")
        require(isinstance(operation.get("mutates"), bool), f"{identifier}: mutation flag missing")
        namespace = operation.get("namespace")
        require(namespace == "controller" or namespace in NAMESPACE_NAMES or (isinstance(namespace, list) and namespace and namespace == sorted(set(namespace)) and all(item in NAMESPACE_NAMES for item in namespace)), f"{identifier}: namespace declaration invalid")
        require(isinstance(operation.get("repetition"), int) and operation["repetition"] >= 0, f"{identifier}: repetition declaration invalid")
        require(operation.get("timeout_seconds") == 900, f"{identifier}: timeout drifted")
        cleanup_action = operation.get("cleanup_action")
        require(isinstance(cleanup_action, dict) and set(cleanup_action) == {"on_success", "on_failure"}, f"{identifier}: cleanup action missing")
        success = cleanup_action["on_success"]
        failure = cleanup_action["on_failure"]
        require(isinstance(success, dict) and isinstance(failure, dict), f"{identifier}: cleanup disposition invalid")
        operation_argv = operation.get("argv", [])[3:]
        is_device_delete = len(operation_argv) > 5 and operation_argv[:4] == ["/usr/bin/xcrun", "simctl", "--set", DEVICE_SET] and operation_argv[4] == "delete"
        is_path_remove = len(operation_argv) == 4 and operation_argv[:3] == ["/bin/rm", "-rf", "--"] and identifier != "cleanup.remove-owned-root"
        is_evidence_mutation = operation["mutates"] and operation.get("targets") and all(safe_evidence(target) for target in operation["targets"])
        if is_evidence_mutation:
            require(success == {"disposition": "none", "reason": "approved-evidence-retained"} and failure.get("disposition") == "retain-orphan" and failure.get("reason") == "partial-evidence-retained", f"{identifier}: evidence retention disposition drifted")
        elif is_device_delete or is_path_remove:
            expected_reason = "terminal-owned-device-removal" if is_device_delete else "terminal-owned-path-removal"
            require(success == {"disposition": "none", "reason": expected_reason} and failure.get("disposition") == "retain-orphan", f"{identifier}: resource cleanup disposition drifted")
        elif operation["mutates"] and identifier != "cleanup.remove-owned-root":
            require(success.get("disposition") == "later-operations", f"{identifier}: mutating success has no later cleanup")
            cleanup_ids = success.get("operation_ids")
            require(isinstance(cleanup_ids, list) and cleanup_ids, f"{identifier}: cleanup references missing")
            for cleanup_id in cleanup_ids:
                require(cleanup_id in positions and positions[cleanup_id] > positions[identifier], f"{identifier}: cleanup reference is missing or not later: {cleanup_id}")
                cleanup_operation = all_operations[cleanup_id]
                require(cleanup_operation.get("mutates") is True, f"{identifier}: cleanup reference is not mutating: {cleanup_id}")
                require(all(isinstance(target, str) and (under_root(target, allow_root=True) or target.startswith(PREFIX)) for target in cleanup_operation.get("targets", [])), f"{identifier}: cleanup reference is outside owned state: {cleanup_id}")
                argv = cleanup_operation.get("argv", [])[3:]
                semantic_cleanup = (len(argv) > 5 and argv[:4] == ["/usr/bin/xcrun", "simctl", "--set", DEVICE_SET] and argv[4] == "delete") or (len(argv) == 4 and argv[:3] == ["/bin/rm", "-rf", "--"])
                require(semantic_cleanup, f"{identifier}: cleanup reference is not a cleanup-class operation: {cleanup_id}")
                retained = operation.get("parameters", {}).get("retained_owned_targets", operation["targets"])
                cleanup_targets = cleanup_operation.get("targets", [])
                covered = any(
                    target in cleanup_targets
                    or any(under_root(target, allow_root=True) and under_root(cleanup_target, allow_root=True) and (target == cleanup_target or target.startswith(cleanup_target.rstrip("/") + "/")) for cleanup_target in cleanup_targets)
                    for target in retained
                    if target.startswith(PREFIX) or target.startswith(ROOT)
                )
                require(covered, f"{identifier}: cleanup reference does not cover an owned target: {cleanup_id}")
            require(failure.get("disposition") == "retain-orphan" and failure.get("reason") == "fail-closed-no-scope-widening" and isinstance(failure.get("targets"), list), f"{identifier}: failure cleanup may widen scope")
        elif identifier == "cleanup.remove-owned-root":
            require(success == {"disposition": "none", "reason": "terminal-owned-root-removal"} and failure.get("disposition") == "retain-orphan", f"{identifier}: terminal cleanup disposition drifted")
        else:
            require(success == {"disposition": "none", "reason": "read-only-no-new-state"}, f"{identifier}: read-only success disposition drifted")
            require((failure == {"disposition": "none", "reason": "read-only-no-owned-state"}) or (failure.get("disposition") == "retain-orphan" and failure.get("reason") == "fail-closed-no-scope-widening" and isinstance(failure.get("targets"), list) and failure["targets"]), f"{identifier}: read-only failure disposition drifted")
        if operation["kind"] in {"command", "child-command"}:
            require(operation.get("expected_result") in {"success", "failure"}, f"{identifier}: unexpected command-result policy")
            if operation["kind"] == "child-command":
                require(operation["expected_result"] == "success", f"{identifier}: child command cannot predeclare asynchronous failure")
        has_group = "parallel_group" in operation or "parallel_step" in operation
        if has_group:
            require(isinstance(operation.get("parallel_group"), str) and operation["parallel_group"], f"{identifier}: invalid parallel group")
            require(isinstance(operation.get("parallel_step"), int) and operation["parallel_step"] > 0, f"{identifier}: invalid parallel step")
        prerequisites = operation.get("prerequisites")
        require(isinstance(prerequisites, list) and all(item in seen for item in prerequisites), f"{identifier}: prerequisite is not earlier")
        targets = operation.get("targets")
        require(isinstance(targets, list), f"{identifier}: targets missing")
        for target in targets:
            require(isinstance(target, str), f"{identifier}: invalid target")
            validate_target(target)
        evidence = operation.get("evidence")
        require(isinstance(evidence, str) and safe_evidence(evidence), f"{identifier}: unsafe evidence path")
        if operation["kind"] in {"command", "child-command"}:
            validate_command(operation)
        if operation["kind"] == "child-command":
            handle = operation.get("child_handle")
            require(isinstance(handle, str) and handle and handle not in child_handles, f"{identifier}: invalid child handle")
            child_handles[handle] = identifier
        if operation["kind"] == "effect":
            require(operation.get("action") in ALLOWED_EFFECTS, f"{identifier}: effect forbidden")
            parameters = operation.get("parameters", {})
            if operation.get("action") in {"create-supervised-caller-lease", "observe-caller-lease-expiry"}:
                require(parameters.get("ttl_seconds") == 1.0 and parameters.get("heartbeat_seconds") == 0.25, f"{identifier}: caller lease timing drifted")
                require(parameters.get("lease_path") == f"{ROOT}/controller/leases/{parameters.get('lease_id')}.json", f"{identifier}: caller lease path drifted")
            if operation.get("action") == "create-supervised-caller-lease":
                require(parameters.get("identity_operation_id") in seen, f"{identifier}: caller device identity result is not owned")
            if operation.get("action") == "observe-caller-lease-expiry":
                require(parameters.get("signal_operation_id") in seen and seen[parameters["signal_operation_id"]].get("action") == "signal-recorded-child", f"{identifier}: caller-loss signal result is not owned")
            if operation.get("action") == "verify-caller-loss-reclaim-order-and-deadline":
                require(parameters.get("cleanup_grace_seconds") == 30.0, f"{identifier}: caller reclaim grace drifted")
                require(parameters.get("expected_events") == ["lease.heartbeat.missed", "lease.expired", "orphan.detected", "orphan.reclaimed"], f"{identifier}: W3 caller-loss event order drifted")
                result_ids = [*parameters.get("cleanup_operation_ids", []), parameters.get("post_cleanup_identity_operation_id")]
                require(result_ids and all(item in seen for item in result_ids), f"{identifier}: caller cleanup result is not owned")
            if operation.get("action") == "verify-clean-session-after-caller-loss":
                result_ids = [parameters.get("retry_identity_operation_id"), parameters.get("retry_launch_operation_id"), parameters.get("post_cleanup_identity_operation_id")]
                require(all(item in seen for item in result_ids), f"{identifier}: caller retry result is not owned")
            if operation.get("action") == "signal-recorded-child":
                require(len(targets) == 1 and targets[0].startswith("recorded-child:"), f"{identifier}: signal target invalid")
                handle = targets[0].split(":", 1)[1]
                require(handle in child_handles and child_handles[handle] in prerequisites, f"{identifier}: unrecorded or non-prerequisite child")
                require(set(parameters) == {"signal", "owned_process_group_required", "retained_owned_targets"} and parameters["signal"] == "SIGTERM" and parameters["owned_process_group_required"] is True, f"{identifier}: signal policy drifted")
                require(isinstance(parameters["retained_owned_targets"], list) and parameters["retained_owned_targets"] and all(isinstance(item, str) for item in parameters["retained_owned_targets"]), f"{identifier}: retained owned targets missing")
                for target in parameters["retained_owned_targets"]:
                    validate_target(target)
            if operation.get("action") == "attest-reset-reusable-state":
                reset_ids = parameters.get("reset_operation_ids")
                require(isinstance(reset_ids, list) and reset_ids and identifier not in reset_ids and all(item in seen for item in reset_ids), f"{identifier}: reset measurement self-reference or missing source")
                require(parameters.get("expected_device_state") in {"Shutdown", "absent"}, f"{identifier}: reset state missing")
            if operation.get("action") == "emit-benchmark-v2-and-decision":
                cleanup_ids = parameters.get("final_cleanup_operation_ids")
                require(isinstance(cleanup_ids, list) and cleanup_ids == ["cleanup.assert-no-owned-devices-or-record-orphans", "cleanup.remove-owned-root", "cleanup.verify-absence"] and all(item in seen for item in cleanup_ids), f"{identifier}: final cleanup binding missing")
        seen[identifier] = operation


def manifest_commands(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"id": item["id"], "argv": item["argv"], "mutates": item["mutates"], "targets": item["targets"]}
        for item in ledger["operations"]
        if item["kind"] in {"command", "child-command"}
    ]


def parse_time(value: Any, field: str) -> datetime:
    require(isinstance(value, str), f"{field}: missing date-time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise GuardError(f"{field}: invalid date-time") from error
    require(parsed.tzinfo is not None, f"{field}: timezone required")
    return parsed.astimezone(timezone.utc)


def validate_against_accepted_schema(manifest: dict[str, Any]) -> None:
    verifier_path = PHASE_B / "approval/scripts/verify_approval.py"
    spec = importlib.util.spec_from_file_location("e06_accepted_schema_validator", verifier_path)
    require(spec is not None and spec.loader is not None, "cannot load accepted schema validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    schema = load_object(EXECUTION_MANIFEST_SCHEMA)
    try:
        module.validate_schema(manifest, schema, schema)
    except module.VerificationError as error:
        raise GuardError(f"accepted execution-manifest schema rejected manifest: {error}") from error


def validate_manifest(manifest: dict[str, Any], ledger: dict[str, Any], *, require_current_window: bool) -> None:
    validate_against_accepted_schema(manifest)
    required = {"format_version", "manifest_id", "phase_b_ticket", "candidate_id", "operator", "approval", "host", "profile", "paths", "resources", "commands", "cleanup_allowlist", "evidence_root"}
    require(set(manifest) == required, "manifest top-level fields drifted")
    require(manifest["format_version"] == "taskflow-e06-execution-manifest/v1-experimental", "manifest format drifted")
    require(manifest["manifest_id"] == "taskflow-e06-native-a" and manifest["phase_b_ticket"] == "TF-003.14" and manifest["candidate_id"] == "trusted-native-host", "manifest identity drifted")
    require(isinstance(manifest["operator"].get("id"), str) and manifest["operator"]["id"], "operator missing")
    approval = manifest["approval"]
    require(isinstance(approval.get("approved_by"), str) and approval["approved_by"], "approval identity missing")
    approved_at = parse_time(approval.get("approved_at"), "approved_at")
    require(approval.get("plan_approval_is_not_execution_approval") is True, "approval boundary missing")
    require(isinstance(approval.get("exact_mutation_scope"), list) and approval["exact_mutation_scope"], "exact mutation scope missing")
    scope_text = "\n".join(approval["exact_mutation_scope"])
    require(ROOT in scope_text, "approval does not name the child mutable root")
    require(EVIDENCE in scope_text, "approval does not separately name runner evidence writes")
    require("CoreSimulatorService" in scope_text, "approval does not name the external CoreSimulatorService mutation boundary")
    host = manifest["host"]
    start = parse_time(host.get("exclusive_window_start"), "exclusive_window_start")
    end = parse_time(host.get("exclusive_window_end"), "exclusive_window_end")
    require(start < end and approved_at <= end, "approval/window ordering invalid")
    if require_current_window:
        now = datetime.now(timezone.utc)
        require(start <= now <= end, "approval window is not current")
    require(host.get("resource_id") == "taskflow-e06-local-mac17-7", "host resource drifted")
    require(host.get("inventory_snapshot_sha256") == "9e021a326cba6e3b3b92c6cfa9f274c531d5f9cf13b95a4f314f2afc95d80630", "inventory digest drifted")
    paths = manifest["paths"]
    require(paths.get("mutable_root") == ROOT and paths.get("custom_device_set_root") == DEVICE_SET, "manifest root/device set drifted")
    require(paths.get("default_simulator_set_forbidden") is True, "default device set not forbidden")
    for key in ("workspace_roots", "derived_data_roots"):
        require(isinstance(paths.get(key), list) and len(paths[key]) == 4 and all(under_root(item) for item in paths[key]), f"manifest {key} incomplete")
    resources = manifest["resources"]
    require(resources == {"concurrency_levels": [1, 2, 3, 4], "min_free_ram_gib": 16, "min_free_disk_gib": 200, "thermal_stop_signal": "serious", "per_command_timeout_seconds": 900}, "resource/threshold contract drifted")
    require(manifest["commands"] == manifest_commands(ledger), "manifest commands do not exactly match expanded ledger")
    cleanup = manifest["cleanup_allowlist"]
    require(cleanup.get("paths") == [ROOT, DEVICE_SET, *[f"{ROOT}/{name}" for name in NAMESPACE_NAMES]], "cleanup paths drifted")
    require(cleanup.get("vm_names") == [] and cleanup.get("simulator_name_prefix") == PREFIX, "cleanup identity drifted")
    require(cleanup.get("immutable_base_delete_forbidden") is True and cleanup.get("broad_process_kill_forbidden") is True, "cleanup prohibition missing")
    require(manifest["evidence_root"] == EVIDENCE, "evidence root drifted")
    profile = manifest["profile"]
    require(profile.get("base_image_digest") is None, "native base image must be null")
    for key in ("expected_profile_digest", "runner_digest", "sandbox_policy_digest", "reset_policy_digest"):
        require(re.fullmatch(r"[0-9a-f]{64}", profile.get(key, "")) is not None, f"profile digest invalid: {key}")


NAMESPACE_NAMES = ["namespace-a", "namespace-b", "namespace-c", "namespace-d"]


def git_value(*arguments: str) -> str:
    completed = subprocess.run(["git", *arguments], cwd=REPOSITORY, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    require(completed.returncode == 0, completed.stderr.strip())
    return completed.stdout.strip()


def validate_execution_binding(manifest_path: Path, binding_path: Path, ledger: dict[str, Any]) -> dict[str, Any]:
    require(manifest_path.resolve() == APPROVED_MANIFEST.resolve(), "manifest path is not the approved location")
    require(binding_path.resolve() == APPROVED_BINDING.resolve(), "binding path is not the approved location")
    manifest = load_object(manifest_path)
    binding = load_object(binding_path)
    require(binding.get("format_version") == "taskflow-e06-implementation-binding/v1-experimental", "binding format drifted")
    component_fields = set(implementation_component_hashes())
    require(set(binding) == {"format_version", "implementation_commit", "implementation_tree", "manifest_sha256", *component_fields, "host_attestation_sha256", "coresimulator_attestation_sha256", "approved_by", "approved_at", "exclusive_window_start", "exclusive_window_end"}, "binding fields drifted")
    require(binding["implementation_commit"] == git_value("rev-parse", "HEAD"), "binding commit is not HEAD")
    require(binding["implementation_tree"] == git_value("rev-parse", "HEAD^{tree}"), "binding tree is not HEAD tree")
    require(binding["manifest_sha256"] == sha256(manifest_path), "binding manifest digest drifted")
    actual_components = implementation_component_hashes()
    for field, actual in actual_components.items():
        require(binding.get(field) == actual, f"binding component digest drifted: {field}")
    require(manifest["profile"]["runner_digest"] == binding["execution_files_sha256"], "manifest runner digest is not the approved execution files digest")
    require(manifest["profile"]["sandbox_policy_digest"] == binding["sandbox_policy_sha256"], "sandbox policy digest drifted")
    require(manifest["profile"]["reset_policy_digest"] == binding["reset_policy_sha256"], "reset policy digest drifted")
    require(APPROVED_HOST_ATTESTATION.is_file() and binding.get("host_attestation_sha256") == sha256(APPROVED_HOST_ATTESTATION), "host attestation absent or digest drifted")
    require(APPROVED_CORESIMULATOR_ATTESTATION.is_file() and binding.get("coresimulator_attestation_sha256") == sha256(APPROVED_CORESIMULATOR_ATTESTATION), "CoreSimulator attestation absent or digest drifted")
    require(binding["approved_by"] == manifest["approval"]["approved_by"] and binding["approved_at"] == manifest["approval"]["approved_at"], "binding approval identity/time drifted")
    require(binding["exclusive_window_start"] == manifest["host"]["exclusive_window_start"] and binding["exclusive_window_end"] == manifest["host"]["exclusive_window_end"], "binding window drifted")
    validate_manifest(manifest, ledger, require_current_window=True)
    host_attestation = load_object(APPROVED_HOST_ATTESTATION)
    require(set(host_attestation) == {"format_version", "collected_at", "resource_id", "expected_profile_digest", "free_ram_gib", "free_disk_gib", "thermal_state", "exclusive_window_confirmed", "mutable_root_absent"}, "host attestation fields drifted")
    require(host_attestation["format_version"] == "taskflow-e06-host-attestation/v1-experimental", "host attestation format drifted")
    collected_at = parse_time(host_attestation["collected_at"], "host collected_at")
    require(parse_time(binding["exclusive_window_start"], "binding window start") <= collected_at <= parse_time(binding["exclusive_window_end"], "binding window end"), "host attestation outside approved window")
    require(host_attestation["resource_id"] == manifest["host"]["resource_id"], "attested host resource drifted")
    require(host_attestation["expected_profile_digest"] == manifest["profile"]["expected_profile_digest"], "attested profile digest drifted")
    require(host_attestation["free_ram_gib"] >= manifest["resources"]["min_free_ram_gib"] and host_attestation["free_disk_gib"] >= manifest["resources"]["min_free_disk_gib"], "attested capacity below floor")
    require(host_attestation["thermal_state"] in {"nominal", "fair"}, "attested thermal state reaches stop level")
    require(host_attestation["exclusive_window_confirmed"] is True and host_attestation["mutable_root_absent"] is True, "host exclusivity/root absence not attested")
    coresimulator = load_object(APPROVED_CORESIMULATOR_ATTESTATION)
    require(set(coresimulator) == {"format_version", "collected_at", "custom_device_set_root", "runtime_identifier", "runtime_build", "architectures", "device_type", "custom_set_accessible", "default_device_set_accessed", "preexisting_experiment_devices", "service_side_boundary_verified", "service_side_boundary_mechanism", "service_side_write_paths", "service_side_cleanup_policy_sha256"}, "CoreSimulator attestation fields drifted")
    require(coresimulator["format_version"] == "taskflow-e06-coresimulator-attestation/v1-experimental", "CoreSimulator attestation format drifted")
    core_collected_at = parse_time(coresimulator["collected_at"], "CoreSimulator collected_at")
    require(parse_time(binding["exclusive_window_start"], "binding window start") <= core_collected_at <= parse_time(binding["exclusive_window_end"], "binding window end"), "CoreSimulator attestation outside approved window")
    require(coresimulator["custom_device_set_root"] == DEVICE_SET and coresimulator["custom_set_accessible"] is True, "custom device set not attested")
    require(coresimulator["runtime_identifier"] == "com.apple.CoreSimulator.SimRuntime.iOS-26-5" and coresimulator["runtime_build"] == "23F77" and coresimulator["architectures"] == ["arm64"], "CoreSimulator runtime drifted")
    require(coresimulator["device_type"] == "com.apple.CoreSimulator.SimDeviceType.iPhone-17", "CoreSimulator device type drifted")
    require(coresimulator["default_device_set_accessed"] is False and coresimulator["preexisting_experiment_devices"] == [], "default or pre-existing simulator state observed")
    require(coresimulator["service_side_boundary_verified"] is True, "CoreSimulatorService write boundary is unresolved")
    require(coresimulator["service_side_boundary_mechanism"] in {"dedicated-ephemeral-account", "dedicated-host"}, "CoreSimulatorService requires a dedicated account or host")
    require(isinstance(coresimulator["service_side_write_paths"], list) and coresimulator["service_side_write_paths"] and all(isinstance(item, str) and item.startswith("/") and ".." not in PurePosixPath(item).parts for item in coresimulator["service_side_write_paths"]), "CoreSimulatorService write paths are not exact")
    require(re.fullmatch(r"[0-9a-f]{64}", coresimulator.get("service_side_cleanup_policy_sha256", "")) is not None, "CoreSimulatorService cleanup policy is not bound")
    scope_text = "\n".join(manifest["approval"]["exact_mutation_scope"])
    require(all(path in scope_text for path in coresimulator["service_side_write_paths"]), "approval omits an attested CoreSimulatorService write path")
    require(not os.path.lexists(ROOT), "mutable root already exists; ownership cannot be established")
    return manifest
