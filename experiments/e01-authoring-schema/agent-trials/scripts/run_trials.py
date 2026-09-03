#!/usr/bin/env python3
import hashlib
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time


SCRIPT = Path(__file__).resolve()
TRIALS = SCRIPT.parents[1]
ROOT = SCRIPT.parents[4]
RESULTS = TRIALS / "results"
BASE_BUNDLE = Path("/private/tmp/e01-sealed-4b77693a513a")
CONTROL_ROOT = Path("/private/tmp/e01-seatbelt-4b77693a513a")
MEMORY_ROOT = Path("/Users/alessandro.rizzo/.codex/memories")
SETUP_FAILURE = TRIALS / "setup-failures/2026-09-03-invalid-response-schema"
NESTED_SANDBOX_FAILURE = TRIALS / "setup-failures/2026-09-03-nested-sandbox"


def worktrees() -> list[Path]:
    output = subprocess.check_output(["git", "worktree", "list", "--porcelain"], cwd=ROOT, text=True)
    return [Path(line.removeprefix("worktree ")).resolve() for line in output.splitlines() if line.startswith("worktree ")]


def quote_profile(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def make_profile(denied: list[Path]) -> str:
    lines = ["(version 1)", "(allow default)"]
    for denied_root in denied:
        value = quote_profile(str(denied_root))
        lines.append(f'(deny file-read* (subpath "{value}"))')
        lines.append(f'(deny file-write* (subpath "{value}"))')
    return "\n".join(lines) + "\n"


def safe_reset(path: Path, prefix: str) -> None:
    resolved = path.resolve()
    if not resolved.name.startswith(prefix) or resolved.parent != Path("/private/tmp"):
        raise SystemExit(f"refusing to reset unexpected trial path {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def run_preflight(profile: Path, denied: list[Path]) -> dict:
    checks = ["test -r help.txt", "test -x taskflow-e01", "./taskflow-e01 api W3 >/dev/null"]
    for source in denied:
        checks.append(f"test ! -r {shlex.quote(str(source / 'README.md'))}")
    command = ["sandbox-exec", "-f", str(profile), "/bin/sh", "-c", " && ".join(checks)]
    completed = subprocess.run(command, cwd=BASE_BUNDLE, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    audit = BASE_BUNDLE / ".interface-audit.jsonl"
    if audit.exists():
        audit.unlink()
    return {"command": command, "exit_code": completed.returncode, "output": completed.stdout}


def copy_if_present(source: Path, destination: Path) -> None:
    if source.exists():
        shutil.copyfile(source, destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retry-after-invalid-schema", action="store_true")
    parser.add_argument("--retry-after-nested-sandbox", action="store_true")
    args = parser.parse_args()
    if args.retry_after_invalid_schema:
        if not RESULTS.exists():
            raise SystemExit("invalid-schema retry requires retained failed results")
        transcripts = list(RESULTS.glob("attempt-*/transcript.jsonl"))
        if len(transcripts) != 2 or not all("invalid_json_schema" in path.read_text() for path in transcripts):
            raise SystemExit("refusing retry: prior attempts were not both pre-inference invalid-schema failures")
        if SETUP_FAILURE.exists():
            raise SystemExit(f"refusing to overwrite setup failure evidence: {SETUP_FAILURE}")
        SETUP_FAILURE.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(RESULTS), str(SETUP_FAILURE))
    if args.retry_after_nested_sandbox:
        if not RESULTS.exists():
            raise SystemExit("nested-sandbox retry requires retained failed results")
        responses = list(RESULTS.glob("attempt-*/final-response.json"))
        if len(responses) != 2 or not all("sandbox_apply" in path.read_text() for path in responses):
            raise SystemExit("refusing retry: prior attempts were not both nested-sandbox setup failures")
        if NESTED_SANDBOX_FAILURE.exists():
            raise SystemExit(f"refusing to overwrite setup failure evidence: {NESTED_SANDBOX_FAILURE}")
        NESTED_SANDBOX_FAILURE.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(RESULTS), str(NESTED_SANDBOX_FAILURE))
    if RESULTS.exists():
        raise SystemExit(f"refusing to overwrite existing trial results: {RESULTS}")
    subprocess.run(["python3", str(TRIALS / "scripts/build_bundle.py"), "--out", str(BASE_BUNDLE)], cwd=ROOT, check=True)
    manifest = json.loads((BASE_BUNDLE / "bundle-manifest.json").read_text())
    denied = worktrees() + [MEMORY_ROOT]
    CONTROL_ROOT.mkdir(parents=True, exist_ok=True)
    profile_text = make_profile(denied)
    profile = CONTROL_ROOT / "source-deny.sb"
    profile.write_text(profile_text)
    preflight = run_preflight(profile, denied)
    if preflight["exit_code"] != 0:
        raise SystemExit(f"Seatbelt preflight failed: {preflight}")
    RESULTS.mkdir(parents=True)
    (RESULTS / "bundle-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (RESULTS / "source-deny.sb").write_text(profile_text)
    (RESULTS / "access-control-preflight.json").write_text(json.dumps({
        "schema_version": "taskflow-e01-source-control-preflight/v1",
        "denied_roots": [str(path) for path in denied],
        "bundle_root": str(BASE_BUNDLE),
        "bundle_readable_and_executable": True,
        "denied_roots_unreadable": True,
        **preflight,
    }, indent=2) + "\n")

    prompt = (TRIALS / "prompt.md").read_text()
    summaries = []
    for attempt in (1, 2):
        bundle = Path(f"/private/tmp/e01-sealed-attempt-{attempt}-4b77693a513a")
        safe_reset(bundle, f"e01-sealed-attempt-{attempt}-")
        shutil.copytree(BASE_BUNDLE, bundle)
        result_dir = RESULTS / f"attempt-{attempt}"
        result_dir.mkdir()
        final_message = bundle / "final-response.json"
        command = [
            "sandbox-exec", "-f", str(profile),
            "codex", "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--sandbox", "danger-full-access",
            "--cd", str(bundle),
            "--output-schema", str(bundle / "response-schema.json"),
            "--output-last-message", str(final_message),
            "--json",
            prompt,
        ]
        started = time.monotonic()
        completed = subprocess.run(command, cwd=bundle, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env={**os.environ, "NO_COLOR": "1"})
        elapsed = time.monotonic() - started
        (result_dir / "transcript.raw.log").write_text(completed.stdout)
        json_events = [line for line in completed.stdout.splitlines() if line.startswith("{")]
        for event in json_events:
            json.loads(event)
        (result_dir / "transcript.jsonl").write_text("\n".join(json_events) + "\n")
        copy_if_present(final_message, result_dir / "final-response.json")
        copy_if_present(bundle / "repaired-w1-args.json", result_dir / "repaired-w1-args.json")
        copy_if_present(bundle / "invocation-result.json", result_dir / "invocation-result.json")
        copy_if_present(bundle / ".interface-audit.jsonl", result_dir / "interface-audit.jsonl")
        denied_mentions = [str(path) for path in denied if str(path) in completed.stdout]
        summary = {
            "schema_version": "taskflow-e01-agent-attempt/v1",
            "attempt": attempt,
            "bundle_digest": manifest["bundle_digest"],
            "command": command,
            "exit_code": completed.returncode,
            "elapsed_seconds": elapsed,
            "fresh_ephemeral_session": True,
            "codex_inner_sandbox": "danger-full-access; enclosing Seatbelt profile is the enforcement boundary",
            "seatbelt_profile_sha256": hashlib.sha256(profile_text.encode()).hexdigest(),
            "denied_source_path_mentions_in_transcript": denied_mentions,
            "blocked_source_read_attempt": bool(denied_mentions),
        }
        (result_dir / "attempt.json").write_text(json.dumps(summary, indent=2) + "\n")
        summaries.append(summary)
    (RESULTS / "attempts.json").write_text(json.dumps(summaries, indent=2) + "\n")
    print("run-trials: completed two attempts")


if __name__ == "__main__":
    main()
