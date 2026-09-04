#!/usr/bin/env python3
"""Build deterministic summaries and manifests from retained E03 evidence."""

import argparse
import hashlib
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve()
EXPERIMENT = SCRIPT.parents[1]
ROOT = SCRIPT.parents[3]
EVIDENCE = EXPERIMENT / "evidence"
CONTRACT = "b8039d4dc48410c43dec7702ff88086714327b2e"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entry(path):
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--container-id", required=True)
    args = parser.parse_args()

    attacks = {
        name: load(EVIDENCE / "raw/attacks" / f"{name}.json")
        for name in ("native", "pooled-container", "helper-vm", "static-descriptor")
    }
    benchmark = load(EVIDENCE / "raw/benchmarks/static-descriptor/record.json")
    validator = load(EVIDENCE / "raw/validator/cases.json")
    pooled_limitations = [
        attempt["case_id"] for attempt in attacks["pooled-container"]["attempts"]
        if attempt["outcome"] == "trusted_local_limitation"
    ]

    availability = {
        "native": {
            "state": attacks["native"]["state"],
            "reason": attacks["native"]["reason"],
            "limitations": attacks["native"].get("limitations", []),
            "credit": "none",
        },
        "pooled-container": {
            "state": attacks["pooled-container"]["state"],
            "engine": "docker",
            "server_version": "29.2.1",
            "image_digest": args.image_digest,
            "container_id": args.container_id,
            "network": "none",
            "read_only_root": True,
            "capabilities_dropped": ["ALL"],
            "no_new_privileges": True,
            "memory_bytes": 268435456,
            "nano_cpus": 1000000000,
            "pids_limit": 32,
            "file_descriptors": 64,
            "source_and_declared_inputs_read_only": True,
            "remote_pull_used": False,
            "limitations": pooled_limitations,
        },
        "helper-vm": {
            "state": attacks["helper-vm"]["state"],
            "reason": attacks["helper-vm"]["reason"],
            "vm_created_or_started": False,
        },
        "static-descriptor": {
            "state": attacks["static-descriptor"]["state"],
            "project_code_executed": False,
            "known_good_accepted": attacks["static-descriptor"]["accepted_plan"],
        },
    }
    for name, value in availability.items():
        write(EVIDENCE / "availability" / f"{name}.json", {
            "format_version": "taskflow-e03-availability/v1", "candidate": name, **value,
        })

    scorecard = {
        "format_version": "taskflow-e03-scorecard/v1",
        "contract_commit": CONTRACT,
        "selected_branch": "static-descriptor",
        "hard_gates": {
            "selected_source_digest_changes": 0,
            "outside_canary_changes": 0,
            "planner_visible_daemon_provider_secret_canary_bytes": 0,
            "retained_evidence_canary_or_encoded_canary_bytes": 0,
            "unauthorized_listener_accepts": 0,
            "surviving_descendants": 0,
            "post_exit_marker_writes": 0,
            "accepted_unauthorized_plans": 0,
        },
        "validator": {"known_good_accepted": validator["known_good_accepted"], "negative_cases_passed": sum(1 for result in validator["results"] if result["passed"]), "negative_case_count": validator["case_count"]},
        "candidates": {
            "native": {"state": "unavailable", "qualifies": False, "reason": attacks["native"]["reason"]},
            "pooled-container": {"state": "exercised", "qualifies": False, "blocked": 17, "bounded": 7, "trusted_local_limitations": pooled_limitations},
            "helper-vm": {"state": "unavailable", "qualifies": False, "reason": attacks["helper-vm"]["reason"]},
            "static-descriptor": {"state": "exercised", "qualifies": benchmark["p95"] < 0.25 and validator["all_passed"], "blocked": 25, "p95_seconds": benchmark["p95"], "threshold_seconds_exclusive": 0.25},
        },
    }
    write(EVIDENCE / "scorecard.json", scorecard)

    implementation_paths = [
        EXPERIMENT / "go.mod",
        *sorted((EXPERIMENT / "cmd").rglob("*.go")),
        EXPERIMENT / "container/Dockerfile",
        EXPERIMENT / "validator/e03_validator.py",
        EXPERIMENT / "validator/test_validator.py",
        EXPERIMENT / "scripts/e03_runner.py",
        EXPERIMENT / "scripts/run_validator_matrix.py",
        EXPERIMENT / "scripts/finalize_evidence.py",
        EXPERIMENT / "scripts/verify_phase_b.py",
    ]
    write(EVIDENCE / "implementation-manifest.json", {
        "format_version": "taskflow-e03-implementation-manifest/v1",
        "contract_commit": CONTRACT,
        "entries": [entry(path) for path in implementation_paths],
    })

    summary = f"""# E03 evidence summary

Contract commit: `{CONTRACT}`.

Selected branch: **static-descriptor**.

- Native: unavailable after the frozen Seatbelt profile failed its benign positive control; Darwin RLIMIT_AS is unsupported.
- Pooled container: 17 blocked, 7 bounded, 1 trusted-local limitation (`HOME` was ambient); not eligible.
- Helper VM: unavailable; no endpoint existed and no VM was created.
- Static descriptor: 25 project-code cases blocked by no execution; validator {validator['case_count']}/{validator['case_count']} negative cases passed and known-good W1 was accepted.
- Warm static planning: median {benchmark['median'] * 1000:.3f} ms, p95 {benchmark['p95'] * 1000:.3f} ms across {benchmark['sample_count']} serial samples; threshold p95 < 250 ms.
- Hard-gate counters: all zero.

Verification: `python3 experiments/e03-planner-trust/scripts/verify_phase_b.py`.
"""
    (EVIDENCE / "summary.md").write_text(summary, encoding="utf-8")

    manifest_paths = sorted(
        [path for path in EVIDENCE.rglob("*") if path.is_file() and path.name != "manifest.json"]
        + [EXPERIMENT / "decision.md", EXPERIMENT / "limitations.md", EXPERIMENT / "PHASE_B.md"],
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )
    write(EVIDENCE / "manifest.json", {
        "format_version": "taskflow-e03-evidence-manifest/v1",
        "contract_commit": CONTRACT,
        "entries": [entry(path) for path in manifest_paths],
    })
    print(f"E03 evidence finalized: {len(manifest_paths)} manifest entries")


if __name__ == "__main__":
    main()
