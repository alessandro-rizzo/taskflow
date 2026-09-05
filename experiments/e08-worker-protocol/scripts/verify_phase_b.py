#!/usr/bin/env python3
"""Verify the immutable Phase A snapshot and approved non-SSH Phase B."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import math
import subprocess
import tempfile
from pathlib import Path


EXPERIMENT = Path(__file__).resolve().parents[1]
REPOSITORY = EXPERIMENT.parents[1]
PHASE_A_COMMIT = "fe41c6428c4d7d432cdd463c82dd12c3465e1103"
PHASE_A_FILES = {
    "README.md", "Taskfile.yml", "contract.json", "decision-matrix.json",
    "envelopes.schema.json", "fault-matrix.json", "fixture-bindings.json",
    "frozen-artifacts.json", "protocol.sha256", "scripts/verify_contract.py",
    "ssh-availability-manifest.schema.json", "state-machines.json",
    "tests/test_verify_contract.py", "thresholds.json",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path} is not an object")
    return value


def git_bytes(relative: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{PHASE_A_COMMIT}:experiments/e08-worker-protocol/{relative}"], cwd=REPOSITORY)


def verify_phase_a_snapshot() -> None:
    for relative in sorted(PHASE_A_FILES):
        require((EXPERIMENT / relative).read_bytes() == git_bytes(relative), f"Phase A file changed after commit: {relative}")
    with tempfile.TemporaryDirectory(prefix="taskflow-e08-phase-a-") as name:
        frozen = Path(name) / "experiments/e08-worker-protocol"
        for relative in PHASE_A_FILES:
            target = frozen / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(git_bytes(relative))
        module_path = frozen / "scripts/verify_contract.py"
        spec = importlib.util.spec_from_file_location("e08_phase_a_verifier", module_path)
        require(spec is not None and spec.loader is not None, "cannot load Phase A verifier")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.verify(frozen, REPOSITORY)


def verify_manifest(path: Path) -> dict:
    manifest = load(path)
    files = manifest.get("files", [])
    require(files and [item["path"] for item in files] == sorted(item["path"] for item in files), f"unordered or empty manifest: {path}")
    for item in files:
        require(sha256(EXPERIMENT / item["path"]) == item["sha256"], f"manifest mismatch: {item['path']}")
    return manifest


def nearest_rank_p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[round(0.95 * (len(ordered) - 1))]


def verify_benchmarks(scorecard: dict) -> None:
    thresholds = load(EXPERIMENT / "thresholds.json")
    frozen = {item["id"]: item for item in thresholds["timing_metrics"]}
    measurements = scorecard["measurements"]
    require(len(measurements) == 13, "expected thirteen three-shape benchmark sets")
    for item in measurements:
        record = load(EXPERIMENT / item["record"])
        metric = frozen[item["metric"]]
        require(record["schema_version"] == "taskflow-t1-benchmark/v2", "benchmark schema drifted")
        require(record["sample_count"] == metric["sample_count"] == len(record["samples"]), f"sample count mismatch: {item['record']}")
        require(math.isclose(record["p95"], nearest_rank_p95(record["samples"]), rel_tol=0, abs_tol=1e-12), f"p95 mismatch: {item['record']}")
        if item["metric"] == "ready-result-hit":
            require(record["state"] == "cache-hit" and record["reservation_count"] == 0, "cache-hit benchmark performed reservation")
        observed = (max(record["samples"]) if metric["statistic"] == "maximum" else record["p95"]) * 1000
        limit = metric["threshold"]["milliseconds"]
        passed = observed < limit if metric["threshold"]["operator"] == "strictly-less-than" else observed <= limit
        require(passed and item["passed"], f"frozen threshold failed: {item['adapter']}/{item['metric']}")


def verify_faults(scorecard: dict) -> None:
    matrix = load(EXPERIMENT / "fault-matrix.json")
    rows = []
    for case in matrix["cases"]:
        path = EXPERIMENT / case["raw_trace"]
        current = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        ssh_path = EXPERIMENT / "evidence/ssh-linux/raw" / f"{case['id']}.jsonl"
        ssh = [json.loads(line) for line in ssh_path.read_text(encoding="utf-8").splitlines() if line]
        require(len(current) == 10 and len(ssh) == 5, f"expected 3 adapters x 5 repetitions: {case['id']}")
        require({row["adapter"] for row in current} == {"in-process", "macos-e06-stub"}, f"adapter coverage mismatch: {case['id']}")
        for row in current:
            require(row["fault_id"] == case["id"] and row["verdict"] == "pass", f"failed fault row: {case['id']}")
            require(row["ssh_connections"] == 0 and row["external_host_mutations"] == 0, "external action recorded")
            require(row["evidence_method"] in {"executable-core", "typed-core-unit", "state-machine-analysis"}, "unknown evidence strength")
            if row["evidence_method"] == "state-machine-analysis":
                require(row["assertions"]["implemented_transport_fault"] is False, "analysis row masquerades as implementation")
        rows.extend(current)
        for row in ssh:
            require(row["adapter"] == "ssh-linux" and row["fault_id"] == case["id"] and row["verdict"] == "pass", f"failed SSH row: {case['id']}")
            require(row["evidence_method"] in {"actual-openssh-boundary-reconnect", "actual-openssh-linux", "actual-openssh-plus-local-allowlist", "actual-openssh-two-worker-identities", "executable-core-no-ssh", "state-machine-analysis-local-linux", "typed-core-no-ssh", "typed-core-unit"}, "unknown SSH evidence strength")
        rows.extend(ssh)
    require(len(rows) == scorecard["fault_rows"] == 390, "fault row total mismatch")
    analyzed = sum(row["evidence_method"].startswith("state-machine-analysis") for row in rows)
    require(analyzed == scorecard["state_machine_analysis_only_rows"] and analyzed > 0, "analysis-only limitations missing")


def verify_no_forbidden_adapter_work() -> None:
    source = (EXPERIMENT / "adapters.go").read_text(encoding="utf-8")
    mac = source[source.index("type MacOSStubAdapter"):]
    for token in ("os.", "exec.", "net.", "ssh", "simctl", "xcodebuild"):
        require(token not in mac, f"macOS stub contains forbidden host operation: {token}")
    for path in EXPERIMENT.rglob("*.go"):
        text = path.read_text(encoding="utf-8")
        require('"golang.org/x/crypto/ssh"' not in text, f"embedded SSH implementation forbidden: {path}")
        if '"net"' in text:
            require(path.relative_to(EXPERIMENT).as_posix() == "cmd/e08worker/main.go", f"network import outside worker proxy: {path}")
        require("map[string]any" not in text, f"provider option bag forbidden: {path}")
    manifest = load(EXPERIMENT / "ssh-availability.json")
    require(set(manifest) == {"format_version", "manifest_id", "endpoint", "identity", "profile", "remote_scope", "capacity", "commands", "fault_scope", "cleanup", "evidence", "approval"}, "SSH manifest is not closed")
    require(manifest["format_version"] == "taskflow-e08-ssh-availability-manifest/v1-experimental", "SSH manifest version drifted")
    require(manifest["endpoint"]["host"] == "127.0.0.1" and manifest["endpoint"]["port"] == 22216, "SSH endpoint drifted")
    require(manifest["endpoint"]["strict_host_key_checking"] is True, "strict host checking disabled")
    require(manifest["endpoint"]["host_key_algorithm"] == "ssh-ed25519", "host-key algorithm drifted")
    known_hosts = (REPOSITORY / manifest["endpoint"]["known_hosts_path"]).read_text(encoding="utf-8").strip().split()
    require(known_hosts[:2] == ["[127.0.0.1]:22216", "ssh-ed25519"] and len(known_hosts) == 3, "known-host entry drifted")
    fingerprint = base64.b64encode(hashlib.sha256(base64.b64decode(known_hosts[2])).digest()).decode().rstrip("=")
    require(manifest["endpoint"]["host_key_sha256"] == "SHA256:" + fingerprint, "known-host fingerprint mismatch")
    identity = manifest["identity"]
    require(identity["user"] == "e08worker" and identity["credential_mediator"] == "experiment-owned-ed25519-key-wrapper", "SSH identity drifted")
    require(all(identity[key] is True for key in ("ambient_ssh_config_forbidden", "ambient_agent_forbidden", "interactive_prompts_forbidden", "forwarding_forbidden")), "ambient SSH authority enabled")
    require(manifest["remote_scope"]["root"] == "/config/taskflow-e08-ssh-linux", "remote ownership drifted")
    require(all(manifest["remote_scope"][key] is True for key in ("shared_root_forbidden", "sudo_forbidden", "installation_forbidden")), "remote safety boundary drifted")
    profile = load(EXPERIMENT / "approved/ssh-profile.json")
    profile_digest = "sha256:" + hashlib.sha256(json.dumps(profile, separators=(",", ":")).encode()).hexdigest()
    require(manifest["profile"]["linux_profile_digest"] == profile_digest, "SSH profile digest drifted")
    require(manifest["profile"]["runner_digest"] == profile["runner_digest"] and manifest["profile"]["os"] == "linux" and manifest["profile"]["architecture"] == "aarch64", "SSH runner/profile fields drifted")
    require(manifest["commands"]["allowlist"] == [["e08-w2"]] and manifest["commands"]["shell_startup_forbidden"] is True, "SSH command allowlist drifted")
    require(manifest["capacity"]["max_concurrent_attempts"] == 1 and manifest["capacity"]["exclusive_paths"] is True, "SSH capacity scope drifted")
    require(all(manifest["cleanup"][key] is True for key in ("broad_process_kill_forbidden", "outside_allowlist_forbidden")), "cleanup scope widened")
    require(manifest["evidence"]["credential_values_forbidden"] is True, "credential evidence allowed")
    require(manifest["approval"]["exact_network_and_mutations_approved"] is True and manifest["approval"]["phase_a_approval_is_not_execution_approval"] is True, "SSH approval missing")
    cleanup = load(EXPERIMENT / "evidence/ssh-linux/cleanup-result.json")
    require(cleanup["status"] == "complete" and cleanup["owned_root_absent_after_cleanup"] is True and cleanup["run_created_cache_absent_after_cleanup"] is True, "SSH cleanup incomplete")
    require(cleanup["listener_127_0_0_1_22216_closed"] is True and cleanup["named_worker_processes_absent"] is True, "SSH resource remained live")
    require(cleanup["private_keys_retained"] is False and cleanup["pre_existing_default_profile_deleted"] is False, "cleanup crossed ownership boundary")


def verify_decision(scorecard: dict) -> None:
    require(scorecard["selected_branch"] == "state-machine-first-transport-deferral", "wrong frozen-precedence branch")
    require(scorecard["failed_exercised_rows"] == 0, "local exercised hard gate failed")
    require(scorecard["representative_ssh_linux_evidence"] is True and scorecard["ssh_connections"] > 0, "SSH evidence missing")
    require(scorecard["external_remote_host_evidence"] is False and scorecard["local_linux_vm_transport_only"] is True, "locality limitation missing")
    require(scorecard["transport_frozen"] is False and scorecard["production_contract_allowed_to_stabilize"] is False, "experimental boundary drifted")
    decision = (REPOSITORY / "docs/decisions/0012-e08-worker-protocol.md").read_text(encoding="utf-8")
    require("state-machine-first transport deferral" in decision.lower(), "ADR does not match scorecard")
    require("No production contract" in decision, "ADR stabilizes production contract")


def verify_phase_b() -> None:
    implementation = verify_manifest(EXPERIMENT / "evidence/implementation-manifest.json")
    require(implementation["phase_a_commit"] == PHASE_A_COMMIT, "implementation not bound to Phase A")
    verify_manifest(EXPERIMENT / "evidence/manifest.json")
    scorecard = load(EXPERIMENT / "evidence/scorecard.json")
    verify_benchmarks(scorecard)
    verify_faults(scorecard)
    verify_no_forbidden_adapter_work()
    verify_decision(scorecard)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-a-only", action="store_true")
    args = parser.parse_args()
    verify_phase_a_snapshot()
    if not args.phase_a_only:
        verify_phase_b()
    print("E08 Phase A snapshot valid" if args.phase_a_only else "E08 three-shape Phase B evidence valid")


if __name__ == "__main__":
    main()
