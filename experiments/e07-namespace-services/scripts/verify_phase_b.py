#!/usr/bin/env python3
"""Fail-closed verification for the frozen E07 contract and Phase B evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[1]
CONTRACT_COMMIT = "7a61d88"


def fail(message: str) -> None:
    raise ValueError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def p95(values: List[float]) -> float:
    return sorted(values)[round(0.95 * (len(values) - 1))]


def median(values: List[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def verify_phase_a() -> None:
    manifest = load(ROOT / "frozen-artifacts.json")
    for artifact in manifest["artifacts"]:
        path = ROOT / artifact["path"]
        if not path.is_file() or digest(path) != artifact["sha256"]:
            fail(f"frozen Phase A artifact changed: {artifact['path']}")
        relative = path.relative_to(PROJECT)
        committed = subprocess.check_output(["git", "show", f"{CONTRACT_COMMIT}:{relative}"], cwd=str(PROJECT))
        if hashlib.sha256(committed).hexdigest() != artifact["sha256"]:
            fail(f"contract commit mismatch: {artifact['path']}")
    expected_protocol = (ROOT / "protocol.sha256").read_text().split()[0]
    if digest(ROOT / "frozen-artifacts.json") != expected_protocol:
        fail("protocol digest does not bind frozen manifest")
    subprocess.check_call(["git", "merge-base", "--is-ancestor", CONTRACT_COMMIT, "HEAD"], cwd=str(PROJECT))


def verify_jsonl(path: Path, expected: int) -> List[Dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if len(rows) != expected:
        fail(f"{path.name}: expected {expected} rows, got {len(rows)}")
    common = {"format_version", "sequence", "event", "run_id", "namespace_id", "monotonic_seconds"}
    for row in rows:
        if not common.issubset(row):
            fail(f"{path.name}: missing common event fields")
        if row["format_version"] != "taskflow-e07-event-evidence/v1-experimental":
            fail(f"{path.name}: wrong format")
    return rows


def verify_benchmark(path: Path) -> None:
    record = load(path)
    required = {"schema_version", "experiment_id", "fixture_id", "source_revision", "timestamp", "hardware", "os", "toolchain", "state", "preparation_command", "samples", "sample_count", "median", "p95", "raw_result_location"}
    if not required.issubset(record):
        fail(f"benchmark missing fields: {path}")
    samples = record["samples"]
    if record["schema_version"] != "taskflow-t1-benchmark/v2" or record["experiment_id"] != "E07" or record["fixture_id"] != "w3-isolated-native-mobile-stack":
        fail(f"benchmark identity mismatch: {path}")
    if len(samples) != 30 or record["sample_count"] != 30 or any(not math.isfinite(value) or value < 0 for value in samples):
        fail(f"benchmark sample set invalid: {path}")
    if abs(record["median"] - median(samples)) > 1e-9 or abs(record["p95"] - p95(samples)) > 1e-9:
        fail(f"benchmark statistics mismatch: {path}")
    raw = [float(line) for line in (path.parent / record["raw_result_location"]).read_text().splitlines()]
    if len(raw) != len(samples) or any(abs(left - right) > 1e-9 for left, right in zip(raw, samples)):
        fail(f"benchmark raw samples mismatch: {path}")


def verify_phase_b() -> None:
    evidence = ROOT / "evidence"
    schema = load(ROOT / "event-schema.json")
    for required in schema["phase_b_evidence"]["required_paths"]:
        if not (ROOT / required).is_file():
            fail(f"required evidence missing: {required}")
    thresholds = load(ROOT / "thresholds.json")
    isolation = verify_jsonl(evidence / "raw" / "paired-namespaces.jsonl", 20)
    authorization = verify_jsonl(evidence / "raw" / "authorization.jsonl", 120)
    readiness = verify_jsonl(evidence / "raw" / "readiness.jsonl", 33)
    caller = verify_jsonl(evidence / "raw" / "caller-loss-cleanup.jsonl", 20)
    restarts = verify_jsonl(evidence / "raw" / "cleanup-restarts.jsonl", 8)
    reuse = verify_jsonl(evidence / "raw" / "reuse.jsonl", 3)
    routing = verify_jsonl(evidence / "raw" / "routing-overhead.jsonl", 30)

    if any(row["collision_count"] for row in isolation) or any(row["cross_namespace_endpoint_success_count"] for row in isolation):
        fail("isolation collision or cross-namespace success")
    if any(row["peer_marker_read_count"] or row["peer_marker_write_count"] or row["project_visible_forbidden_field_count"] for row in isolation):
        fail("namespace state leak or project-visible provider detail")
    matrix = load(evidence / "authorization-matrix.json")
    if set(matrix["repetitions_by_class"]) != set(thresholds["authorization"]["denial_classes"]) or any(value < 20 for value in matrix["repetitions_by_class"].values()):
        fail("authorization class coverage incomplete")
    if any(matrix[key] for key in ("unauthorized_success_count", "connection_detail_disclosure_count", "route_credential_byte_disclosure_count", "provider_connection_before_authorization_count", "direct_guessed_loopback_success_count")):
        fail("authorization safety gate failed")
    for row in authorization:
        if row["diagnostic_code"] != matrix["expected_diagnostics"][row["denial_class"]]:
            fail("unstable authorization diagnostic")
        if sorted(row["diagnostic_fields"]) != ["code", "consumer_id", "endpoint_id", "namespace_id", "policy_id"]:
            fail("authorization diagnostic field mismatch")

    ready = load(evidence / "readiness-summary.json")
    if ready["sample_count"] != 30 or ready["fixed_sleep_count"] or ready["route_before_successful_health_probe_count"] or ready["route_before_committed_ready_transition_count"]:
        fail("readiness shape or ordering failed")
    if ready["p95_seconds"] >= 1.0 or ready["fault_drain_max_seconds"] > 2.0:
        fail("readiness timing failed")
    cleanup = load(evidence / "cleanup-summary.json")
    if cleanup["caller_loss_trial_count"] != 20 or cleanup["restart_case_count"] != 8:
        fail("cleanup trial count mismatch")
    if cleanup["expiry_detection_lateness_max_seconds"] > 0.5 or cleanup["cleanup_after_expiry_p95_seconds"] > 1.0 or cleanup["cleanup_after_expiry_max_seconds"] > 2.0:
        fail("cleanup timing failed")
    if any(cleanup["remaining_counts"].values()) or cleanup["committed_event_loss_count"] or cleanup["committed_event_duplicate_count"] or cleanup["cleanup_stage_reorder_count"]:
        fail("cleanup residue or durable restart failure")
    for row in caller:
        if row["cleanup_stages"] != ["route.revoked", "service.stopped", "namespace.mutable_state.removed", "lease.finalized"]:
            fail("caller-loss cleanup stage order failed")
    for row in restarts:
        if row["observed_stages"] != ["route.revoked", "service.stopped", "namespace.mutable_state.removed", "lease.finalized"]:
            fail("restart cleanup stage order failed")

    scorecard = load(evidence / "scorecard.json")
    reuse_metrics = scorecard["metrics"]["reuse"]
    if reuse_metrics["namespace_sequence_count"] != 3 or reuse_metrics["immutable_api_artifact_distinct_digest_count"] != 1 or reuse_metrics["immutable_api_artifact_publication_count"] != 1:
        fail("immutable reuse identity failed")
    if any(value for key, value in reuse_metrics.items() if key.startswith("shared_") or key.startswith("prior_")):
        fail("mutable state was reused")
    if len({row["artifact_digest"] for row in reuse}) != 1:
        fail("reuse evidence artifact mismatch")
    if len(routing) != 30 or p95([row["latency_seconds"] for row in routing]) >= 0.025 or p95([row["paired_delta_seconds"] for row in routing]) > 0.01:
        fail("routing overhead gate failed")
    if not scorecard["hard_gate_pass"] or scorecard["selected_branch"] != "explicit-provider-routing" or not scorecard["provider_route_capability_required"]:
        fail("decision precedence not applied")

    verify_benchmark(evidence / "benchmarks" / "endpoint-resolution" / "record.json")
    verify_benchmark(evidence / "benchmarks" / "fake-macos-relay" / "record.json")
    for path, expected in load(evidence / "checksums.json").items():
        if digest(ROOT / path) != expected:
            fail(f"evidence checksum mismatch: {path}")
    manifest = load(evidence / "implementation-manifest.json")
    for item in manifest["files"]:
        if digest(ROOT / item["path"]) != item["sha256"]:
            fail(f"implementation manifest mismatch: {item['path']}")
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in evidence.rglob("*") if path.is_file())
    for forbidden in ("handle_token", "route_token", "service_token", "TASKFLOW_E07_ROUTE_TOKEN", "TASKFLOW_E07_SERVICE_TOKEN"):
        if forbidden in text:
            fail(f"credential-bearing field retained: {forbidden}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-a-only", action="store_true")
    args = parser.parse_args()
    verify_phase_a()
    if not args.phase_a_only:
        verify_phase_b()
    print("E07 Phase A snapshot: PASS" if args.phase_a_only else "E07 Phase B evidence: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"E07 verification: FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
