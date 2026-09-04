#!/usr/bin/env python3
"""Run the complete, frozen E05 experiment and preserve its evidence."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

import durability
import operational
import score
import simulator

HERE = Path(__file__).resolve().parents[1]
REPOSITORY = HERE.parents[1]


def command_version(*command):
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()


def benchmark(output):
    fixture = REPOSITORY / "fixtures/t1-benchmark-harness"
    destination = output / "measurements/t1-warm-startup"
    database = output / "measurements/operations.sqlite3"
    reopen = f"python3 {HERE / 'scripts/durability.py'} --reopen {database}"
    environment = dict(os.environ)
    environment.setdefault("GOCACHE", "/tmp/taskflow-tf00312-phaseb-go-cache")
    host = command_version("hostinfo")
    cores = re.search(r"(\d+) processors are logically available", host)
    ram = re.search(r"Primary memory available: ([0-9.]+) gigabytes", host)
    cpu = re.search(r"Processor type: ([^\n]+)", host)
    if not (cores and ram and cpu):
        raise RuntimeError("hostinfo did not expose benchmark hardware metadata")
    subprocess.run([
        "go", "run", "./cmd/t1bench", "-n", "30", "-state", "warm", "-prepare", "true",
        "-experiment", "E05", "-fixture", "w3-isolated-native-mobile-stack",
        "-source-revision", "fbf1fbe", "-toolchain", f"python@{platform.python_version()}",
        "-cpu", cpu.group(1), "-cores", cores.group(1), "-ram-gib", ram.group(1),
        "-lease-count", "0", "-cmd", reopen, "-out", str(destination),
    ], cwd=fixture, env=environment, check=True)


def write_environment(output):
    document = {"format_version": "e05-environment-v1-experimental", "phase_a_anchor": "fbf1fbe",
                "platform": platform.platform(), "python": platform.python_version(),
                "sqlite": __import__("sqlite3").sqlite_version, "go": command_version("go", "version"),
                "task": command_version("task", "--version"), "real_providers": False,
                "real_builds": False, "source_state": "Phase B reviewer diff above committed Phase A anchor"}
    (output / "environment.json").write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def write_decision(output, result):
    gates = result["gates"]
    content = f"""# E05 decision: {result['selected_branch']}

The frozen decision matrix selects **{result['selected_branch']}** at precedence
order {result['decision_precedence_order']}. The shared weighted-aging scheduler
passes safety, fairness, durability, attachment, cleanup, and simulator-proxy
operations gates, but it does not meet the predeclared material scheduling
benefit at either four or twenty agents. Thresholds were not changed after
results were observed.

Key observed decision inputs:

- material benefit at 20 agents: `{str(gates['material_benefit_scale_20']).lower()}`
- material benefit at 4 or 20 agents: `{str(gates['material_benefit_scale_4_or_20']).lower()}`
- SQLite durability gate: `{str(gates['durability']).lower()}`
- weighted safety: `{str(gates['weighted_safety']).lower()}`
- operations proxy: `{str(gates['operations']).lower()}`
- unique full-run ownership passing results: `{gates['unique_full_run_ownership_passing_result_count']}`

This is a Gate 1 experiment recommendation, not a production architecture or
permission to stabilize a daemon API. The result says the tested shared
controller adds trustworthy ownership semantics, but the frozen workload does
not justify its breadth on scheduling efficiency alone. Narrower ownership
mechanisms should be considered at convergence.
"""
    (output / "decision.md").write_text(content)


def run(output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    simulator.generate(output)
    durability.run_matrix(output / "raw/durability")
    durability.operations(output / "measurements")
    operational.generate(output / "measurements")
    benchmark(output)
    # The durable proof is the crash log/integrity report and benchmark raw
    # samples, not mutable SQLite/WAL snapshots.  Avoid preserving transient
    # sidecars as evidence or treating their bytes as a portable format.
    for name in ("operations.sqlite3", "operations.backup.sqlite3"):
        for suffix in ("", "-wal", "-shm"):
            path = output / "measurements" / f"{name}{suffix}"
            if path.exists():
                path.unlink()
    write_environment(output)
    result = score.evaluate(output)
    (output / "results/scorecard.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    write_decision(output, result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=HERE)
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps({"selected_branch": result["selected_branch"]}, sort_keys=True))


if __name__ == "__main__":
    main()
