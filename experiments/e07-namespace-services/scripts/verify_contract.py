#!/usr/bin/env python3
"""Verify the frozen, result-free E07 Phase A contract."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


EXPERIMENT = Path(__file__).resolve().parents[1]
REPOSITORY = EXPERIMENT.parents[1]

EXPECTED_FILES = {
    "README.md",
    "Taskfile.yml",
    "contract.json",
    "decision-matrix.json",
    "event-schema.json",
    "fixture-bindings.json",
    "frozen-artifacts.json",
    "protocol.sha256",
    "scripts/verify_contract.py",
    "tests/test_verify_contract.py",
    "thresholds.json",
}
FROZEN_FILES = EXPECTED_FILES - {"frozen-artifacts.json", "protocol.sha256"}

EXPECTED_BINDINGS = {
    "fixtures/w3/spec.md": "3604c22837c2c377309c4d08b1eeeef862fc150b195b545bed981745fd1768a4",
    "fixtures/w3/examples/namespace-a.json": "b86378913dcc9f7e80c8a47cf387f68a5a6130d88592fa02be72229e85a3583e",
    "fixtures/w3/examples/namespace-b.json": "22db508434c6997cc8ec4bd9b0dee4bc0a01181380ca196e0abb875c865ab682",
    "fixtures/w3/examples/scenario-caller-loss.json": "88fbb5623f79bfcf572759bfe6f16a5371a423f24b098969a0194923b33800cc",
    "fixtures/w3/examples/scenario-cancellation.json": "5e043f9f043748f22bc5a0f5a220b883fe7fcec7912400286723fb2442ac4b01",
    "fixtures/w3/examples/scenario-dirty-warm-infrastructure.json": "e319dc7d35df836f6b792901de028226872161be051db503f6c97ebde7dde87b",
    "fixtures/w3/examples/scenario-port-collision.json": "fd8da59e371f2eb3f38342f23bccfd728f348b99703cffaf7e7516cac8124560",
    "fixtures/w3/examples/scenario-simulator-profile-mismatch.json": "09898335565236d4f3856cfa03deaf826a9e8e3e9e61bc48e33635ec2d70f40a",
    "fixtures/w3/examples/scenario-unauthorized-routing.json": "a4f79da3f856f34e1c06039c00ba7126b006e9bde4e7b708895ed4771de968b3",
    "fixtures/t1-lifecycle-faults/lease.go": "a915fad64df70c10e6d31aac4557bf7198c347a60565a951a4b45fc5ffd14b6d",
    "fixtures/t1-lifecycle-faults/lease_state.go": "4a70cb20e995f9d4b69e29a561c04e3f856113d50c6bef7e557b4e76a1e42e23",
    "fixtures/t1-lifecycle-faults/scenario_lease_expiry_test.go": "dfa49e57b4d277479e887c422edb69040ecfe0e423572d728ff2754bc9b23d90",
    "experiments/e02-plan-ir/evidence/raw/canonical/w3.json": "35cbc9f8bf8af5e15095b61a55dc753e84877d6bd1b25644f27e02ceca2239f0",
    "docs/decisions/0006-e02-plan-ir.md": "5128c2ce46531da9a4c21aca1a82f6f005a096ff7ca134622dcde8fc811ae29c",
    "experiments/e05-daemon-simulation/results/lifecycle.json": "1e01cb9185be383e2759a9964aa397e1f5a6d11eede61a51d2cb576da0dbf5ed",
    "experiments/e05-daemon-simulation/thresholds.json": "860bbb206d73d76ab9b2c93efdbd5276df4251b2e9ff164fb1274d50b14ec8f5",
    "experiments/e05-daemon-simulation/decision.md": "2d2bca7a83995c6ca3863f030428641e925adc7a46aeb509bfc82f2b8ba63552",
    "experiments/e05-daemon-simulation/limitations.md": "036f82723d29b2907b39cd38b4a165dc3c5dfdac18c6fd6003658681b0a470be",
    "experiments/e06-macos-feasibility/contract.json": "e504372b6887b94fba46a341bfa7faf8bcb9a032bd503ca3fe20da93c66a74df",
    "experiments/e06-macos-feasibility/candidate-matrix.json": "43422a12603f0f9480d7c701e09d0e31772998ab80aa22f94363e56609762fbe",
    "fixtures/t1-benchmark-harness/record.go": "b0bb479abc9d2095d3f8f3067001125312c0be98d5ed67f3b295b72a13f0a659",
    "fixtures/t1-benchmark-harness/validate.go": "07dedcd217927500b6a9758aeaf8c6ebf9b780e4ab66b8577ced793ef57d071a",
}

EXPECTED_THRESHOLD_SECTIONS = {
    "isolation": {
        "paired_namespace_trial_count": 20,
        "namespace_count_per_trial": 2,
        "service_name_collision_count_max": 0,
        "allocated_port_collision_count_max": 0,
        "writable_root_collision_count_max": 0,
        "database_path_collision_count_max": 0,
        "endpoint_id_collision_count_max": 0,
        "lease_id_collision_count_max": 0,
        "route_capability_id_collision_count_max": 0,
        "mutable_object_identity_collision_count_max": 0,
        "peer_marker_read_count_max": 0,
        "peer_marker_write_count_max": 0,
        "cross_namespace_endpoint_success_count_max": 0,
        "project_visible_forbidden_field_count_max": 0,
    },
    "authorization": {
        "denial_classes": [
            "wrong-endpoint-type",
            "foreign-consumer",
            "forged-handle",
            "missing-capability",
            "stale-handle",
            "provider-mismatch",
        ],
        "repetitions_per_class_min": 20,
        "unauthorized_success_count_max": 0,
        "connection_detail_disclosure_count_max": 0,
        "route_credential_byte_disclosure_count_max": 0,
        "provider_connection_before_authorization_count_max": 0,
        "required_diagnostic_fields": ["code", "endpoint_id", "consumer_id", "namespace_id", "policy_id"],
    },
    "readiness": {
        "serial_sample_count": 30,
        "fixed_sleep_count_max": 0,
        "route_before_successful_health_probe_count_max": 0,
        "route_before_committed_ready_transition_count_max": 0,
        "process_start_to_committed_ready_p95_seconds_strictly_less_than": 1.0,
        "unhealthy_or_early_exit_drain_max_seconds": 2.0,
    },
    "caller_loss_cleanup": {
        "trial_count": 20,
        "lease_ttl_seconds": 1.0,
        "heartbeat_interval_seconds": 0.25,
        "reaper_interval_seconds": 0.1,
        "expiry_detection_lateness_max_seconds": 0.5,
        "cleanup_after_expiry_p95_seconds_max": 1.0,
        "cleanup_after_expiry_max_seconds_max": 2.0,
        "remaining_process_count_max": 0,
        "remaining_listener_count_max": 0,
        "remaining_route_count_max": 0,
        "remaining_lease_count_max": 0,
        "remaining_mutable_namespace_path_count_max": 0,
        "cleanup_stages": ["route.revoked", "service.stopped", "namespace.mutable_state.removed", "lease.finalized"],
        "restart_timings_per_stage": ["before-commit", "after-commit"],
        "committed_event_loss_count_max": 0,
        "committed_event_duplicate_count_max": 0,
        "cleanup_stage_reorder_count_max": 0,
    },
    "reuse": {
        "namespace_sequence_count": 3,
        "immutable_api_artifact_distinct_digest_count": 1,
        "immutable_api_artifact_publication_count": 1,
        "shared_mutable_database_count_max": 0,
        "shared_route_credential_count_max": 0,
        "shared_service_process_count_max": 0,
        "shared_route_count_max": 0,
        "prior_namespace_marker_visible_count_max": 0,
    },
    "routing_overhead": {
        "serial_paired_sample_count": 30,
        "sample_order": "alternate direct-loopback-first and fake-macos-relay-first",
        "authorized_endpoint_resolution_p95_seconds_strictly_less_than": 0.025,
        "fake_macos_relay_paired_p95_delta_seconds_max": 0.01,
    },
}

EXPECTED_DECISION_IDS = [
    "stop-narrow-safety",
    "typed-endpoint-manager",
    "explicit-provider-routing",
    "compose-style-integration",
    "stop-narrow-no-credible-candidate",
]
EXPECTED_DIAGNOSTICS = [
    "E07_ENDPOINT_TYPE_MISMATCH",
    "E07_CONSUMER_NOT_AUTHORIZED",
    "E07_ENDPOINT_HANDLE_INVALID",
    "E07_ROUTE_CAPABILITY_MISSING",
    "E07_ENDPOINT_HANDLE_STALE",
    "E07_PROVIDER_MISMATCH",
]
EXPECTED_EVIDENCE_PATHS = [
    "evidence/raw/paired-namespaces.jsonl",
    "evidence/raw/authorization.jsonl",
    "evidence/raw/readiness.jsonl",
    "evidence/raw/caller-loss-cleanup.jsonl",
    "evidence/raw/cleanup-restarts.jsonl",
    "evidence/raw/reuse.jsonl",
    "evidence/raw/routing-overhead.jsonl",
    "evidence/process-listener-inventory.json",
    "evidence/namespace-leak-collision-report.json",
    "evidence/authorization-matrix.json",
    "evidence/readiness-summary.json",
    "evidence/cleanup-summary.json",
    "evidence/benchmarks/endpoint-resolution/record.json",
    "evidence/benchmarks/endpoint-resolution/samples.txt",
    "evidence/benchmarks/fake-macos-relay/record.json",
    "evidence/benchmarks/fake-macos-relay/samples.txt",
    "evidence/environment.json",
    "evidence/execution.json",
    "evidence/checksums.json",
    "evidence/implementation-manifest.json",
    "evidence/evidence-manifest.json",
    "evidence/scorecard.json",
    "evidence/limitations.md",
    "evidence/recommendation.md",
]


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"cannot read {path}: {error}") from error
    require(isinstance(value, dict), f"{path} must contain a JSON object")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc" and path.name != ".DS_Store"
    }


def verify_fileset(experiment: Path) -> None:
    found = relative_files(experiment)
    require(found == EXPECTED_FILES, f"Phase A fileset mismatch: missing={sorted(EXPECTED_FILES - found)} extra={sorted(found - EXPECTED_FILES)}")


def verify_contract(experiment: Path) -> None:
    contract = load_object(experiment / "contract.json")
    require(contract.get("format_version") == "taskflow-e07-phase-a-contract/v1-experimental", "contract format drifted")
    require(contract.get("status") == "phase-a-result-free-frozen", "contract must remain result-free")
    require(contract.get("baseline_revision") == "098035bf29656c3fd3b3991224a98fdded3453b7", "baseline revision drifted")
    require(contract.get("risks") == ["R7"], "risk mapping drifted")
    canonical = contract.get("canonical_requirements", {})
    require(canonical.get("targeted") == ["AGENT-4", "AGENT-5", "EXEC-5"], "canonical requirements drifted")
    require(sorted(canonical.get("partially_exercised", {})) == ["AGENT-6", "EXEC-1", "PLAN-5"], "partial requirement mapping drifted")
    stale = [f"NS-{index}" for index in range(1, 6)]
    require(canonical.get("stale_ticket_references") == stale, "stale NS provenance drifted")
    without_stale = json.loads(json.dumps(contract))
    without_stale["canonical_requirements"].pop("stale_ticket_references", None)
    require(not any(item in json.dumps(without_stale) for item in stale), "stale NS label leaked into canonical contract")
    phase = contract.get("phase_boundary", {})
    require("service process or endpoint listener" in phase.get("phase_a_forbids", []), "Phase A must forbid services and listeners")
    require("benchmark or evidence generation" in phase.get("phase_a_forbids", []), "Phase A must forbid measurements")
    require("reviewed and explicitly authorized Phase A contract commit" in phase.get("phase_b_preconditions", []), "Phase B commit precondition drifted")
    workload = contract.get("workload", {})
    require(workload.get("paired_namespace_trials") == 20 and workload.get("barrier_synchronised") is True, "paired workload drifted")
    subsets = workload.get("subsets", [])
    require(len(subsets) == 2, "workload must contain exactly two namespace subsets")
    expected_request_keys = {"source_id", "service_type", "endpoint_type", "consumer_id"}
    forbidden = set(workload.get("forbidden_project_fields", []))
    require(forbidden == {"port", "host", "route", "token", "credential", "writable_root", "database_path", "process", "provider_options"}, "forbidden project-field set drifted")
    for subset in subsets:
        require(subset.get("service_target_class") == "linux", "service target must remain Linux-class")
        require(subset.get("consumer_target_class") == "fake-macos", "consumer target must remain fake-macOS")
        request = subset.get("project_visible_request", {})
        require(set(request) == expected_request_keys, "project-visible request leaked a field")
        require(request.get("service_type") == "Service[API]" and request.get("endpoint_type") == "Endpoint[API]", "typed W3 request drifted")
        require(not (set(request) & forbidden), "project-visible request contains forbidden infrastructure detail")
    shape = contract.get("phase_b_shape", {})
    require(shape.get("cleanup_stages") == EXPECTED_THRESHOLD_SECTIONS["caller_loss_cleanup"]["cleanup_stages"], "cleanup shape drifted")
    require(shape.get("forbidden_external_mechanisms") == ["VM", "simulator", "external provider", "public network"], "external mechanism boundary drifted")
    require(contract.get("verification_command") == "mise exec -- task --dir experiments/e07-namespace-services check:phase-a", "verification command drifted")


def verify_bindings(experiment: Path, repository: Path) -> None:
    document = load_object(experiment / "fixture-bindings.json")
    require(document.get("source_revision") == "098035bf29656c3fd3b3991224a98fdded3453b7", "binding revision drifted")
    observed: dict[str, str] = {}
    for binding in document.get("bindings", []):
        for item in binding.get("files", []):
            path = item.get("path")
            digest = item.get("sha256")
            require(isinstance(path, str) and path not in observed, f"duplicate or invalid binding path: {path}")
            observed[path] = digest
    require(observed == EXPECTED_BINDINGS, "fixture binding set or declared digest drifted")
    for path, expected in EXPECTED_BINDINGS.items():
        actual = sha256(repository / path)
        require(actual == expected, f"fixture drift: {path}: want {expected}, got {actual}")


def verify_thresholds(experiment: Path) -> None:
    document = load_object(experiment / "thresholds.json")
    require(document.get("format_version") == "taskflow-e07-thresholds/v1-experimental", "threshold format drifted")
    statistics = document.get("statistics", {})
    require(statistics.get("p95_method") == "sort ascending and select index round(0.95*(n-1))", "p95 method drifted")
    require(statistics.get("execution_order") == "serial except for the explicitly barrier-synchronised two-namespace isolation trial", "execution order drifted")
    for section, expected in EXPECTED_THRESHOLD_SECTIONS.items():
        require(document.get(section) == expected, f"{section} thresholds drifted")


def verify_decision(experiment: Path) -> None:
    document = load_object(experiment / "decision-matrix.json")
    require(document.get("status") == "predeclared-no-selection" and document.get("selected_branch") is None, "Phase A must not select a branch")
    entries = document.get("precedence", [])
    require([entry.get("id") for entry in entries] == EXPECTED_DECISION_IDS, "decision precedence drifted")
    require([entry.get("order") for entry in entries] == list(range(1, 6)), "decision order drifted")
    rules = document.get("candidate_credit_rules", {})
    require(rules == {
        "command_presence_is_execution_evidence": False,
        "static_compose_file_is_execution_evidence": False,
        "unapproved_shared_runtime_is_eligible": False,
        "threshold_changes_after_evidence_are_allowed": False,
        "project_visible_provider_option_count_max": 0,
    }, "candidate credit rules drifted")
    require(document.get("adr_path") == "docs/decisions/0011-e07-namespace-services.md", "ADR path drifted")


def verify_event_schema(experiment: Path) -> None:
    document = load_object(experiment / "event-schema.json")
    require(document.get("ordering_rule") == "Persist the durable mutation before emitting the event that describes it.", "event durability ordering drifted")
    require(document.get("common_required_fields") == ["format_version", "sequence", "event", "run_id", "namespace_id", "monotonic_seconds"], "common event fields drifted")
    require(document.get("stable_diagnostic_codes") == EXPECTED_DIAGNOSTICS, "diagnostic codes drifted")
    credential = document.get("credential_policy", {})
    require(credential == {
        "raw_route_credentials_allowed": False,
        "raw_tokens_allowed": False,
        "retained_representation": "sha256 digest only",
        "digest_field": "capability_digest",
    }, "credential evidence policy drifted")
    evidence = document.get("phase_b_evidence", {})
    require(evidence.get("required_paths") == EXPECTED_EVIDENCE_PATHS, "required evidence paths drifted")
    require(evidence.get("exact_reproduction_command_required") is True, "reproduction command requirement drifted")
    require(evidence.get("failed_sets_retained") is True and evidence.get("normalized_jsonl_required") is True, "raw evidence retention drifted")


def verify_frozen_artifacts(experiment: Path) -> None:
    manifest = load_object(experiment / "frozen-artifacts.json")
    require(manifest.get("format_version") == "taskflow-e07-frozen-artifacts/v1-experimental", "frozen manifest format drifted")
    artifacts = manifest.get("artifacts", [])
    paths = [item.get("path") for item in artifacts]
    require(paths == sorted(FROZEN_FILES), "frozen artifact set or order drifted")
    for item in artifacts:
        digest = item.get("sha256")
        require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None, f"invalid frozen digest: {item.get('path')}")
        actual = sha256(experiment / item["path"])
        require(actual == digest, f"frozen artifact drift: {item['path']}: want {digest}, got {actual}")
    line = (experiment / "protocol.sha256").read_text(encoding="utf-8").strip()
    match = re.fullmatch(r"([0-9a-f]{64})  frozen-artifacts\.json", line)
    require(match is not None, "protocol.sha256 must contain one frozen-artifacts.json entry")
    actual = sha256(experiment / "frozen-artifacts.json")
    require(match.group(1) == actual, f"frozen manifest digest mismatch: want {match.group(1)}, got {actual}")


def verify(experiment: Path = EXPERIMENT, repository: Path = REPOSITORY) -> None:
    verify_fileset(experiment)
    verify_contract(experiment)
    verify_bindings(experiment, repository)
    verify_thresholds(experiment)
    verify_decision(experiment)
    verify_event_schema(experiment)
    verify_frozen_artifacts(experiment)


def main() -> int:
    try:
        verify()
    except (OSError, VerificationError) as error:
        print(f"verify-e07-contract: {error}", file=sys.stderr)
        return 1
    print("verify-e07-contract: result-free Phase A contract valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
