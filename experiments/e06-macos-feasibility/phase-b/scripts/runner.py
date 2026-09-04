#!/usr/bin/env python3
"""Describe the frozen E06 Phase-B runner; execution is intentionally absent."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import guard


PHASE_B = Path(__file__).resolve().parents[1]


def describe() -> dict[str, object]:
    validated = guard.validate(PHASE_B)
    ledger_path = PHASE_B / "command-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    return {
        "format_version": "taskflow-e06-runner-description/v1-experimental",
        "candidate": validated["candidate"],
        "command_ids": [command["id"] for command in ledger["commands"]],
        "command_ledger_sha256": hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
        "execution_allowed": False,
        "reason": "repository-only preparation; approved execution manifest absent"
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--describe", action="store_true")
    args = parser.parse_args()
    if not args.describe:
        parser.error("repository-only runner supports --describe only")
    print(json.dumps(describe(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
