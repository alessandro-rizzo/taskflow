#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
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


def run(args: list[str], *, ok: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, env=env)
    if ok and result.returncode != 0:
        raise SystemExit(f"{' '.join(args)} failed\n{result.stdout}{result.stderr}")
    return result


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


for required in (
    "package.json",
    "bun.lock",
    "tsconfig.json",
    "evidence/manifest.json",
    "evidence/dependencies.json",
    "evidence/count-manifest.json",
    "evidence/limitations.json",
    "limitations.md",
):
    if not (ROOT / required).is_file():
        raise SystemExit(f"missing candidate declaration: {required}")

package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
if package.get("devDependencies") != {"typescript": "5.9.3"}:
    raise SystemExit("Candidate D must pin exactly TypeScript 5.9.3")

with tempfile.TemporaryDirectory(prefix="verify-", dir=ROOT) as temporary:
    temporary_path = Path(temporary)
    sentinel = temporary_path / "body-sentinel"
    environment = dict(os.environ, E01_BODY_SENTINEL=str(sentinel))
    hashes: dict[str, str] = {}
    for scope, filename in SCOPES.items():
        samples = [run(["bun", "run", "cli.ts", "discover", scope], env=environment).stdout for _ in range(10)]
        if len(set(samples)) != 1:
            raise SystemExit(f"{scope} discovery is not byte deterministic")
        parsed = json.loads(samples[0])
        write(ROOT / "outputs" / filename, json.dumps(parsed, indent=2) + "\n")
        hashes[scope] = hashlib.sha256(samples[0].encode()).hexdigest()

    traces = [run(["bun", "run", "cli.ts", "trace"], env=environment).stdout for _ in range(10)]
    if len(set(traces)) != 1:
        raise SystemExit("W1 trace is not byte deterministic")
    write(ROOT / "outputs/w1-logical-trace.json", json.dumps(json.loads(traces[0]), indent=2) + "\n")

    diagnostics = []
    cases = [
        ("W1", '{"unknown":true}', "unknown", "known argument"),
        ("W1", '{"changed-only":"yes"}', "changed-only", "boolean"),
        ("W1", '{"verbosity":"loud"}', "verbosity", "one of"),
        ("effect", "{}", "environment", "required string"),
    ]
    for scope, payload, path, expected in cases:
        result = run(["bun", "run", "cli.ts", "validate", scope, payload], ok=False, env=environment)
        lines = result.stderr.splitlines()
        if result.returncode == 0 or len(lines) < 2:
            raise SystemExit(f"diagnostic did not fail with machine and human output: {scope}")
        value = json.loads(lines[0])
        if not value["operation"] or value["path"] != path or expected not in value["expected"] or not lines[1]:
            raise SystemExit(f"incomplete diagnostic: {result.stderr}")
        diagnostics.append(value)
    if sentinel.exists():
        raise SystemExit("discovery or validation evaluated an operation body")

    negative_logs: dict[str, str] = {}
    common = [
        str(ROOT / "node_modules/.bin/tsc"),
        "--noEmit",
        "--strict",
        "--target", "ES2022",
        "--module", "ESNext",
        "--moduleResolution", "Bundler",
        "--allowImportingTsExtensions",
        "node-shim.d.ts",
    ]
    for name, type_names in {
        "artifact": ("BackendBinary", "IOSApp"),
        "endpoint": ("API", "OtherAPI"),
    }.items():
        result = run(common + [f"typefail/{name}.ts"], ok=False)
        output = result.stdout + result.stderr
        if result.returncode == 0 or f"typefail/{name}.ts" not in output or any(value not in output for value in type_names):
            raise SystemExit(f"negative {name} composition lacked fixture/type context\n{output}")
        write(ROOT / "evidence" / f"negative-{name}.log", output)
        negative_logs[name] = output

    formatted = run(["bun", "run", "scripts/format-source.mjs", "candidate.ts"]).stdout
    formatted_path = temporary_path / "candidate.ts"
    write(formatted_path, formatted)
    formatted_again = run(["bun", "run", "scripts/format-source.mjs", str(formatted_path)]).stdout
    if formatted != formatted_again:
        raise SystemExit("TypeScript compiler-printer normalization is not idempotent")
    formatted_lines = formatted.splitlines()
    begin = formatted_lines.index("// E01-AUTHOR-BEGIN") + 1
    end = formatted_lines.index("// E01-AUTHOR-END")
    authored = sum(1 for line in formatted_lines[begin:end] if line.strip() and not line.lstrip().startswith("//"))
    summary = {
        "candidate": "D",
        "approach": "minimal-typescript-descriptors",
        "semantic_checker": run([str(ROOT / "node_modules/.bin/tsc"), "--version"]).stdout.strip(),
        "checker_lock_sha256": hashlib.sha256((ROOT / "bun.lock").read_bytes()).hexdigest(),
        "formatter": "TypeScript compiler API printer",
        "formatter_idempotent": True,
        "authored_loc": authored,
        "low_level_concepts": ["operation-registration", "argument-schema", "output-schema", "capability-request"],
        "nominal_typing_phantom_members": 3,
        "determinism_runs_per_scope": 10,
        "body_sentinel_absent": True,
        "positive_typing": "bun run typecheck",
        "negative_typing": ["artifact", "endpoint"],
        "diagnostic_cases": diagnostics,
        "output_hashes": hashes,
        "versions": {
            "bun": run(["bun", "--version"]).stdout.strip(),
            "python": run(["python3", "--version"]).stdout.strip(),
        },
    }
    write(ROOT / "evidence/check-summary.json", json.dumps(summary, indent=2) + "\n")

print("candidate D: PASS")
