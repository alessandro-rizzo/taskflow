#!/usr/bin/env python3
"""Compare completed D outputs; contains no authoring implementation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

EXPERIMENT = Path(__file__).resolve().parents[1]
REPOSITORY = EXPERIMENT.parents[1]
CANDIDATES = {
    "A": EXPERIMENT / "candidates/a-explicit-go",
    "B": EXPERIMENT / "candidates/b-generated-go",
    "C": EXPERIMENT / "candidates/c-reflection-go",
    "D": EXPERIMENT / "candidates/d-typescript",
}


def fail(message: str) -> None:
    raise SystemExit("verify-candidate-d: " + message)


targets = json.loads((EXPERIMENT / "scope/targets.json").read_text(encoding="utf-8"))
names = targets["candidate_output_names"]
candidate_d = CANDIDATES["D"]

for workflow in targets["workflows"]:
    name = names[workflow["roadmap_workflow"]]
    candidate = candidate_d / "outputs" / name
    golden = REPOSITORY / workflow["golden_path"]
    result = subprocess.run(
        ["go", "run", "./cmd/t1conform", "--candidate", str(candidate), "--golden", str(golden)],
        cwd=REPOSITORY / "fixtures/t1-plan-conformance",
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        fail(result.stdout + result.stderr)

comparison_names = [
    names["W1"],
    names["W2"],
    names["W3"],
    names["effect"],
    "w1-logical-trace.json",
]
for name in comparison_names:
    values = {
        label: json.loads((directory / "outputs" / name).read_text(encoding="utf-8"))
        for label, directory in CANDIDATES.items()
    }
    baseline = values["A"]
    if any(value != baseline for value in values.values()):
        fail(f"canonical A/B/C/D mismatch: {name}")

expected_effect = json.loads((EXPERIMENT / "scope/effect-probe.schema.json").read_text(encoding="utf-8"))
if json.loads((candidate_d / "outputs" / names["effect"]).read_text(encoding="utf-8")) != expected_effect:
    fail("effect output differs from the Phase A probe")

w1 = next(item for item in targets["workflows"] if item["roadmap_workflow"] == "W1")
trace = json.loads((candidate_d / "outputs/w1-logical-trace.json").read_text(encoding="utf-8"))
if trace != w1["logical_authoring_shape"]:
    fail("W1 trace differs from the Phase A oracle")

for path in candidate_d.rglob("*.ts"):
    text = path.read_text(encoding="utf-8")
    if any(value in text for value in ("prototype/bootstrap", "fixtures/", "a-explicit-go", "b-generated-go", "c-reflection-go", "candidates/")):
        fail(f"forbidden implementation dependency in {path.relative_to(candidate_d)}")

package = json.loads((candidate_d / "package.json").read_text(encoding="utf-8"))
if package.get("devDependencies") != {"typescript": "5.9.3"}:
    fail("semantic checker is not exact-pinned")

for name in (
    "manifest.json",
    "dependencies.json",
    "count-manifest.json",
    "limitations.json",
    "check-summary.json",
    "negative-artifact.log",
    "negative-endpoint.log",
):
    if not (candidate_d / "evidence" / name).is_file():
        fail("missing evidence/" + name)

print("verify-candidate-d: PASS")
