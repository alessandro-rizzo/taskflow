#!/usr/bin/env python3
"""Frozen E03 warm-planning benchmark orchestration interface.

Phase A uses only --describe. Phase B may benchmark only candidates whose
complete correctness suite has already produced a scorecard.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys


SCRIPT = Path(__file__).resolve()
EXPERIMENT = SCRIPT.parents[1]
ROOT = SCRIPT.parents[3]
CANDIDATES = ["native", "pooled-container", "helper-vm", "static-descriptor"]
DESCRIPTION = {
    "schema_version": "taskflow-e03-benchmark-wrapper/v1",
    "candidate_order": CANDIDATES,
    "samples_per_exercised_candidate": 30,
    "state": "warm",
    "prepare_before_every_sample": "true",
    "p95_seconds_exclusive": 0.25,
    "timed_boundary": "immutable inputs ready through independent acceptance",
    "concurrent_measurement_allowed": False,
    "phase_a_execution_allowed": False,
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git_bytes(commit, relative_path):
    proc = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"cannot read {relative_path} from contract commit {commit}: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc.stdout


def verify_contract_commit(commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("--contract-commit must be a full lowercase 40-character SHA")
    protocol_bytes = git_bytes(commit, "experiments/e03-planner-trust/protocol.json")
    recorded = git_bytes(
        commit, "experiments/e03-planner-trust/protocol.sha256"
    ).decode("ascii").strip()
    if recorded != digest(protocol_bytes):
        raise RuntimeError("contract commit protocol checksum is invalid")
    scope = json.loads(
        git_bytes(commit, "experiments/e03-planner-trust/scope-hashes.json")
    )
    relative = "experiments/e03-planner-trust/scripts/run_benchmarks.py"
    expected = {entry["path"]: entry["sha256"] for entry in scope["entries"]}.get(
        relative
    )
    committed = git_bytes(commit, relative)
    if expected != digest(committed):
        raise RuntimeError("contract commit does not bind the benchmark wrapper bytes")
    if digest(SCRIPT.read_bytes()) != expected:
        raise RuntimeError("live benchmark wrapper differs from the frozen contract")


def parse_args(argv):
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--describe", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--contract-commit")
    parser.add_argument("--runner")
    parser.add_argument("--benchmark-binary")
    parser.add_argument("--attack-scorecard")
    parser.add_argument("--out")
    parser.add_argument("--candidate", action="append", choices=CANDIDATES)
    parser.add_argument("--cpu")
    parser.add_argument("--cores", type=int)
    parser.add_argument("--ram-gib", type=float)
    parser.add_argument("--os-name")
    parser.add_argument("--os-version")
    parser.add_argument("--os-build")
    parser.add_argument("--os-arch")
    return parser.parse_args(argv)


def validate_candidate_order(candidates):
    if not candidates:
        raise RuntimeError("at least one --candidate is required")
    if len(set(candidates)) != len(candidates):
        raise RuntimeError("--candidate values must be unique")
    indexes = [CANDIDATES.index(candidate) for candidate in candidates]
    if indexes != sorted(indexes):
        raise RuntimeError("candidates must follow the frozen candidate order")


def required_metadata(args):
    names = [
        "cpu",
        "cores",
        "ram_gib",
        "os_name",
        "os_version",
        "os_build",
        "os_arch",
    ]
    missing = [name.replace("_", "-") for name in names if not getattr(args, name)]
    if missing:
        raise RuntimeError("missing explicit machine metadata: " + ", ".join(missing))


def execute(args):
    needed = [
        args.contract_commit,
        args.runner,
        args.benchmark_binary,
        args.attack_scorecard,
        args.out,
    ]
    if any(value is None for value in needed):
        raise RuntimeError(
            "--execute requires contract, runner, benchmark, attack scorecard, and output arguments"
        )
    verify_contract_commit(args.contract_commit)
    validate_candidate_order(args.candidate)
    required_metadata(args)

    runner = Path(args.runner).resolve()
    benchmark = Path(args.benchmark_binary).resolve()
    scorecard = Path(args.attack_scorecard).resolve()
    for path, label in [(runner, "runner"), (benchmark, "benchmark binary")]:
        if not path.is_file() or not os.access(path, os.X_OK):
            raise RuntimeError(f"Phase B {label} is missing or not executable")
    if not scorecard.is_file():
        raise RuntimeError("attack scorecard is missing")
    out = Path(args.out).resolve()
    if out.exists():
        raise RuntimeError("--out must not already exist; benchmark sets are never overwritten")
    out.mkdir(parents=True)

    for candidate in args.candidate:
        timed = shlex.join(
            [
                str(runner),
                "plan",
                "--candidate",
                candidate,
                "--protocol",
                str(EXPERIMENT / "protocol.json"),
                "--attack-scorecard",
                str(scorecard),
                "--contract-commit",
                args.contract_commit,
                "--output",
                "/dev/null",
            ]
        )
        command = [
            str(benchmark),
            "--cmd",
            timed,
            "--n",
            "30",
            "--state",
            "warm",
            "--prepare",
            "true",
            "--experiment",
            "E03",
            "--fixture",
            "w1-fast-project-check",
            "--source-revision",
            args.contract_commit,
            "--out",
            str(out / candidate),
            "--cpu",
            args.cpu,
            "--cores",
            str(args.cores),
            "--ram-gib",
            str(args.ram_gib),
            "--os-name",
            args.os_name,
            "--os-version",
            args.os_version,
            "--os-build",
            args.os_build,
            "--os-arch",
            args.os_arch,
            "--cache-dim",
            "driver=prebuilt",
            "--cache-dim",
            f"candidate={candidate}",
            "--toolchain",
            "python@3.9.6",
        ]
        subprocess.run(command, cwd=ROOT, check=True)


def main(argv):
    args = parse_args(argv)
    if args.describe:
        print(json.dumps(DESCRIPTION, sort_keys=True, separators=(",", ":")))
        return 0
    try:
        execute(args)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"run_benchmarks.py: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
