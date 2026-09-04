#!/usr/bin/env python3
"""Verify that ADR 0006 records the manifest-bound E02 decision faithfully."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT = ROOT / "experiments/e02-plan-ir"
ADR = ROOT / "docs/decisions/0006-e02-plan-ir.md"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit("verify-e02-decision: " + message)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def section(document: str, heading: str) -> str:
    marker = "## " + heading
    require(marker in document, "ADR missing " + marker)
    body = document.split(marker, 1)[1]
    return body.split("\n## ", 1)[0]


def main() -> None:
    scorecard = load(EXPERIMENT / "evidence/scorecard.json")
    require(scorecard["decision"] == "continue-canonical-json", "scorecard branch changed")
    require(all(scorecard["checks"].values()), "one or more compact scorecard gates failed")
    require(
        scorecard["contract_commit"] == "6b98cada25439f66c75eaf3f5faea3d01dfdfade",
        "scorecard contract anchor changed",
    )

    document = ADR.read_text(encoding="utf-8")
    for field in (
        "Question:",
        "Decision date:",
        "## Options considered",
        "## Predeclared thresholds",
        "## Evidence and raw-result locations",
        "## Decision",
        "## Consequences and deliberately unsupported cases",
        "## Trigger for revisiting this decision",
        "## Contracts now allowed to stabilize",
    ):
        require(field in document, "ADR missing " + field)

    require("Status: proposed" in document or "Status: accepted" in document, "ADR status invalid")
    require("**Continue with canonical JSON.**" in section(document, "Decision"), "ADR branch differs from scorecard")

    records = {
        name: load(EXPERIMENT / "evidence/raw/benchmarks" / name / "record.json")
        for name in (
            "w1-plan",
            "large-generation-canonicalization",
            "large-reader-validation-digest",
        )
    }
    large = load(EXPERIMENT / "evidence/raw/benchmarks/large-graph.json")
    expected_results = (
        f"p95 {records['w1-plan']['p95'] * 1000:.3f} ms",
        f"p95 {records['large-generation-canonicalization']['p95'] * 1000:.3f} ms",
        f"p95 {records['large-reader-validation-digest']['p95'] * 1000:.3f} ms",
        f"{large['canonical_bytes']:,} bytes",
    )
    for result in expected_results:
        require(result in document, "ADR does not cite retained result " + result)

    contracts = section(document, "Contracts now allowed to stabilize")
    require("\n\nNone." in contracts, "ADR stabilizes a contract prematurely")
    require("Gate 1 inputs only" in contracts, "ADR does not limit proposed concepts to Gate 1")
    require("No production plan encoding" in contracts, "ADR omits the production-format boundary")
    print("verify-e02-decision: PASS branch=continue-canonical-json contracts=none")


if __name__ == "__main__":
    main()
