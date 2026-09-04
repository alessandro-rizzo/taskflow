#!/usr/bin/env python3
"""Verify E06 execution preparation without reaching a native primitive."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


EXECUTION = Path(__file__).resolve().parents[1]
PHASE_B = EXECUTION.parent
PHASE_A = PHASE_B.parent
REPOSITORY = PHASE_B.parents[2]
sys.path.insert(0, str(EXECUTION / "scripts"))

import guard  # noqa: E402
import schedule  # noqa: E402


PHASE_A_COMMIT = "098035bf29656c3fd3b3991224a98fdded3453b7"
PHASE_B_COMMIT = "6decbbd1323fd9a69137129db234028d80b1151d"
AUDIT_COMMIT = "83d36f8eea6ec818f41ed4fc376b85be2d48f1c3"
EXPECTED_FILES = {
    "README.md",
    "Taskfile.yml",
    "contract.json",
    "expanded-ledger.json",
    "schedule-spec.json",
    "scripts/guard.py",
    "scripts/runner.py",
    "scripts/schedule.py",
    "scripts/verify_execution.py",
    "tests/test_execution.py",
}
AUDIT_FILES = {
    "README.md",
    "approval-packet.json",
    "approval-request.md",
    "cleanup-ledger.json",
    "host-attestation.json",
    "scripts/verify_approval.py",
    "tests/test_approval.py",
}


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def git_bytes(commit: str, relative: str) -> bytes:
    completed = subprocess.run(["git", "show", f"{commit}:{relative}"], cwd=REPOSITORY, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(completed.returncode == 0, completed.stderr.decode("utf-8", "replace").strip())
    return completed.stdout


def git_text(*arguments: str) -> str:
    completed = subprocess.run(["git", *arguments], cwd=REPOSITORY, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    require(completed.returncode == 0, completed.stderr.strip())
    return completed.stdout.strip()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path}: expected object")
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def verify_anchors() -> None:
    require(git_text("merge-base", "--is-ancestor", PHASE_A_COMMIT, PHASE_B_COMMIT) == "", "Phase A is not an ancestor of frozen Phase B")
    require(git_text("merge-base", "--is-ancestor", PHASE_B_COMMIT, AUDIT_COMMIT) == "", "frozen Phase B is not an ancestor of audit")
    require(git_text("merge-base", "--is-ancestor", AUDIT_COMMIT, "HEAD") == "", "audit is not an ancestor of HEAD")

    phase_a_manifest_path = "experiments/e06-macos-feasibility/frozen-artifacts.json"
    phase_a_manifest = json.loads(git_bytes(PHASE_A_COMMIT, phase_a_manifest_path))
    for item in phase_a_manifest["artifacts"]:
        relative = f"experiments/e06-macos-feasibility/{item['path']}"
        accepted = git_bytes(PHASE_A_COMMIT, relative)
        require(sha256_bytes(accepted) == item["sha256"], f"accepted Phase-A digest drift: {relative}")
        require((REPOSITORY / relative).read_bytes() == accepted, f"live Phase-A drift: {relative}")
    for relative in (phase_a_manifest_path, "experiments/e06-macos-feasibility/protocol.sha256"):
        require((REPOSITORY / relative).read_bytes() == git_bytes(PHASE_A_COMMIT, relative), f"live Phase-A control drift: {relative}")

    phase_b_manifest_path = "experiments/e06-macos-feasibility/phase-b/frozen-artifacts.json"
    phase_b_manifest = json.loads(git_bytes(PHASE_B_COMMIT, phase_b_manifest_path))
    for item in phase_b_manifest["artifacts"]:
        relative = f"experiments/e06-macos-feasibility/phase-b/{item['path']}"
        frozen = git_bytes(PHASE_B_COMMIT, relative)
        require(sha256_bytes(frozen) == item["sha256"], f"frozen Phase-B digest drift: {relative}")
        require((REPOSITORY / relative).read_bytes() == frozen, f"live frozen Phase-B drift: {relative}")
    for relative in (phase_b_manifest_path, "experiments/e06-macos-feasibility/phase-b/protocol.sha256"):
        require((REPOSITORY / relative).read_bytes() == git_bytes(PHASE_B_COMMIT, relative), f"live Phase-B control drift: {relative}")

    for relative in sorted(AUDIT_FILES):
        repository_relative = f"experiments/e06-macos-feasibility/phase-b/approval/{relative}"
        require((REPOSITORY / repository_relative).read_bytes() == git_bytes(AUDIT_COMMIT, repository_relative), f"retained audit drift: {repository_relative}")


def verify_retained_audit_snapshot() -> None:
    verifier_path = PHASE_B / "approval/scripts/verify_approval.py"
    spec = importlib.util.spec_from_file_location("retained_e06_approval_verifier", verifier_path)
    require(spec is not None and spec.loader is not None, "cannot load retained audit verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_git_output = module.git_output

    def frozen_git_output(*arguments: str) -> bytes:
        if arguments == ("rev-parse", "HEAD"):
            return (PHASE_B_COMMIT + "\n").encode("utf-8")
        return original_git_output(*arguments)

    module.git_output = frozen_git_output
    module.verify()


def verify_fileset() -> None:
    found = {
        item.relative_to(EXECUTION).as_posix()
        for item in EXECUTION.rglob("*")
        if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc" and item.name != ".DS_Store"
    }
    require(found == EXPECTED_FILES, f"execution fileset mismatch: missing={sorted(EXPECTED_FILES - found)} extra={sorted(found - EXPECTED_FILES)}")


def verify_contract_and_schedule() -> None:
    contract = load(EXECUTION / "contract.json")
    require(contract["status"] == "repository-only-not-approved-not-executed" and contract["execution_count"] == 0, "execution contract status drifted")
    anchors = [item["commit"] for item in contract["immutable_anchors"]]
    require(anchors == [PHASE_A_COMMIT, PHASE_B_COMMIT, AUDIT_COMMIT], "contract anchors drifted")
    require(contract["execution_gate"]["required_cli_flag"] == "--execute", "explicit execution flag missing")
    require(contract["repository_modes_may_execute"] is False, "repository mode execution not forbidden")
    require(contract["thresholds"]["caller_loss_lease_ttl_seconds"] == schedule.CALLER_LEASE_TTL_SECONDS, "caller-loss TTL drifted")
    require(contract["thresholds"]["caller_loss_heartbeat_seconds"] == schedule.CALLER_HEARTBEAT_SECONDS, "caller-loss heartbeat drifted")

    spec = load(EXECUTION / "schedule-spec.json")
    require(spec["simulator_order"] == list(schedule.MECHANISMS), "simulator order drifted")
    require(spec["timing"] == {"warm-workspace-ready": 30, "simulator-ready-to-install-per-mechanism": 30, "xcode-build-per-mechanism": 15, "simulator-install-per-mechanism": 15, "mobile-test-per-mechanism": 15, "candidate-reset-per-mechanism": 15, "candidate-cleanup-per-mechanism": 15}, "timing sample counts drifted")
    require(spec["correctness"] == {"alternating-namespace-contamination": 20, "two-namespace-isolation": 10, "bounded-maximum-safe-concurrency": {"levels": [1, 2, 3, 4], "repetitions_per_level": 5}}, "correctness counts drifted")
    require(spec["faults"] == {"profile-mismatch": 1, "simulator-loss": 5, "cancellation": 5, "caller-loss": 5}, "fault counts drifted")
    require(spec["implementation_status"] == {"repository_runner_complete": True, "native_execution_requires_future_coresimulator_attestation": True, "open_blocker": None, "caller_loss_supervisor": "NativeBackend durable lease file and reaper", "caller_loss_substitute_forbidden": "SIGTERM-on-recorded-xcodebuild", "caller_loss_lease_ttl_seconds": 1.0, "caller_loss_heartbeat_seconds": 0.25, "caller_loss_cleanup_grace_seconds": 30.0}, "caller-loss supervisor contract drifted")
    thresholds = spec["thresholds"]
    require(thresholds["warm-workspace-ready"] == {"operator": "strictly-less-than", "p95_seconds": 3.0}, "workspace threshold drifted")
    require(thresholds["simulator-ready-to-install"] == {"operator": "strictly-less-than", "p95_seconds": 15.0}, "simulator threshold drifted")
    require(thresholds["threshold_relaxation_after_results"] is False, "threshold relaxation enabled")

    ledger = load(EXECUTION / "expanded-ledger.json")
    generated = schedule.build_ledger()
    require(ledger == generated, "expanded ledger differs from deterministic generator")
    guard.validate_ledger(ledger)
    operations = ledger["operations"]
    identifiers = [item["id"] for item in operations]
    require(ledger["operation_count"] == 9032, "expanded operation count drifted")
    require(all(set(("namespace", "repetition", "cleanup_action")) <= set(item) for item in operations), "operation scope/cleanup metadata missing")
    require(sum(item["action"] == "record-timing-and-assert-clean-workspace" for item in operations if item["kind"] == "effect") == 30, "warm workspace sample expansion drifted")
    require(sum(item["action"] == "record-timing-and-attest-simulator-identity" for item in operations if item["kind"] == "effect") == 90, "simulator readiness sample expansion drifted")
    ready_samples = [item for item in operations if item.get("action") == "record-timing-and-attest-simulator-identity"]
    require(all(item["parameters"]["timed_operation_ids"][-2:] == [item["parameters"]["identity_operation_id"], item["parameters"]["installation_service_operation_id"]] for item in ready_samples), "simulator readiness omits identity or installation service")
    require(sum(item.get("action") == "attest-live-profile" for item in operations) >= 1, "live profile attestations missing")
    require(sum(item.get("action") == "verify-build-output-manifest" for item in operations) > 0 and sum(item.get("action") == "verify-installed-bundle-identity" for item in operations) > 0, "build/install evidence assertions missing")
    require(sum(item["action"] == "record-build-install-test-timings-and-structured-result" for item in operations if item["kind"] == "effect") == 45, "mobile lifecycle sample expansion drifted")
    require(sum(item["action"] == "assert-zero-cross-namespace-observations" for item in operations if item["kind"] == "effect") == 20, "contamination expansion drifted")
    require(sum(item["action"] == "assert-zero-path-device-lease-or-identity-collision" for item in operations if item["kind"] == "effect") == 10, "two-namespace expansion drifted")
    require(sum(item["action"] == "record-capacity-and-assert-all-hard-gates" for item in operations if item["kind"] == "effect") == 20, "concurrency expansion drifted")
    concurrent_results = [item for item in operations if item.get("action") in {"assert-zero-path-device-lease-or-identity-collision", "record-capacity-and-assert-all-hard-gates"}]
    require(all(len(item["parameters"]["pre_capacity_operation_ids"]) == 3 and len(item["parameters"]["post_capacity_operation_ids"]) == 3 for item in concurrent_results), "concurrent live capacity boundaries drifted")
    require(sum(item["action"] == "assert-lost-session-rejected-and-clean-retry-possible" for item in operations if item["kind"] == "effect") == 5, "simulator-loss expansion drifted")
    require(sum(item["action"] == "signal-recorded-child" for item in operations if item["kind"] == "effect") == 10, "cancellation/caller-loss signal expansion drifted")
    require(sum(item["action"] == "create-supervised-caller-lease" for item in operations if item["kind"] == "effect") == 5, "caller-loss lease creation expansion drifted")
    require(sum(item["action"] == "observe-caller-lease-expiry" for item in operations if item["kind"] == "effect") == 5, "caller-loss expiry expansion drifted")
    require(sum(item["action"] == "verify-caller-loss-reclaim-order-and-deadline" for item in operations if item["kind"] == "effect") == 5, "caller-loss reclaim expansion drifted")
    require(sum(item["action"] == "verify-clean-session-after-caller-loss" for item in operations if item["kind"] == "effect") == 5, "caller-loss retry expansion drifted")
    caller_children = [item for item in operations if item["kind"] == "child-command" and item["phase"] == "fault.caller-loss"]
    require(len(caller_children) == 5 and all(item["argv"][3:] == ["/bin/sleep", "30"] for item in caller_children), "caller-loss child command drifted")
    reclaim_checks = [item for item in operations if item.get("action") == "verify-caller-loss-reclaim-order-and-deadline"]
    require(all(item["parameters"]["expected_events"] == ["lease.heartbeat.missed", "lease.expired", "orphan.detected", "orphan.reclaimed"] and item["parameters"]["cleanup_grace_seconds"] == 30.0 for item in reclaim_checks), "caller-loss W3 order/deadline drifted")
    require(sum(item.get("expected_result") == "failure" for item in operations) == 5, "lost-session rejection commands drifted")
    require(identifiers.index("gate.root-absence") < identifiers.index("attestation.initial.profile.runtime"), "custom set is touched before root-absence gate")
    grouped = [item for item in operations if "parallel_group" in item]
    require(grouped and all(item["kind"] == "command" for item in grouped), "parallel native commands are not explicitly enumerated")
    contamination = [item for item in operations if item.get("action") == "assert-zero-cross-namespace-observations"]
    require(all(item["parameters"]["dimensions"] == ["workspace", "HOME", "TMPDIR", "DerivedData", "installed-app-data", "preferences", "keychain-canary-name", "lease-identifier"] for item in contamination), "contamination dimensions drifted")
    lifecycle = [item for item in operations if item.get("action") == "record-reset-cleanup-timings-and-residue"]
    require(all(item["parameters"]["reset_operation_ids"] and item["parameters"]["cleanup_operation_ids"] and not set(item["parameters"]["reset_operation_ids"]) & set(item["parameters"]["cleanup_operation_ids"]) for item in lifecycle), "reset and cleanup timing boundaries overlap")
    cleanup_samples = [item for item in operations if item.get("action") == "record-cleanup-timing-and-residue"]
    require(len(lifecycle) == len(cleanup_samples) == 45, "independent reset/cleanup samples drifted")
    require(all(set(item["parameters"]["preparation_operation_ids"]).isdisjoint(item["parameters"]["cleanup_operation_ids"]) for item in cleanup_samples), "cleanup preparation overlaps timed cleanup")
    require(identifiers[-1] == "evidence.finalize", "terminal evidence finalization missing")
    emit = next(item for item in operations if item.get("action") == "emit-benchmark-v2-and-decision")
    require(emit["parameters"]["series"] == [[metric, mechanism] for metric, mechanism in schedule.BENCHMARK_SERIES] and emit["parameters"]["adr_edit_forbidden"] is True, "benchmark/decision evidence order drifted")
    require(emit["prerequisites"] == ["cleanup.verify-absence"] and identifiers.index("cleanup.verify-absence") < identifiers.index(emit["id"]) < identifiers.index("evidence.finalize"), "decision emitted before final cleanup")


def verify_no_execution_state() -> None:
    contract = load(EXECUTION / "contract.json")
    mutable_root = Path(contract["mutable_root"])
    evidence_root = REPOSITORY / contract["evidence_root"]
    require(not os.path.lexists(mutable_root), f"mutable root exists during repository verification: {mutable_root}")
    require(not os.path.lexists(evidence_root), f"execution evidence exists before approval: {evidence_root}")
    require(not (PHASE_B / "execution-approval").exists(), "premature execution approval directory exists")


def verify() -> None:
    verify_fileset()
    verify_anchors()
    verify_retained_audit_snapshot()
    verify_contract_and_schedule()
    verify_no_execution_state()


def main() -> int:
    try:
        verify()
    except (KeyError, OSError, json.JSONDecodeError, guard.GuardError, VerificationError) as error:
        print(f"verify-e06-execution: {error}")
        return 1
    print("verify-e06-execution: immutable anchors, 9032-operation schedule, guards, and zero-execution state valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
