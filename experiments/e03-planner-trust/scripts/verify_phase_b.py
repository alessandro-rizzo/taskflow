#!/usr/bin/env python3
"""Verify retained E03 Phase B evidence and the mechanically selected branch."""

import base64
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys


SCRIPT = Path(__file__).resolve()
EXPERIMENT = SCRIPT.parents[1]
ROOT = SCRIPT.parents[3]
EVIDENCE = EXPERIMENT / "evidence"
ALLOWED = {"blocked", "bounded", "trusted_local_limitation"}
REQUIRED_ATTEMPT = {
    "format_version", "candidate", "attempt_id", "case_id", "outcome",
    "duration_seconds", "mechanism_identity", "policy_digest", "applied_limits",
    "denial_reason", "leak_scan",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    contract = subprocess.run(
        [sys.executable, str(EXPERIMENT / "scripts/verify_contract.py")],
        cwd=ROOT, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    require(contract.returncode == 0, "frozen Phase A contract no longer verifies: " + contract.stderr.strip())
    score = load(EVIDENCE / "scorecard.json")
    require(score["contract_commit"] == "b8039d4dc48410c43dec7702ff88086714327b2e", "contract anchor drift")
    require(score["selected_branch"] == "static-descriptor", "unexpected decision branch")

    results = {}
    for candidate in ("native", "pooled-container", "helper-vm", "static-descriptor"):
        result = load(EVIDENCE / "raw/attacks" / f"{candidate}.json")
        require(result["candidate"] == candidate, f"candidate mismatch: {candidate}")
        require(result["state"] in {"exercised", "unavailable"}, f"invalid state: {candidate}")
        for attempt in result.get("attempts", []):
            require(REQUIRED_ATTEMPT <= set(attempt), f"attempt fields missing: {attempt.get('attempt_id')}")
            require(attempt["outcome"] in ALLOWED, f"invalid outcome: {attempt.get('attempt_id')}")
            require(not attempt["leak_scan"]["synthetic_parent_canary_found"], f"canary leak: {attempt.get('attempt_id')}")
        results[candidate] = result

    require(results["native"]["state"] == "unavailable", "native must fail closed after positive-control failure")
    require(results["helper-vm"]["state"] == "unavailable", "helper VM availability changed")
    pooled_limits = [a for a in results["pooled-container"]["attempts"] if a["outcome"] == "trusted_local_limitation"]
    require([a["case_id"] for a in pooled_limits] == ["home-and-config-roots-absent"], "pooled limitation drift")
    require(results["pooled-container"]["outside_canary_unchanged"] is True, "pooled outside canary changed")
    require(results["pooled-container"]["unauthorized_listener_accepts"] == 0, "pooled listener accepted a connection")
    require(len(results["static-descriptor"]["attempts"]) == 25, "static case coverage drift")
    require(results["static-descriptor"]["accepted_plan"] is True, "static known-good rejected")

    validator = load(EVIDENCE / "raw/validator/cases.json")
    require(validator["case_count"] == 19 and validator["all_passed"], "validator matrix failed")
    require(validator["known_good_accepted"], "validator positive control failed")

    record = load(EVIDENCE / "raw/benchmarks/static-descriptor/record.json")
    require(record["sample_count"] == 30, "benchmark sample count drift")
    require(record["p95"] < 0.25, "static descriptor missed warm W1 budget")
    require(abs(record["p95"] - score["candidates"]["static-descriptor"]["p95_seconds"]) < 1e-12, "scorecard p95 mismatch")
    samples = sorted(record["samples"])
    require(len(samples) == record["sample_count"], "benchmark sample array mismatch")
    expected_median = (samples[14] + samples[15]) / 2
    expected_p95 = samples[math.floor(0.95 * (len(samples) - 1) + 0.5)]
    require(abs(record["median"] - expected_median) < 1e-12, "benchmark median mismatch")
    require(abs(record["p95"] - expected_p95) < 1e-12, "benchmark p95 recomputation mismatch")
    sample_lines = [float(line) for line in (EVIDENCE / "raw/benchmarks/static-descriptor/samples.txt").read_text().splitlines()]
    require(sample_lines == record["samples"], "benchmark raw samples disagree with record")

    for value in score["hard_gates"].values():
        require(value == 0, "a scorecard hard gate is nonzero")

    implementation = load(EVIDENCE / "implementation-manifest.json")
    for item in implementation["entries"]:
        path = ROOT / item["path"]
        require(path.is_file(), "implementation path missing: " + item["path"])
        require(sha256(path) == item["sha256"], "implementation digest mismatch: " + item["path"])

    manifest = load(EVIDENCE / "manifest.json")
    for entry in manifest["entries"]:
        path = ROOT / entry["path"]
        require(path.is_file(), "manifest path missing: " + entry["path"])
        require(sha256(path) == entry["sha256"], "manifest digest mismatch: " + entry["path"])

    forbidden = []
    for marker in (
        b"E03-SYNTHETIC-PARENT-CANARY-5d2ec7",
        b"E03-SYNTHETIC-OUTPUT-PROBE-7fc86c",
    ):
        forbidden.extend((marker, marker.hex().encode(), base64.b64encode(marker)))
    for path in EVIDENCE.rglob("*"):
        if path.is_file() and path.name != "manifest.json":
            raw = path.read_bytes()
            require(not any(marker in raw for marker in forbidden), "synthetic canary retained in " + str(path.relative_to(ROOT)))

    print(
        "E03 Phase B evidence: PASS branch=static-descriptor "
        f"validator=19/19 warm-p95={record['p95'] * 1000:.3f}ms"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, KeyError, TypeError, RuntimeError) as exc:
        print("verify_phase_b.py:", exc, file=sys.stderr)
        raise SystemExit(1)
