#!/usr/bin/env python3
"""Compare completed B outputs; contains no authoring implementation."""
import json, subprocess
from pathlib import Path

EXPERIMENT=Path(__file__).resolve().parents[1]; REPOSITORY=EXPERIMENT.parents[1]
B=EXPERIMENT/"candidates/b-generated-go"; A=EXPERIMENT/"candidates/a-explicit-go"
def fail(message): raise SystemExit("verify-candidate-b: "+message)
targets=json.loads((EXPERIMENT/"scope/targets.json").read_text()); names=targets["candidate_output_names"]
for workflow in targets["workflows"]:
    name=names[workflow["roadmap_workflow"]]; candidate=B/"outputs"/name; golden=REPOSITORY/workflow["golden_path"]
    result=subprocess.run(["go","run","./cmd/t1conform","--candidate",str(candidate),"--golden",str(golden)],cwd=REPOSITORY/"fixtures/t1-plan-conformance",text=True,capture_output=True)
    if result.returncode: fail(result.stdout+result.stderr)
for name in [names["W1"],names["W2"],names["W3"],names["effect"],"w1-logical-trace.json"]:
    left=json.loads((A/"outputs"/name).read_text()); right=json.loads((B/"outputs"/name).read_text())
    if left != right: fail(f"canonical A/B mismatch: {name}")
effect=json.loads((B/"outputs"/names["effect"]).read_text()); expected=json.loads((EXPERIMENT/"scope/effect-probe.schema.json").read_text())
if effect != expected: fail("effect differs from Phase A probe")
w1=next(item for item in targets["workflows"] if item["roadmap_workflow"]=="W1")
if json.loads((B/"outputs/w1-logical-trace.json").read_text()) != w1["logical_authoring_shape"]: fail("W1 trace differs from oracle")
for path in B.rglob("*.go"):
    text=path.read_text()
    if "prototype/bootstrap" in text or "fixtures/" in text or "a-explicit-go" in text or "candidates/" in text: fail(f"forbidden dependency in {path.relative_to(B)}")
for name in ["manifest.json","dependencies.json","count-manifest.json","limitations.json","check-summary.json","negative-artifact.log","negative-endpoint.log"]:
    if not (B/"evidence"/name).is_file(): fail("missing evidence/"+name)
print("verify-candidate-b: PASS")
