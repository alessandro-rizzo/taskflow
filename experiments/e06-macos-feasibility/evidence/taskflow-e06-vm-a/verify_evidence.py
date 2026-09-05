#!/usr/bin/env python3
"""Verify the terminal E06 VM smoke evidence and negative branch decision."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EXPECTED_ATTEMPTS = {
    "attempt-001": (146, 724, "c7e89d3417f2cd1be24d72909928a3894244a2282f61d8c00585d74a5f28aa03"),
    "attempt-002": (153, 744, "7911622d78c44e4755597a4009039f42795733ba01b2e78bf09b766b02822f38"),
    "attempt-003": (118, 652, "882df5a27fa2d6bdfff04c9c2dbad115a900c7741776801b0ea0bd60512f0473"),
}
BASE_HASHES = {
    "manifest.json": "61f6e857a3d65dd2f8daf9c51c7b837fa458bcc9181ae8556e645b534dab6bf6",
    "config.json": "cf4ace9e40323ec8d0c4b233a3e54bcce28b62a4211f94d7349350a3e726dc03",
    "nvram.bin": "954c8f723cdd1e34567167ebe972f57308833a2cb588535ddefd644d54271f66",
    "disk.img": "39457bd2f67d82eafebca964ca7d6e5ce01e72de64b2ade50d4c96636d07f692",
}
UUID = re.compile(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b")


class EvidenceError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def load(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def verify_checksums() -> None:
    manifest = load("checksums.json")
    require(manifest["format_version"] == "taskflow-e06-vm-evidence-checksums/v1", "checksum format drifted")
    expected = {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.name != "checksums.json"
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
        and "scripts" not in path.relative_to(ROOT).parts
        and "tests" not in path.relative_to(ROOT).parts
    }
    paths = [entry["path"] for entry in manifest["entries"]]
    require(paths == sorted(expected), "checksum fileset mismatch")
    for entry in manifest["entries"]:
        require(hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest() == entry["sha256"], f"checksum mismatch: {entry['path']}")


def verify_sanitized() -> None:
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in {".json", ".md", ".txt", ".py", ".yml"} or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(ROOT)
        if path.name == "verify_evidence.py" or "scripts" in relative.parts or "tests" in relative.parts:
            continue
        text = path.read_text(encoding="utf-8")
        require(UUID.search(text) is None, f"unsanitized device identifier: {path}")
        require("/Users/" not in text.replace("/Users/<redacted>", ""), f"unsanitized user path: {path}")
        require("PRIVATE KEY" not in text and "Authorization: Bearer" not in text, f"credential-like material: {path}")


def verify_attempts() -> None:
    for attempt, (count, kib, digest) in EXPECTED_ATTEMPTS.items():
        summary = load(f"retained/{attempt}/source-summary.json")
        require((summary["source_file_count"], summary["source_du_kib"], summary["source_sha256"]) == (count, kib, digest), f"{attempt}: source summary drifted")
        failure = load(f"retained/{attempt}/failure.json")
        require(failure["status"] == "failed" and failure["benchmark_samples"] == 0, f"{attempt}: failure/sample result drifted")
        cleanup = load(f"retained/{attempt}/cleanup.json")
        require(cleanup["status"] == "absent" and cleanup["duration_seconds"] <= 30, f"{attempt}: clone cleanup was not bounded")
        before = load(f"retained/{attempt}/base-hashes-before.json")
        after = load(f"retained/{attempt}/base-hashes-after.json")
        require(before == after and before == {"hashes": BASE_HASHES, "status": "passed"}, f"{attempt}: immutable base changed")

    first = load("retained/attempt-001/launch.json")
    require(first["exit_code"] == 0 and "TASKFLOW_E06_RESULT:" not in first["stdout"], "attempt one no-result failure not retained")
    initial = load("retained/attempt-002/launch-initial.json")
    persisted = load("retained/attempt-002/launch-persisted.json")
    require('"previous_default":""' in initial["stdout"] and '"previous_file":""' in initial["stdout"], "attempt two initial state drifted")
    require('"previous_default":"taskflow-e06-vm-a-smoke-namespace-a"' in persisted["stdout"], "attempt two defaults did not persist")
    require('"previous_file":"taskflow-e06-vm-a-smoke-namespace-a"' in persisted["stdout"], "attempt two file did not persist")
    require('"previous_keychain_name":""' in persisted["stdout"], "attempt two Keychain failure not retained")

    signing = load("retained/attempt-003/build-signing.json")
    excerpt = "\n".join(signing["build_log_excerpt"])
    require("FAKETEAMID.dev.taskflow.e06.smoke" in excerpt, "intermediate application identifier missing")
    command = next(line for line in signing["build_log_excerpt"] if line.startswith("/usr/bin/codesign --force"))
    require("--entitlements" not in command, "attempt three unexpectedly attached entitlements")
    require(signing["signing_inspection"]["exit_code"] == 0 and signing["signing_inspection"]["stdout"] == "", "attempt three signing inspection drifted")
    third_failure = load("retained/attempt-003/failure.json")
    require(third_failure["error"] == "missing signing entitlements", "attempt three failure drifted")
    require(not (ROOT / "retained/attempt-003/launch.json").exists(), "attempt three must stop before simulator launch")


def verify_setup_receipts() -> None:
    summary = load("retained/setup/source-summary.json")
    require(summary["source_file_count"] == 23 and summary["source_du_kib"] == 136, "setup receipt inventory drifted")
    require(summary["source_sha256"] == "0d2dabb94f8adec914d0c53e1228181f4ed694958d05e130adf02ed271cedadd", "setup receipt digest drifted")
    cleanup = load("retained/setup/cleanup-authorisation.json")
    require(cleanup["state"] == "pending-experiment-completion" and "VM clones" in cleanup["scope"], "cleanup authority receipt drifted")
    preflight = load("retained/setup/preflight-completed.json")
    require(preflight["status"] == "guest-inventory-complete-with-limitations" and preflight["benchmark_samples"] == 0, "guest preflight result drifted")
    require(preflight["dhcp"]["original_bootpd_present"] is False, "original DHCP preference state drifted")
    identity = load("retained/setup/identity-completion.json")
    require(identity["status"] == "complete-not-smoke-approved", "guest identity receipt drifted")
    require(all(value == 0 for value in identity["execution_counts"].values()), "identity completion unexpectedly executed workload")


def verify_decision() -> None:
    result = load("result.json")
    require(result["selected_branch"] == "stop-or-narrow" and result["execution_boundary"] == "terminal-after-three-smoke-attempts", "terminal branch drifted")
    require(result["benchmark_samples"] == 0 and result["threshold_relaxation_after_results"] is False, "threshold/sample claim drifted")
    require(all(item["status"] == "not-reached" for item in result["thresholds"]), "unmeasured thresholds must remain explicit")
    require(result["full_matrix_executed"] is False and result["fourth_smoke_attempt_allowed"] is False, "unsupported execution claim")
    require(result["credential_boundary"]["apple_credentials_used"] is False, "credential boundary drifted")
    cleanup = load("cleanup-result.json")
    require(cleanup["root"]["path"] == "/private/tmp/taskflow-e06-vm-a" and cleanup["root"]["status_after"] == "absent", "cleanup target/result drifted")
    require(cleanup["vm_guard"]["all_stopped"] is True and all(item["state"] == "stopped" for item in cleanup["vm_guard"]["entries"]), "cleanup VM guard drifted")
    require(cleanup["host_preferences"]["action"] == "none" and cleanup["host_preferences"]["bootpd_key_before_cleanup"] == "absent", "cleanup changed host preferences")
    require(cleanup["filesystem"]["available_kib_after"] - cleanup["filesystem"]["available_kib_before"] == cleanup["filesystem"]["reclaimed_bytes"] // 1024, "reclaimed-space arithmetic drifted")
    require(result["cleanup"]["reclaimed_bytes"] == cleanup["filesystem"]["reclaimed_bytes"] and result["cleanup"]["experiment_root_absent"] is True, "result cleanup summary drifted")


def verify() -> None:
    verify_checksums()
    verify_sanitized()
    verify_attempts()
    verify_setup_receipts()
    verify_decision()


if __name__ == "__main__":
    verify()
    print("e06-vm-evidence: passed")
