#!/usr/bin/env python3
"""Compare completed candidate A outputs; contains no authoring implementation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

EXPERIMENT = Path(__file__).resolve().parents[1]
REPOSITORY = EXPERIMENT.parents[1]
CANDIDATE = EXPERIMENT / "candidates/a-explicit-go"


def fail(message: str) -> None:
    raise SystemExit(f"verify-candidate-a: {message}")


targets = json.loads((EXPERIMENT / "scope/targets.json").read_text(encoding="utf-8"))
names = targets["candidate_output_names"]
for workflow in targets["workflows"]:
    candidate = CANDIDATE / "outputs" / names[workflow["roadmap_workflow"]]
    golden = REPOSITORY / workflow["golden_path"]
    result = subprocess.run(
        ["go", "run", "./cmd/t1conform", "--candidate", str(candidate), "--golden", str(golden)],
        cwd=REPOSITORY / "fixtures/t1-plan-conformance",
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        fail(result.stdout + result.stderr)

effect = json.loads((CANDIDATE / "outputs" / names["effect"]).read_text(encoding="utf-8"))
expected_effect = json.loads((EXPERIMENT / "scope/effect-probe.schema.json").read_text(encoding="utf-8"))
if effect != expected_effect:
    fail("effect output differs from the Phase A probe")

w1 = next(item for item in targets["workflows"] if item["roadmap_workflow"] == "W1")
trace = json.loads((CANDIDATE / "outputs/w1-logical-trace.json").read_text(encoding="utf-8"))
if trace != w1["logical_authoring_shape"]:
    fail("W1 logical trace differs from the Phase A oracle")

for path in CANDIDATE.rglob("*.go"):
    text = path.read_text(encoding="utf-8")
    if "prototype/bootstrap" in text or "fixtures/" in text or "candidates/" in text:
        fail(f"forbidden implementation dependency in {path.relative_to(CANDIDATE)}")

required = [
    CANDIDATE / "evidence/manifest.json",
    CANDIDATE / "evidence/check-summary.json",
    CANDIDATE / "evidence/negative-artifact.log",
    CANDIDATE / "evidence/negative-endpoint.log",
    CANDIDATE / "limitations.md",
]
missing = [str(path.relative_to(CANDIDATE)) for path in required if not path.is_file()]
if missing:
    fail("missing evidence: " + ", ".join(missing))

print("verify-candidate-a: PASS")
