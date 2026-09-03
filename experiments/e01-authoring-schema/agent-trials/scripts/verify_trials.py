#!/usr/bin/env python3
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve()
TRIALS = SCRIPT.parents[1]
RESULTS = TRIALS / "results"
EXPECTED_W3_OUTPUTS = [{"id": "mobile-e2e-report", "type": "Report[MobileE2E]", "optional": False}]
EXPECTED_W3_CAPABILITIES = ["linux-execution-profile", "macos-execution-profile", "simulator-session"]
EXPECTED_W1_OUTPUTS = [
    {"id": "test-report", "type": "Report[GoTests]", "optional": False},
    {"id": "diagnostics", "type": "Report[Diagnostics]", "optional": True},
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"verify-trials: {message}")


def canonical_outputs(value: list[dict]) -> list[dict]:
    return sorted(value, key=lambda item: item["id"])


def main() -> None:
    preflight = json.loads((RESULTS / "access-control-preflight.json").read_text())
    require(preflight["exit_code"] == 0, "source-control preflight")
    require(preflight["denied_roots_unreadable"] is True, "source roots must be denied")
    manifest = json.loads((RESULTS / "bundle-manifest.json").read_text())
    require(manifest["candidate_source_included"] is False, "candidate source in bundle")
    require(manifest["repository_documentation_included"] is False, "repository docs in bundle")
    attempt_summaries = json.loads((RESULTS / "attempts.json").read_text())
    require(len(attempt_summaries) == 2, "expected exactly two attempts")
    require(len({item["bundle_digest"] for item in attempt_summaries}) == 1, "bundle differs between attempts")
    outcomes = []
    for attempt in (1, 2):
        directory = RESULTS / f"attempt-{attempt}"
        metadata = json.loads((directory / "attempt.json").read_text())
        require(metadata["exit_code"] == 0, f"attempt {attempt} exit")
        require(metadata["fresh_ephemeral_session"] is True, f"attempt {attempt} freshness")
        require(metadata["blocked_source_read_attempt"] is False, f"attempt {attempt} blocked source read")
        response = json.loads((directory / "final-response.json").read_text())
        require(response["source_read_attempted"] is False, f"attempt {attempt} self-reported source read")
        require(response["w3_operation"] == "mobile-e2e", f"attempt {attempt} W3 operation")
        require(canonical_outputs(response["w3_outputs"]) == canonical_outputs(EXPECTED_W3_OUTPUTS), f"attempt {attempt} W3 outputs")
        require(sorted(response["w3_capabilities"]) == sorted(EXPECTED_W3_CAPABILITIES), f"attempt {attempt} W3 capabilities")
        repaired = json.loads((directory / "repaired-w1-args.json").read_text())
        require(set(repaired) <= {"verbosity", "changed-only"}, f"attempt {attempt} unknown repaired argument")
        require(repaired.get("verbosity", "normal") in {"quiet", "normal", "verbose"}, f"attempt {attempt} verbosity")
        require(isinstance(repaired.get("changed-only", False), bool), f"attempt {attempt} changed-only")
        invocation = json.loads((directory / "invocation-result.json").read_text())
        require(invocation["status"] == "fake-success" and invocation["operation"] == "check", f"attempt {attempt} invocation")
        require(canonical_outputs(invocation["outputs"]) == canonical_outputs(EXPECTED_W1_OUTPUTS), f"attempt {attempt} invocation outputs")
        require(canonical_outputs(response["w1_outputs"]) == canonical_outputs(EXPECTED_W1_OUTPUTS), f"attempt {attempt} reported W1 outputs")
        audit = [json.loads(line) for line in (directory / "interface-audit.jsonl").read_text().splitlines() if line]
        commands = [item["arguments"] for item in audit]
        transcript = (directory / "transcript.jsonl").read_text()
        require("schemas/w3.schema.json" in transcript, f"attempt {attempt} did not inspect sealed W3 schema")
        events = [json.loads(line) for line in transcript.splitlines() if line.startswith("{")]
        shell_commands = [event["item"]["command"] for event in events if event.get("type") == "item.started" and event.get("item", {}).get("type") == "command_execution"]
        for command in shell_commands:
            require("../" not in command, f"attempt {attempt} traversed outside bundle")
            require("/Users/" not in command, f"attempt {attempt} referenced a user source path")
            require("find /" not in command and "cd /" not in command and "ls /" not in command, f"attempt {attempt} attempted a root filesystem read")
        require(any(values[:2] == ["validate", "W1"] for values in commands), f"attempt {attempt} did not validate W1")
        require(any(values[:2] == ["invoke", "W1"] for values in commands), f"attempt {attempt} did not invoke W1")
        outcomes.append({
            "attempt": attempt,
            "success": True,
            "elapsed_seconds": metadata["elapsed_seconds"],
            "bundle_digest": metadata["bundle_digest"],
            "source_read_attempted": False,
            "tasks": {"discover_w3": "pass", "repair_w1": "pass", "invoke_w1": "pass"},
        })
    summary = {
        "schema_version": "taskflow-e01-agent-trial-summary/v1",
        "attempts_required": 2,
        "attempts_succeeded": 2,
        "shared_schema_trial": True,
        "source_access_control": "macOS Seatbelt denied primary repository, known worktrees, and Codex memory",
        "success": True,
        "outcomes": outcomes,
    }
    (TRIALS / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print("verify-trials: PASS")


if __name__ == "__main__":
    main()
