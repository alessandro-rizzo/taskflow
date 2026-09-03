#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import subprocess
import sys


SCRIPT = Path(__file__).resolve()
MEASUREMENTS = SCRIPT.parents[1]
ROOT = SCRIPT.parents[4]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"verify-results: {message}")


def main() -> None:
    subprocess.run([sys.executable, str(MEASUREMENTS / "scripts/verify_protocol.py")], check=True)
    subprocess.run([sys.executable, str(ROOT / "experiments/e01-authoring-schema/agent-trials/scripts/verify_trials.py")], check=True)
    before_scorecard = (MEASUREMENTS / "scorecard.json").read_bytes()
    before_manifest = (MEASUREMENTS / "evidence-manifest.json").read_bytes()
    subprocess.run([sys.executable, str(MEASUREMENTS / "scripts/finalize_results.py")], check=True)
    require((MEASUREMENTS / "scorecard.json").read_bytes() == before_scorecard, "scorecard is not reproducible")
    require((MEASUREMENTS / "evidence-manifest.json").read_bytes() == before_manifest, "evidence manifest is not reproducible")
    scorecard = json.loads(before_scorecard)
    require(scorecard["chosen_branch"] == "B-wins", "branch is not B-wins")
    require(scorecard["contracts_stabilized_now"] == [], "E01 stabilized a contract prematurely")
    adr = (ROOT / "docs/decisions/0005-e01-authoring-schema.md").read_text()
    for heading in (
        "Question:", "Decision date:", "## Options considered", "## Predeclared thresholds",
        "## Evidence and raw-result locations", "## Decision", "## Consequences and deliberately unsupported cases",
        "## Trigger for revisiting this decision", "## Contracts now allowed to stabilize",
    ):
        require(heading in adr, f"ADR missing {heading}")
    require("**B wins.**" in adr, "ADR branch differs from scorecard")
    require("Status: proposed" in adr or "Status: accepted" in adr, "ADR status")
    require(hashlib.sha256((MEASUREMENTS / "protocol.json").read_bytes()).hexdigest() == scorecard["protocol_sha256"], "protocol binding")
    print("verify-results: PASS")


if __name__ == "__main__":
    main()
