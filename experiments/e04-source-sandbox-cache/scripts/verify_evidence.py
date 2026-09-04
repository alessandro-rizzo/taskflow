#!/usr/bin/env python3
"""Verify retained E04 probe and benchmark evidence against Phase A."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


EXPERIMENT = Path(__file__).resolve().parents[1]
REPOSITORY = EXPERIMENT.parents[1]
EVIDENCE = EXPERIMENT / "evidence"
PHASE_A_COMMIT = "fe5cb0aa25deb4c10f72dc56e800cfeaac9e363c"

from verify_contract import verify_contract  # noqa: E402


def fail(message: str) -> None:
    raise SystemExit(f"verify-e04-evidence: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"cannot read {path.relative_to(REPOSITORY)}: {error}")
    require(isinstance(value, dict), f"{path.relative_to(REPOSITORY)} must be an object")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_manifest(path: Path, schema: str, expected_paths: list[Path]) -> None:
    manifest = load(path)
    require(manifest.get("schema_version") == schema, f"wrong schema in {path.name}")
    require(manifest.get("phase_a_contract_commit") == PHASE_A_COMMIT, f"wrong Phase A commit in {path.name}")
    entries = manifest.get("files")
    require(isinstance(entries, list), f"{path.name} files must be a list")
    actual_paths = [EXPERIMENT / entry["path"] for entry in entries]
    require(actual_paths == sorted(expected_paths), f"{path.name} path set/order drifted")
    for entry, actual_path in zip(entries, actual_paths):
        require(actual_path.is_file(), f"manifest file missing: {entry['path']}")
        require(sha256(actual_path) == entry.get("sha256"), f"manifest digest mismatch: {entry['path']}")


def verify_implementation_manifest() -> None:
    expected = [
        EXPERIMENT / "Taskfile.yml",
        EXPERIMENT / "e04.py",
        EXPERIMENT / "scripts" / "run_evidence.py",
        EXPERIMENT / "scripts" / "verify_evidence.py",
        EXPERIMENT / "tests" / "test_e04.py",
    ]
    verify_manifest(
        EVIDENCE / "implementation-manifest.json",
        "taskflow-e04-implementation-manifest/v1",
        expected,
    )


def verify_evidence_manifest() -> None:
    expected = sorted(
        path
        for path in EVIDENCE.rglob("*")
        if path.is_file() and path.name != "evidence-manifest.json"
    )
    verify_manifest(
        EVIDENCE / "evidence-manifest.json",
        "taskflow-e04-evidence-manifest/v1",
        expected,
    )


def probe_documents(protocol: dict[str, Any]) -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for declaration in protocol["probes"]:
        path = EXPERIMENT / declaration["evidence_path"]
        document = load(path)
        identifier = declaration["id"]
        require(document.get("schema_version") == "taskflow-e04-probe-evidence/v1", f"{identifier}: wrong schema")
        require(document.get("experiment_id") == "E04", f"{identifier}: wrong experiment")
        require(document.get("id") == identifier, f"{identifier}: id mismatch")
        require(document.get("roadmap_demonstration") == declaration["roadmap_demonstration"], f"{identifier}: roadmap number mismatch")
        require(document.get("phase_a_contract_commit") == PHASE_A_COMMIT, f"{identifier}: Phase A binding mismatch")
        require(document.get("requested_reproducibility") == "isolated", f"{identifier}: requested level mismatch")
        require(document.get("attained_reproducibility") == "observed", f"{identifier}: attained level must remain honest")
        require(document.get("status") == "pass", f"{identifier}: probe did not pass")
        require(isinstance(document.get("limitations"), list) and document["limitations"], f"{identifier}: limitations missing")
        documents[identifier] = document
    return documents


def verify_probe_details(documents: dict[str, dict[str, Any]]) -> None:
    source = documents["source-mutation"]["details"]
    require(source["original_file_digest"] == source["executed_file_digest"], "execution did not consume original captured bytes")
    require(source["captured_source_digest"] != source["fresh_live_digest_after_mutation"], "source mutation did not alter fresh identity")
    require(source["materialized_tree_verified"] is True, "materialized tree was not verified")
    require(source["executed_extra_file_present"] is False and source["mutation_marker_observed"] is False, "post-capture source leaked into execution")

    concurrent = documents["concurrent-output-isolation"]["details"]
    require(concurrent["method"] == "apfs-clone", "concurrent probe did not exercise APFS clone")
    require(concurrent["distinct_workspace_roots"] is True, "concurrent workspaces collided")
    require(concurrent["own_markers_intact"] is True, "concurrent output marker changed")
    require(concurrent["peer_reads_denied"] is True, "peer output remained readable")
    require(concurrent["immutable_base_verified_after_runs"] is True, "immutable base changed")
    for run_id in ("run_a", "run_b"):
        require(all(item["passed"] for item in concurrent[run_id]["commands"]), f"{run_id} W1 command failed")

    ambient = documents["ambient-input-control"]["details"]
    require(ambient["environment_canary_absent"] is True, "undeclared environment value reached child")
    require(ambient["read_denied"] is True, "undeclared read was not denied")
    require(ambient["write_denied"] is True, "undeclared write was not denied")
    require(ambient["sandbox_mechanism"] == "sandbox-exec-targeted-deny", "unexpected sandbox mechanism")

    identity = documents["pre-reservation-identity"]["details"]
    require(identity["mandatory_components"] == [
        "source_manifest",
        "typed_input_manifests",
        "resolved_process_and_arguments",
        "execution_profile",
        "sandbox_policy",
        "dependency_manifests",
    ], "identity component set changed")
    require(identity["all_mutations_change_identity"] is True, "identity mutation sensitivity failed")
    require(identity["missing_components_rejected"] is True, "incomplete identity was accepted")
    require(identity["key_before_lookup"] is True and identity["lookup_before_reservation"] is True, "cache ordering failed")

    hit = documents["zero-reservation-cache-hit"]["details"]
    require(hit["sample_count"] == 30, "ready-hit probe must retain 30 traces")
    require(hit["all_resource_counters_zero"] is True, "ready hit consumed resources")
    require(hit["forbidden_events_absent"] is True, "ready hit emitted provisioning events")
    for trace in hit["traces"]:
        require(not any(trace["counters"].values()), "ready-hit trace contains a nonzero counter")

    mismatch = documents["attestation-mismatch"]["details"]
    require(mismatch["status"] == "attestation-mismatch", "attestation mismatch did not fail closed")
    require(mismatch["identity_unchanged"] is True, "attestation mismatch re-keyed the node")
    require(mismatch["sandbox_execution_publication_absent"] is True, "attestation mismatch continued execution")
    require(mismatch["counters"]["reservations"] == 1 and mismatch["counters"]["sandboxes"] == 0, "attestation counters changed")

    separation = documents["cache-class-separation"]["details"]
    require(len(set(separation["classes"].values())) == 3, "cache classes share a type")
    require(separation["poisoned_tool_cache_created_result_hit"] is False, "tool cache authorized a result hit")
    require(separation["warm_workers_created_result_hit"] is False, "warm state authorized a result hit")
    require(separation["result_hit_without_tool_or_warm_state"] is True, "result hit depended on performance caches")


def computed_statistics(samples: list[float]) -> tuple[float, float]:
    ordered = sorted(samples)
    count = len(ordered)
    median = ordered[count // 2] if count % 2 else (ordered[count // 2 - 1] + ordered[count // 2]) / 2
    p95_index = math.floor(0.95 * (count - 1) + 0.5)
    return median, ordered[p95_index]


def verify_benchmarks(protocol: dict[str, Any]) -> dict[str, dict[str, Any]]:
    paths = {
        "local-warm-sandbox-creation-apfs": EVIDENCE / "benchmarks" / "apfs-clone-warm" / "record.json",
        "local-warm-sandbox-creation-copy-control": EVIDENCE / "benchmarks" / "copy-warm" / "record.json",
        "ready-cache-hit-after-planning": EVIDENCE / "benchmarks" / "ready-cache-hit" / "record.json",
    }
    records: dict[str, dict[str, Any]] = {}
    metric_contracts = {item["id"]: item for item in protocol["measurements"]["metrics"]}
    for metric_id, path in paths.items():
        record = load(path)
        contract = metric_contracts[metric_id]
        require(record.get("schema_version") == "taskflow-t1-benchmark/v2", f"{metric_id}: wrong benchmark schema")
        require(record.get("experiment_id") == "E04", f"{metric_id}: wrong experiment")
        require(record.get("fixture_id") == "w1-fast-project-check", f"{metric_id}: wrong fixture")
        require(record.get("source_revision") == PHASE_A_COMMIT, f"{metric_id}: wrong source revision")
        require(record.get("sample_count") == contract["sample_count"] == len(record.get("samples", [])), f"{metric_id}: sample count mismatch")
        require(record.get("preparation_command"), f"{metric_id}: preparation command missing")
        median, p95 = computed_statistics(record["samples"])
        require(abs(record["median"] - median) < 1e-12, f"{metric_id}: median mismatch")
        require(abs(record["p95"] - p95) < 1e-12, f"{metric_id}: p95 mismatch")
        threshold = contract["threshold"]
        if threshold is not None:
            require(record["p95"] < threshold["seconds"], f"{metric_id}: p95 {record['p95']} missed {threshold['seconds']}")
        records[metric_id] = record

    hit = records["ready-cache-hit-after-planning"]
    require(hit.get("reservation_count") == 0, "ready-hit benchmark reservation_count is not zero")
    require("prepare-cache-hit" in hit["preparation_command"], "ready-hit state was not prepared outside the timer")
    execution = load(EVIDENCE / "execution.json")
    hit_runs = [item for item in execution.get("benchmark_runs", []) if item.get("metric_id") == "ready-cache-hit-after-planning"]
    require(len(hit_runs) == 1, "ready-hit execution command is missing or duplicated")
    require("benchmark-cache-hit" in hit_runs[0].get("command", ""), "ready-hit benchmark command drifted")
    require(hit_runs[0].get("prepare") == hit["preparation_command"], "ready-hit preparation record drifted")
    trace_path = EVIDENCE / "benchmarks" / "ready-cache-hit" / "traces.jsonl"
    traces = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line]
    require(len(traces) == 30, "ready-hit benchmark must retain 30 per-sample traces")
    forbidden = {"reserve-worker", "acquire-worker", "attest-worker-profile", "create-sandbox", "execute"}
    for trace in traces:
        require(not any(trace["counters"].values()), "timed ready-hit trace consumed a resource")
        require(not (forbidden & {event["kind"] for event in trace["events"]}), "timed ready-hit trace provisioned work")
    return records


def verify_no_canary_leak() -> None:
    forbidden = [b"environment-canary-must-not-persist", b"path-canary-must-not-persist", b"peer-secret"]
    for path in EVIDENCE.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            for marker in forbidden:
                require(marker not in data, f"secret canary leaked into {path.relative_to(EXPERIMENT)}")


def verify_summary(records: dict[str, dict[str, Any]]) -> None:
    summary = load(EVIDENCE / "summary.json")
    require(summary.get("experiment_id") == "E04", "summary experiment changed")
    require(summary.get("attained_reproducibility") == "observed", "summary overclaims reproducibility")
    require(summary.get("selected_branch") == "native-fast-incomplete", "unexpected decision branch")
    require(summary.get("local_warm_sandbox_p95_seconds") == records["local-warm-sandbox-creation-apfs"]["p95"], "summary sandbox p95 drifted")
    require(summary.get("ready_cache_hit_p95_seconds") == records["ready-cache-hit-after-planning"]["p95"], "summary hit p95 drifted")
    require(summary.get("ready_cache_hit_reservations") == 0, "summary reservations changed")


def main() -> None:
    digest = verify_contract(False)
    protocol = load(EXPERIMENT / "protocol.json")
    verify_implementation_manifest()
    documents = probe_documents(protocol)
    verify_probe_details(documents)
    records = verify_benchmarks(protocol)
    verify_summary(records)
    verify_no_canary_leak()
    verify_evidence_manifest()
    print(f"verify-e04-evidence: PASS protocol_sha256={digest}")


if __name__ == "__main__":
    main()
