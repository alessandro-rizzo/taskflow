#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCOPES = {
    "W1": "w1-fast-project-check.schema.json",
    "W2": "w2-cross-target-artifact-pipeline.schema.json",
    "W3": "w3-isolated-native-mobile-stack.schema.json",
    "effect": "e01-effect-probe.schema.json",
}

for required in (
    "evidence/manifest.json",
    "evidence/dependencies.json",
    "evidence/count-manifest.json",
    "evidence/limitations.json",
    "limitations.md",
):
    if not (ROOT / required).is_file():
        raise SystemExit(f"missing candidate evidence declaration: {required}")


def run(args: list[str], *, ok: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, env=env)
    if ok and result.returncode != 0:
        raise SystemExit(f"{' '.join(args)} failed\n{result.stdout}{result.stderr}")
    return result


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


with tempfile.TemporaryDirectory(prefix="verify-", dir=ROOT) as temporary:
    relative_temporary = Path(temporary).relative_to(ROOT)
    binary = Path(temporary) / "e01a"
    run(["go", "build", "-o", str(binary), "./cmd/e01a"])
    sentinel = Path(temporary) / "body-sentinel"
    environment = dict(os.environ, E01_BODY_SENTINEL=str(sentinel))
    hashes: dict[str, str] = {}
    for scope, filename in SCOPES.items():
        samples = [run([str(binary), "discover", scope], env=environment).stdout for _ in range(10)]
        if len(set(samples)) != 1:
            raise SystemExit(f"{scope} discovery is not byte deterministic")
        parsed = json.loads(samples[0])
        write(ROOT / "outputs" / filename, json.dumps(parsed, indent=2) + "\n")
        hashes[scope] = hashlib.sha256(samples[0].encode()).hexdigest()

    traces = [run([str(binary), "trace"], env=environment).stdout for _ in range(10)]
    if len(set(traces)) != 1:
        raise SystemExit("W1 trace is not byte deterministic")
    write(ROOT / "outputs/w1-logical-trace.json", json.dumps(json.loads(traces[0]), indent=2) + "\n")

    cases = [
        ("W1", '{"unknown":true}', "unknown", "known argument"),
        ("W1", '{"changed-only":"yes"}', "changed-only", "boolean"),
        ("W1", '{"verbosity":"loud"}', "verbosity", "one of"),
        ("effect", "{}", "environment", "required string"),
    ]
    diagnostics = []
    for scope, payload, path, expected in cases:
        result = run([str(binary), "validate", scope, payload], ok=False, env=environment)
        if result.returncode == 0:
            raise SystemExit(f"diagnostic case unexpectedly passed: {scope} {payload}")
        lines = result.stderr.splitlines()
        if len(lines) < 2:
            raise SystemExit(f"missing machine/human diagnostic: {result.stderr}")
        value = json.loads(lines[0])
        if not value["operation"] or value["path"] != path or expected not in value["expected"] or not lines[1]:
            raise SystemExit(f"incomplete diagnostic: {result.stderr}")
        diagnostics.append(value)
    if sentinel.exists():
        raise SystemExit("discovery or validation evaluated an operation body")

    for name, type_names in {
        "artifact": ("BackendBinary", "IOSApp"),
        "endpoint": ("API", "OtherAPI"),
    }.items():
        target = ROOT / relative_temporary / name
        target.mkdir()
        shutil.copy(ROOT / "compilefail" / f"{name}.go.txt", target / f"{name}.go")
        result = run(["go", "test", f"./{relative_temporary}/{name}"], ok=False)
        output = result.stdout + result.stderr
        if result.returncode == 0 or name not in output or any(type_name not in output for type_name in type_names):
            raise SystemExit(f"negative {name} composition lacked fixture/type context\n{output}")
        stable_output = output.replace(relative_temporary.as_posix(), "verify-TEMP")
        write(ROOT / "evidence" / f"negative-{name}.log", stable_output)

    source = (ROOT / "candidate.go").read_text(encoding="utf-8").splitlines()
    begin = source.index("// E01-AUTHOR-BEGIN") + 1
    end = source.index("// E01-AUTHOR-END")
    authored = sum(1 for line in source[begin:end] if line.strip() and not line.lstrip().startswith("//"))
    summary = {
        "candidate": "A",
        "approach": "explicit-generic-go",
        "determinism_runs_per_scope": 10,
        "body_sentinel_absent": True,
        "positive_typing": "go test ./...",
        "negative_typing": ["artifact", "endpoint"],
        "diagnostic_cases": diagnostics,
        "authored_loc": authored,
        "low_level_concepts": ["operation-registration", "argument-schema", "output-schema", "capability-request"],
        "output_hashes": hashes,
        "versions": {"go": run(["go", "version"]).stdout.strip(), "python": run(["python3", "--version"]).stdout.strip()},
    }
    write(ROOT / "evidence/check-summary.json", json.dumps(summary, indent=2) + "\n")

print("candidate A: PASS")
