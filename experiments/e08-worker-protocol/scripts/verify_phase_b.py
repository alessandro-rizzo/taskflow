#!/usr/bin/env python3
"""Verify the immutable Phase A snapshot and approved non-SSH Phase B."""

from __future__ import annotations

import argparse
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
    require(len(measurements) == 8, "expected eight approved local benchmark sets")
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
        require(len(current) == 10, f"expected 2 adapters x 5 repetitions: {case['id']}")
        require({row["adapter"] for row in current} == {"in-process", "macos-e06-stub"}, f"adapter coverage mismatch: {case['id']}")
        for row in current:
            require(row["fault_id"] == case["id"] and row["verdict"] == "pass", f"failed fault row: {case['id']}")
            require(row["ssh_connections"] == 0 and row["external_host_mutations"] == 0, "external action recorded")
            require(row["evidence_method"] in {"executable-core", "typed-core-unit", "state-machine-analysis"}, "unknown evidence strength")
            if row["evidence_method"] == "state-machine-analysis":
                require(row["assertions"]["implemented_transport_fault"] is False, "analysis row masquerades as implementation")
        rows.extend(current)
    require(len(rows) == scorecard["fault_rows"] == 260, "fault row total mismatch")
    analyzed = sum(row["evidence_method"] == "state-machine-analysis" for row in rows)
    require(analyzed == scorecard["state_machine_analysis_only_rows"] and analyzed > 0, "analysis-only limitations missing")


def verify_no_forbidden_adapter_work() -> None:
    source = (EXPERIMENT / "adapters.go").read_text(encoding="utf-8")
    mac = source[source.index("type MacOSStubAdapter"):]
    for token in ("os.", "exec.", "net.", "ssh", "simctl", "xcodebuild"):
        require(token not in mac, f"macOS stub contains forbidden host operation: {token}")
    for path in EXPERIMENT.rglob("*.go"):
        text = path.read_text(encoding="utf-8")
        require('"golang.org/x/crypto/ssh"' not in text and '"net"' not in text, f"network/SSH import forbidden: {path}")
        require("map[string]any" not in text, f"provider option bag forbidden: {path}")
    require(not (EXPERIMENT / "ssh-availability.json").exists(), "unapproved SSH manifest appeared")


def verify_decision(scorecard: dict) -> None:
    require(scorecard["selected_branch"] == "state-machine-first-transport-deferral", "wrong frozen-precedence branch")
    require(scorecard["failed_exercised_rows"] == 0, "local exercised hard gate failed")
    require(scorecard["representative_ssh_linux_evidence"] is False and scorecard["ssh_connections"] == 0, "SSH blocker was misrepresented")
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
    print("E08 Phase A snapshot valid" if args.phase_a_only else "E08 approved non-SSH Phase B evidence valid")


if __name__ == "__main__":
    main()
