#!/usr/bin/env python3
"""Frozen E03 attack orchestration interface.

Phase A uses only --describe. Execution requires an immutable contract commit
and a Phase B runner which deliberately does not exist in the Phase A tree.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


SCRIPT = Path(__file__).resolve()
EXPERIMENT = SCRIPT.parents[1]
ROOT = SCRIPT.parents[3]
CANDIDATES = ["native", "pooled-container", "helper-vm", "static-descriptor"]
DESCRIPTION = {
    "schema_version": "taskflow-e03-attack-wrapper/v1",
    "candidate_order": CANDIDATES,
    "runner_subcommand": "suite",
    "one_complete_suite_per_candidate": True,
    "per_attempt_seconds_maximum": 2,
    "per_candidate_suite_seconds_maximum": 30,
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
    relative = "experiments/e03-planner-trust/scripts/run_attacks.py"
    expected = {entry["path"]: entry["sha256"] for entry in scope["entries"]}.get(
        relative
    )
    committed = git_bytes(commit, relative)
    if expected != digest(committed):
        raise RuntimeError("contract commit does not bind the attack wrapper bytes")
    if digest(SCRIPT.read_bytes()) != expected:
        raise RuntimeError("live attack wrapper differs from the frozen contract")


def parse_args(argv):
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--describe", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--contract-commit")
    parser.add_argument("--runner")
    parser.add_argument("--out")
    return parser.parse_args(argv)


def execute(args):
    if not args.contract_commit or not args.runner or not args.out:
        raise RuntimeError("--execute requires --contract-commit, --runner, and --out")
    verify_contract_commit(args.contract_commit)
    runner = Path(args.runner).resolve()
    if not runner.is_file() or not os.access(runner, os.X_OK):
        raise RuntimeError("Phase B runner is missing or not executable")
    out = Path(args.out).resolve()
    if out.exists():
        raise RuntimeError("--out must not already exist; attack sets are never overwritten")
    out.mkdir(parents=True)

    protocol = EXPERIMENT / "protocol.json"
    attacks = EXPERIMENT / "attacks.json"
    for candidate in CANDIDATES:
        candidate_out = out / f"{candidate}.json"
        command = [
            str(runner),
            "suite",
            "--candidate",
            candidate,
            "--protocol",
            str(protocol),
            "--attacks",
            str(attacks),
            "--contract-commit",
            args.contract_commit,
            "--output",
            str(candidate_out),
        ]
        subprocess.run(command, cwd=ROOT, check=True, timeout=35)


def main(argv):
    args = parse_args(argv)
    if args.describe:
        print(json.dumps(DESCRIPTION, sort_keys=True, separators=(",", ":")))
        return 0
    try:
        execute(args)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"run_attacks.py: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
