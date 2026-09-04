#!/usr/bin/env python3
"""Run the frozen E02 benchmark sets in their predeclared order."""

from __future__ import annotations

import argparse
import hashlib
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Sequence


REPOSITORY = Path(__file__).resolve().parents[3]
WRAPPER_PATH = "experiments/e02-plan-ir/scripts/run_benchmarks.py"


def fail(message: str) -> None:
    raise SystemExit("e02-benchmarks: " + message)


def existing_file(raw: str, label: str) -> Path:
    path = Path(raw).resolve()
    if not path.is_file():
        fail(f"{label} is not a file: {path}")
    return path


def verify_contract_binding(revision: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        fail("--contract-commit must be a full lowercase Git commit")
    result = subprocess.run(
        ["git", "show", f"{revision}:{WRAPPER_PATH}"],
        cwd=REPOSITORY,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        fail("cannot read the wrapper from --contract-commit")
    live = (REPOSITORY / WRAPPER_PATH).read_bytes()
    if hashlib.sha256(result.stdout).digest() != hashlib.sha256(live).digest():
        fail("live wrapper bytes differ from --contract-commit")


def timed_command(parts: Sequence[str]) -> str:
    return shlex.join(parts) + " >/dev/null"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-commit", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--reader", required=True)
    parser.add_argument("--large-plan", required=True)
    parser.add_argument("--benchmark-runner", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--cpu", required=True)
    parser.add_argument("--cores", type=int, required=True)
    parser.add_argument("--ram-gib", type=float, required=True)
    parser.add_argument("--os-name", required=True)
    parser.add_argument("--os-version", required=True)
    parser.add_argument("--os-build", required=True)
    parser.add_argument("--os-arch", required=True)
    parser.add_argument("--python-version", required=True)
    args = parser.parse_args()

    verify_contract_binding(args.contract_commit)
    candidate = existing_file(args.candidate, "candidate")
    reader = existing_file(args.reader, "reader")
    large_plan = existing_file(args.large_plan, "large plan")
    benchmark_runner = existing_file(args.benchmark_runner, "benchmark runner")
    if args.cores <= 0 or args.ram_gib <= 0:
        fail("machine core and RAM values must be positive")
    for value, label in (
        (args.cpu, "CPU"),
        (args.os_name, "OS name"),
        (args.os_version, "OS version"),
        (args.os_build, "OS build"),
        (args.os_arch, "OS architecture"),
        (args.python_version, "Python version"),
    ):
        if not value.strip():
            fail(f"{label} must be non-empty")

    common = [
        "--state", "warm",
        "--prepare", "true",
        "--experiment", "E02",
        "--source-revision", args.contract_commit,
        "--cpu", args.cpu,
        "--cores", str(args.cores),
        "--ram-gib", str(args.ram_gib),
        "--os-name", args.os_name,
        "--os-version", args.os_version,
        "--os-build", args.os_build,
        "--os-arch", args.os_arch,
        "--cache-dim", "candidate-binary=prebuilt",
        "--cache-dim", "gocache=warm",
        "--toolchain", "python@" + args.python_version,
    ]
    output_root = Path(args.output_root).resolve()
    cases = (
        ("w1-plan", "w1-fast-project-check", 30,
         timed_command([str(candidate), "generate", "--fixture", "w1", "--canonical"])),
        ("large-generation-canonicalization", "large-graph", 15,
         timed_command([str(candidate), "generate", "--fixture", "large", "--nodes", "10000", "--canonical"])),
        ("large-reader-validation-digest", "large-graph", 15,
         timed_command([sys.executable, str(reader), "digest", "--input", str(large_plan)])),
    )
    for identifier, fixture, samples, command in cases:
        subprocess.run(
            [str(benchmark_runner), "--cmd", command, "--n", str(samples),
             "--fixture", fixture, "--out", str(output_root / identifier), *common],
            cwd=REPOSITORY,
            check=True,
        )


if __name__ == "__main__":
    main()
