#!/usr/bin/env python3
"""Verify immutable Phase A at fbf1fbe and the live Phase B evidence."""

from __future__ import annotations

import gzip
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import durability
import score as scoring
import simulator

HERE = Path(__file__).resolve().parents[1]
REPOSITORY = HERE.parents[1]
PHASE_A_COMMIT = "fbf1fbe"
FROZEN_LIVE = ("contract.json", "workload.json", "policies.json", "thresholds.json",
               "fixture-bindings.json", "decision-matrix.json", "frozen-artifacts.json", "protocol.sha256",
               "scripts/verify_contract.py", "tests/test_verify_contract.py")


def git_bytes(relative):
    return subprocess.check_output(["git", "show", f"{PHASE_A_COMMIT}:experiments/e05-daemon-simulation/{relative}"],
                                   cwd=REPOSITORY)


def verify_phase_a_snapshot(errors):
    with tempfile.TemporaryDirectory(prefix="e05-phase-a-") as temporary:
        root = Path(temporary)
        paths = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", PHASE_A_COMMIT, "experiments/e05-daemon-simulation"],
            cwd=REPOSITORY, text=True).splitlines()
        fixture_paths = [entry["path"] for entry in json.loads(git_bytes("fixture-bindings.json"))["bindings"]]
        for relative in paths + fixture_paths:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(subprocess.check_output(["git", "show", f"{PHASE_A_COMMIT}:{relative}"], cwd=REPOSITORY))
        experiment = root / "experiments/e05-daemon-simulation"
        result = subprocess.run([sys.executable, str(experiment / "scripts/verify_contract.py"),
                                 "--experiment-root", str(experiment), "--repository-root", str(root)],
                                capture_output=True, text=True)
        if result.returncode:
            errors.append("immutable Phase A snapshot failed verification: " + result.stderr.strip())
    for relative in FROZEN_LIVE:
        if (HERE / relative).read_bytes() != git_bytes(relative):
            errors.append(f"frozen live artifact differs from {PHASE_A_COMMIT}: {relative}")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_trace_files(root, errors):
    checksums = json.loads((root / "raw/checksums.json").read_text())
    if len(checksums.get("files", {})) != 18:
        errors.append("raw/checksums.json must bind 18 trace files")
    for relative, expected in checksums.get("files", {}).items():
        path = root / relative
        if not path.is_file() or sha(path) != expected:
            errors.append(f"trace checksum mismatch: {relative}")
            continue
        sequences = {}
        with gzip.open(path, "rt") as stream:
            for line in stream:
                row = json.loads(line)
                key = (row["mode"], row["scale"], row["seed"])
                sequences.setdefault(key, []).append(row["sequence"])
        if any(values != list(range(1, len(values) + 1)) for values in sequences.values()):
            errors.append(f"trace sequence gap or reorder: {relative}")


def verify_evidence(root, errors):
    required = ["results/simulation-metrics.json", "results/lifecycle.json", "results/scorecard.json",
                "raw/durability/crash-cases.jsonl", "raw/durability/summary.json",
                "measurements/sqlite-operations.json", "measurements/operational-proxy.json",
                "measurements/t1-warm-startup/record.json", "measurements/t1-warm-startup/samples.txt",
                "environment.json", "decision.md", "limitations.md", "operational-complexity.md"]
    for relative in required:
        if not (root / relative).is_file():
            errors.append(f"missing Phase B evidence: {relative}")
    if errors:
        return
    runs = json.loads((root / "results/simulation-metrics.json").read_text())["runs"]
    if len(runs) != 540:
        errors.append("simulation metrics must contain 6 modes x 3 scales x 30 seeds")
    unsafe = [run for run in runs if run["mode"] == "independent-unguarded-negative-control"]
    guarded = [run for run in runs if run["mode"] != "independent-unguarded-negative-control"]
    if not unsafe or sum(run["capacity_violation_count"] for run in unsafe) == 0:
        errors.append("unsafe negative control did not demonstrate oversubscription")
    if any(run["capacity_violation_count"] or run["active_lease_count_at_drain"] for run in guarded):
        errors.append("a non-negative scheduler violated capacity or leaked a lease")
    durability_result = json.loads((root / "raw/durability/summary.json").read_text())
    if durability_result["fresh_process_case_count"] != 60:
        errors.append("durability matrix does not contain 60 fresh-process cases")
    for key, value in durability_result.items():
        if key.endswith("_count") and key != "fresh_process_case_count" and value != 0:
            errors.append(f"durability hard gate failed: {key}={value}")
    scorecard = json.loads((root / "results/scorecard.json").read_text())
    if scorecard.get("selected_branch") not in {"stronger-state-model", "stop", "full-daemon",
                                             "on-demand-daemon", "broker-only", "stop-narrow"}:
        errors.append("scorecard selected branch is not in frozen decision matrix")
    recomputed = scoring.evaluate(root)
    if scorecard != recomputed:
        errors.append("scorecard or selected branch does not follow the frozen evidence and decision matrix")
    if f"E05 decision: {scorecard.get('selected_branch')}" not in (root / "decision.md").read_text():
        errors.append("decision.md does not report the mechanically selected scorecard branch")
    t1 = json.loads((root / "measurements/t1-warm-startup/record.json").read_text())
    if t1.get("experiment_id") != "E05" or t1.get("sample_count") != 30 or t1.get("p95", 1) > .25:
        errors.append("T1 benchmark-v2 warm-start record is incomplete or above threshold")


def compare_deterministic(root, errors):
    with tempfile.TemporaryDirectory(prefix="e05-regenerate-") as temporary:
        generated = Path(temporary)
        simulator.generate(generated)
        durability.run_matrix(generated / "raw/durability")
        relatives = ["raw/checksums.json", "results/simulation-metrics.json", "results/lifecycle.json",
                     "raw/durability/crash-cases.jsonl", "raw/durability/summary.json"]
        relatives += list(json.loads((generated / "raw/checksums.json").read_text())["files"])
        for relative in relatives:
            if not (root / relative).is_file() or (root / relative).read_bytes() != (generated / relative).read_bytes():
                errors.append(f"deterministic evidence drift: {relative}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-a-only", action="store_true")
    args = parser.parse_args()
    errors = []
    verify_phase_a_snapshot(errors)
    if args.phase_a_only:
        if errors:
            for error in errors:
                print("ERROR:", error, file=sys.stderr)
            return 1
        print(f"E05 immutable Phase A snapshot verified at {PHASE_A_COMMIT}.")
        return 0
    verify_trace_files(HERE, errors)
    verify_evidence(HERE, errors)
    if not errors:
        compare_deterministic(HERE, errors)
    if errors:
        for error in errors:
            print("ERROR:", error, file=sys.stderr)
        return 1
    print(f"E05 Phase B verified; immutable Phase A anchor {PHASE_A_COMMIT}; deterministic evidence reproduced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
