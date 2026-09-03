#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


SCRIPT = Path(__file__).resolve()
TRIALS = SCRIPT.parents[1]
ROOT = SCRIPT.parents[4]
PROTOCOL = json.loads((ROOT / "experiments/e01-authoring-schema/measurements/protocol.json").read_text())
DEFAULT_OUTPUT = Path("/private/tmp/e01-sealed-4b77693a513a")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reset_output(output: Path) -> None:
    resolved = output.resolve()
    if resolved != DEFAULT_OUTPUT.resolve() and not resolved.name.startswith("e01-sealed-"):
        raise SystemExit(f"refusing to replace non-sealed output {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.out.resolve()
    reset_output(output)
    schemas = output / "schemas"
    schemas.mkdir()
    candidate = ROOT / PROTOCOL["candidates"]["A"]["directory"] / "outputs"
    copies = {
        "w1-fast-project-check.schema.json": "w1.schema.json",
        "w2-cross-target-artifact-pipeline.schema.json": "w2.schema.json",
        "w3-isolated-native-mobile-stack.schema.json": "w3.schema.json",
        "e01-effect-probe.schema.json": "effect.schema.json",
    }
    for source, destination in copies.items():
        shutil.copyfile(candidate / source, schemas / destination)
    for name in ("invalid-w1-args.json", "help.txt", "prompt.md", "response-schema.json"):
        shutil.copyfile(TRIALS / name, output / name)
    subprocess.run([
        "go", "build", "-trimpath", "-ldflags=-s -w", "-o", str(output / "taskflow-e01"),
        str(TRIALS / "scripts/fake-interface.go"),
    ], cwd=ROOT, check=True)
    files = sorted(path for path in output.rglob("*") if path.is_file())
    hashes = {str(path.relative_to(output)): sha256(path) for path in files}
    digest_input = "".join(f"{name}\0{value}\n" for name, value in sorted(hashes.items())).encode()
    manifest = {
        "schema_version": "taskflow-e01-sealed-bundle/v1",
        "protocol_sha256": hashlib.sha256((ROOT / "experiments/e01-authoring-schema/measurements/protocol.json").read_bytes()).hexdigest(),
        "candidate_source_revision": PROTOCOL["candidate_source_revision"],
        "candidate_source_included": False,
        "repository_documentation_included": False,
        "shared_schema_source": "canonically identical A-D output; copied from A only after cross-candidate audit",
        "files": hashes,
        "bundle_digest": hashlib.sha256(digest_input).hexdigest(),
    }
    (output / "bundle-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
