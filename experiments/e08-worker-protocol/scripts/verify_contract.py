#!/usr/bin/env python3
"""Verify the frozen E08 Phase A worker-protocol contract."""

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
    "envelopes.schema.json",
    "fault-matrix.json",
    "fixture-bindings.json",
    "frozen-artifacts.json",
    "protocol.sha256",
    "scripts/verify_contract.py",
    "ssh-availability-manifest.schema.json",
    "state-machines.json",
    "tests/test_verify_contract.py",
    "thresholds.json",
}
FROZEN_FILES = EXPECTED_FILES - {"frozen-artifacts.json", "protocol.sha256"}
PHASE_B_NAMES = {
    "adapter",
    "adapters",
    "cmd",
    "decision.md",
    "evidence",
    "go.mod",
    "go.sum",
    "implementation",
    "results",
    "scorecard.json",
    "ssh-availability.json",
    "worker",
}

CANONICAL_REQUIREMENTS = [
    "EXEC-1", "EXEC-2", "EXEC-3", "EXEC-4", "EXEC-5", "REP-1",
    "REP-3", "REP-4", "REP-5", "REP-6", "AGENT-3", "AGENT-5",
    "DUR-1", "DUR-3",
]
STALE_REQUIREMENTS = [f"REM-{index}" for index in range(1, 6)]

OPERATION_GROUPS = {
    "discovery_and_capacity": ["AdvertiseCapabilities", "TryReserve", "AcquireWorker"],
    "identity_and_lifecycle": ["AttestProfile", "CreateSandbox", "AcquireSession"],
    "cas": ["CASHas", "CASPutChunk", "CASGetChunk"],
    "execution": ["Exec", "ReadLogs", "Cancel", "WaitExit"],
    "publication_and_cleanup": ["PublishOutputs", "Cleanup"],
    "continuity": ["Heartbeat", "Reconnect", "QueryOrphans"],
}

FAULT_IDS = [
    "ready-cache-hit-before-reservation",
    "capability-profile-mismatch-before-reservation",
    "provider-unavailable-before-acquisition",
    "attested-profile-mismatch",
    "cas-missing-blob",
    "cas-corrupted-chunk",
    "cas-final-object-digest-mismatch",
    "cas-partial-materialization",
    "cas-manifest-tamper",
    "disconnect-before-exec-acknowledgement",
    "disconnect-during-log-stream",
    "disconnect-during-publication",
    "disconnect-during-cleanup",
    "permanent-worker-loss",
    "cancel-before-placement",
    "cancel-while-running",
    "command-non-zero-exit",
    "duplicate-or-reordered-command",
    "stale-reconnect-token",
    "output-collection-failure",
    "output-digest-failure",
    "atomic-publication-failure",
    "cleanup-timeout",
    "caller-loss-lease-expiry",
    "orphan-query-and-reconcile",
    "w2-compatible-worker-resume",
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
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise VerificationError(f"cannot hash {path}: {error}") from error


def relative_files(experiment: Path) -> set[str]:
    return {
        path.relative_to(experiment).as_posix()
        for path in experiment.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
        and path.name != ".DS_Store"
    }


def verify_fileset(experiment: Path) -> None:
    found = relative_files(experiment)
    require(
        found == EXPECTED_FILES,
        f"Phase A fileset mismatch: missing={sorted(EXPECTED_FILES - found)} extra={sorted(found - EXPECTED_FILES)}",
    )
    for path in experiment.rglob("*"):
        if path.is_file():
            require(path.suffix != ".go", f"Phase B Go source is forbidden: {path}")
        require(path.name not in PHASE_B_NAMES, f"Phase B artifact is forbidden: {path.name}")


def verify_contract(experiment: Path, repository: Path) -> dict[str, Any]:
    contract = load_object(experiment / "contract.json")
    require(contract.get("status") == "phase-a-contract-frozen", "contract status drifted")
    require(
        contract.get("baseline_revision") == "098035bf29656c3fd3b3991224a98fdded3453b7",
        "baseline revision drifted",
    )
    require(contract.get("risks") == ["R5", "R9"], "risk mapping drifted")
    canonical = contract.get("canonical_requirements", {})
    require(canonical.get("specified_by_phase_a") == CANONICAL_REQUIREMENTS, "canonical requirement mapping drifted")
    require(canonical.get("stale_ticket_references") == STALE_REQUIREMENTS, "stale REM provenance drifted")
    require(not any(item.startswith("REM-") for item in canonical.get("specified_by_phase_a", [])), "stale REM label became canonical")
    require(contract.get("typed_operation_groups") == OPERATION_GROUPS, "typed operation groups drifted")
    phase = contract.get("phase_boundary", {})
    forbidden = phase.get("phase_a_forbids", [])
    for phrase in (
        "Go module or worker and adapter source",
        "SSH or provider connection",
        "local remote VM simulator or shared resource mutation",
        "selected E08 decision branch",
    ):
        require(phrase in forbidden, f"Phase A prohibition missing: {phrase}")
    identity = contract.get("identity_and_ordering", {})
    for key in (
        "cache_key_ready_before_reservation",
        "ready_hit_terminal_before_capacity",
        "attestation_before_sandbox_or_session",
        "integrity_verification_before_use",
        "publication_atomic_after_output_verification",
        "planned_profile_rewrite_forbidden",
    ):
        require(identity.get(key) is True, f"identity/order invariant drifted: {key}")
    require(identity.get("cache_classes") == ["result", "tool", "warm-provider"], "cache classes drifted")
    extensions = contract.get("provider_extension_policy", {})
    require(extensions.get("open_option_maps_forbidden") is True, "open provider options must remain forbidden")
    require(extensions.get("project_visible_provider_fields_forbidden") is True, "provider fields leaked toward project plans")
    transport = contract.get("transport_policy", {})
    require(transport.get("status") == "experimental-and-unselected", "transport was selected prematurely")
    require(transport.get("state_machine_precedes_transport") is True, "state machine must precede transport")
    ssh = contract.get("ssh_boundary", {})
    require(ssh.get("status") == "external-blocker", "SSH must remain an external blocker in Phase A")
    require(ssh.get("availability_manifest") is None, "Phase A must not claim an SSH availability manifest")
    require(ssh.get("representative_endpoint_approved") is False, "Phase A must not claim SSH approval")

    product = (repository / "docs/product-specification.md").read_text(encoding="utf-8")
    roadmap = (repository / "docs/roadmap.md").read_text(encoding="utf-8")
    anchors = [
        "- **EXEC-3:** Workers and disposable sandboxes are separate lifecycles.",
        "- **EXEC-4:** Profile identity is known before provisioning and attested at",
        "- **REP-4:** Ready cache hits return before worker reservation.",
        "- **DUR-3:** Cancellation triggers bounded cleanup and records orphans.",
    ]
    for anchor in anchors:
        require(anchor in product, f"product anchor drifted: {anchor}")
    require("### E08: minimal remote worker protocol" in roadmap, "E08 roadmap anchor drifted")
    require("- warm remote Linux sandbox admission: p95 below 2 seconds, excluding queueing;" in roadmap, "remote admission budget drifted")
    require("- W1 cache hit after planning: p95 below 300 ms and zero worker reservations;" in roadmap, "cache-hit budget drifted")
    return contract


def verify_fixture_bindings(experiment: Path, repository: Path) -> None:
    manifest = load_object(experiment / "fixture-bindings.json")
    require(manifest.get("source_revision") == "098035bf29656c3fd3b3991224a98fdded3453b7", "binding source revision drifted")
    bindings = manifest.get("bindings")
    require(isinstance(bindings, list), "bindings must be a list")
    expected = {
        "w2-cross-target-artifact-pipeline": ("t1-w2-experimental-v1", 7),
        "integrity-faults": ("t1-integrity-faults-v2-experimental", 8),
        "e04-cache-profile-evidence": ("taskflow-e04-phase-a-protocol/v1", 8),
        "e06-macos-lifecycle-shape": ("taskflow-e06-phase-a-contract/v1-experimental", 8),
        "t1-benchmark-harness": ("taskflow-t1-benchmark/v2", 4),
    }
    require([item.get("id") for item in bindings] == list(expected), "binding set/order drifted")
    all_paths: list[str] = []
    for binding in bindings:
        version, count = expected[binding["id"]]
        require(binding.get("version") == version, f"binding version drifted: {binding['id']}")
        files = binding.get("files")
        require(isinstance(files, list) and len(files) == count, f"binding file count drifted: {binding['id']}")
        paths = [item.get("path") for item in files]
        require(paths == sorted(paths), f"binding paths must be sorted: {binding['id']}")
        for item in files:
            relative = item.get("path")
            expected_digest = item.get("sha256")
            require(isinstance(relative, str) and ".." not in Path(relative).parts, f"unsafe binding path: {relative}")
            require(isinstance(expected_digest, str) and re.fullmatch(r"[0-9a-f]{64}", expected_digest) is not None, f"invalid binding digest: {relative}")
            require(sha256(repository / relative) == expected_digest, f"bound input drifted: {relative}")
            all_paths.append(relative)
    require(len(all_paths) == len(set(all_paths)), "bound input appears more than once")
    w2_paths = [path for path in all_paths if path.startswith("fixtures/w2/")]
    require(len(w2_paths) == 7 and len([path for path in w2_paths if "/golden/" in path]) == 5, "complete W2 binding missing")


def verify_state_machines(experiment: Path) -> None:
    document = load_object(experiment / "state-machines.json")
    machines = document.get("machines")
    require(isinstance(machines, list), "machines must be a list")
    expected_ids = ["node-attempt", "reservation", "worker-attachment", "sandbox", "session", "publication"]
    require([machine.get("id") for machine in machines] == expected_ids, "machine set/order drifted")
    for machine in machines:
        states = machine.get("states")
        transitions = machine.get("transitions")
        require(isinstance(states, list) and len(states) == len(set(states)), f"invalid states: {machine.get('id')}")
        require(machine.get("initial") in states, f"initial state missing: {machine.get('id')}")
        require(set(machine.get("terminal", [])).issubset(states), f"terminal state missing: {machine.get('id')}")
        require(isinstance(transitions, list) and transitions, f"transitions missing: {machine.get('id')}")
        seen: set[tuple[str, str, str]] = set()
        for transition in transitions:
            edge = (transition.get("from"), transition.get("event"), transition.get("to"))
            require(edge[0] in states and edge[2] in states, f"transition references unknown state: {machine.get('id')} {edge}")
            require(edge not in seen, f"duplicate transition: {machine.get('id')} {edge}")
            seen.add(edge)
    by_id = {machine["id"]: machine for machine in machines}
    node = by_id["node-attempt"]
    node_edges = {(item["from"], item["event"], item["to"]) for item in node["transitions"]}
    required_sequence = {
        ("ready", "cache_lookup_started", "cache_lookup"),
        ("cache_lookup", "verified_result_found", "cache_hit"),
        ("cache_lookup", "result_absent_or_invalid", "reservation_requested"),
        ("worker_acquired", "profile_attested", "attested"),
        ("attested", "sandbox_created", "sandbox_created"),
        ("executing", "exit_succeeded", "publishing"),
        ("publishing", "outputs_published", "succeeded"),
        ("cleaning", "cleanup_deadline_exceeded", "cleanup_warning"),
        ("cleanup_warning", "orphan_recorded", "orphaned"),
    }
    require(required_sequence.issubset(node_edges), "node semantic sequence drifted")
    require("cache_hit" in node.get("terminal", []), "ready hit must terminate before capacity")
    require(by_id["session"].get("optional") is True, "session must remain optional")
    require("Stateless Linux does not synthesize a session." in by_id["session"].get("invariants", []), "Linux session separation drifted")
    cache_forbidden = document.get("cache_hit_forbidden_events", [])
    require(set(cache_forbidden) >= {"try_reserve", "worker_wake", "acquire", "profile_match", "create", "execution_started", "outputs_published"}, "cache-hit forbidden events drifted")


def verify_envelopes(experiment: Path) -> None:
    schema = load_object(experiment / "envelopes.schema.json")
    require(schema.get("additionalProperties") is False, "top-level envelope must be closed")
    defs = schema.get("$defs", {})
    operation_defs = [
        "advertiseCapabilities", "tryReserve", "acquireWorker", "attestProfile",
        "createSandbox", "acquireSession", "casHas", "casPutChunk", "casGetChunk",
        "exec", "readLogs", "cancel", "waitExit", "publishOutputs", "cleanup",
        "heartbeat", "reconnect", "queryOrphans",
    ]
    expected_operations = [name for values in OPERATION_GROUPS.values() for name in values]
    actual_operations = []
    for name in operation_defs:
        definition = defs.get(name, {})
        require(definition.get("additionalProperties") is False, f"operation payload must be closed: {name}")
        actual_operations.append(definition.get("properties", {}).get("kind", {}).get("const"))
    require(actual_operations == expected_operations, "typed operation schema set/order drifted")
    require("payload_digest" in schema.get("required", []), "payload digest must be required for idempotency")
    text = json.dumps(schema, sort_keys=True).lower()
    for forbidden in ("provider_options", "provideroptions", "map[string]any", "credentials", "secret_value"):
        require(forbidden not in text, f"forbidden open or secret field in envelopes: {forbidden}")
    attestation = defs.get("profileAttestation", {}).get("required", [])
    require(attestation == ["planned_profile_digest", "attested_profile_digest", "runner_digest", "fields"], "attestation fields drifted")
    reconnect = defs.get("reconnect", {}).get("required", [])
    require(reconnect == ["kind", "reconnect_token", "last_durable_revision", "last_acknowledged_log_cursor"], "reconnect fields drifted")
    publish = defs.get("publishOutputs", {}).get("properties", {})
    require(publish.get("expected_absent", {}).get("const") is True, "publication must use compare-and-swap absence")
    reason_codes = defs.get("reasonCode", {}).get("enum", [])
    require(len(reason_codes) == 25 and len(reason_codes) == len(set(reason_codes)), "typed reason-code catalog drifted")
    require({"profile-mismatch", "command-exit-nonzero", "transport-disconnected", "cleanup-timeout"}.issubset(reason_codes), "typed failure distinctions drifted")
    disposition = defs.get("reservationDisposition", {})
    require(disposition.get("properties", {}).get("kind", {}).get("const") == "ReservationDisposition", "reservation result type drifted")
    require("disposition" not in defs.get("tryReserve", {}).get("required", []), "TryReserve request must not preselect its result")


def verify_thresholds(experiment: Path) -> None:
    thresholds = load_object(experiment / "thresholds.json")
    require(thresholds.get("sample_policy", {}).get("correctness_repetitions_per_case_per_adapter") == 5, "fault repetition count drifted")
    require(thresholds.get("sample_policy", {}).get("retain_failed_attempts") is True, "failed attempts must be retained")
    metrics = thresholds.get("timing_metrics")
    require(isinstance(metrics, list), "timing metrics missing")
    by_id = {item.get("id"): item for item in metrics}
    expected_counts = {
        "ready-result-hit": 30,
        "warm-ssh-linux-sandbox-admission": 30,
        "non-blocking-try-reserve": 30,
        "cancellation-acknowledgement": 5,
        "bounded-cleanup": 5,
    }
    require({key: by_id.get(key, {}).get("sample_count") for key in expected_counts} == expected_counts, "metric counts drifted")
    require(by_id["ready-result-hit"].get("threshold") == {"operator": "strictly-less-than", "milliseconds": 300}, "ready-hit threshold drifted")
    require(len(by_id["ready-result-hit"].get("hard_zero_counters", [])) == 9, "ready-hit zero counters drifted")
    require(by_id["warm-ssh-linux-sandbox-admission"].get("threshold") == {"operator": "strictly-less-than", "milliseconds": 2000}, "remote admission threshold drifted")
    require("declared queue duration" in by_id["warm-ssh-linux-sandbox-admission"].get("excluded", []), "queue exclusion drifted")
    require(by_id["non-blocking-try-reserve"].get("threshold") == {"operator": "less-than-or-equal", "milliseconds": 100}, "TryReserve threshold drifted")
    require(by_id["cancellation-acknowledgement"].get("threshold") == {"operator": "less-than-or-equal", "milliseconds": 1000}, "cancel acknowledgement threshold drifted")
    require(by_id["bounded-cleanup"].get("threshold") == {"operator": "less-than-or-equal", "milliseconds": 30000}, "cleanup threshold drifted")
    gates = thresholds.get("hard_gates", {})
    require(gates.get("threshold_relaxation_after_results") is False, "post-result threshold relaxation must remain forbidden")
    require(all(value == 0 for key, value in gates.items() if key.endswith("_count_max")), "all correctness hard gates must remain zero")
    require(thresholds.get("benchmark_harness", {}).get("schema_version") == "taskflow-t1-benchmark/v2", "benchmark schema drifted")


def verify_fault_matrix(experiment: Path) -> None:
    matrix = load_object(experiment / "fault-matrix.json")
    require(matrix.get("repetitions_per_case_per_adapter") == 5, "fault repetitions drifted")
    require(matrix.get("adapters") == ["in-process", "ssh-linux", "macos-e06-stub"], "fault adapter set drifted")
    cases = matrix.get("cases")
    require(isinstance(cases, list), "fault cases missing")
    require([case.get("id") for case in cases] == FAULT_IDS, "fault case set/order drifted")
    required_fields = set(matrix.get("required_fields", []))
    expected_fields = {"id", "boundary", "injection", "expected_state", "required_events", "forbidden_events", "retry_rule", "ownership_result", "raw_trace"}
    require(required_fields == expected_fields, "fault required fields drifted")
    traces: list[str] = []
    for case in cases:
        require(expected_fields.issubset(case), f"fault case incomplete: {case.get('id')}")
        require(case.get("required_events"), f"fault required events missing: {case.get('id')}")
        require(case.get("forbidden_events"), f"fault forbidden events missing: {case.get('id')}")
        trace = case.get("raw_trace")
        require(isinstance(trace, str) and trace.startswith("evidence/raw/") and trace.endswith(".jsonl"), f"invalid raw trace: {case.get('id')}")
        traces.append(trace)
    require(len(traces) == len(set(traces)), "fault trace paths must be unique")
    ready = cases[0]
    require(ready.get("expected_state") == "cache_hit" and "try_reserve" in ready.get("forbidden_events", []), "cache-before-reservation fault case drifted")
    resume = cases[-1]
    require("upstream_build_reexecuted" in resume.get("forbidden_events", []), "W2 successful work reuse drifted")


def verify_ssh_schema(experiment: Path) -> None:
    schema = load_object(experiment / "ssh-availability-manifest.schema.json")
    require(schema.get("additionalProperties") is False, "SSH manifest must be closed")
    props = schema.get("properties", {})
    endpoint = props.get("endpoint", {}).get("properties", {})
    identity = props.get("identity", {}).get("properties", {})
    remote = props.get("remote_scope", {}).get("properties", {})
    cleanup = props.get("cleanup", {}).get("properties", {})
    approval = props.get("approval", {}).get("properties", {})
    require(endpoint.get("strict_host_key_checking", {}).get("const") is True, "strict host-key checking must remain required")
    require(endpoint.get("known_hosts_path", {}).get("pattern", "").startswith("^experiments/e08-worker-protocol/approved/"), "known-hosts path must be experiment-owned")
    for key in ("ambient_ssh_config_forbidden", "ambient_agent_forbidden", "interactive_prompts_forbidden", "forwarding_forbidden"):
        require(identity.get(key, {}).get("const") is True, f"SSH identity safeguard drifted: {key}")
    for key in ("shared_root_forbidden", "sudo_forbidden", "installation_forbidden"):
        require(remote.get(key, {}).get("const") is True, f"remote scope safeguard drifted: {key}")
    require(cleanup.get("broad_process_kill_forbidden", {}).get("const") is True, "broad process kill must remain forbidden")
    require(cleanup.get("outside_allowlist_forbidden", {}).get("const") is True, "cleanup outside allowlist must remain forbidden")
    require(approval.get("exact_network_and_mutations_approved", {}).get("const") is True, "exact execution approval must be required")
    require(approval.get("phase_a_approval_is_not_execution_approval", {}).get("const") is True, "Phase A approval cannot authorize SSH")


def verify_decision(experiment: Path) -> None:
    decision = load_object(experiment / "decision-matrix.json")
    require(decision.get("status") == "predeclared-no-selection", "decision status drifted")
    require(decision.get("selected_branch") is None, "Phase A cannot select a branch")
    branches = decision.get("branches")
    expected_ids = [
        "stop-or-narrow",
        "state-machine-first-transport-deferral",
        "separated-worker-sandbox-session-protocols",
        "one-typed-core-with-capability-extensions",
    ]
    require([branch.get("id") for branch in branches] == expected_ids, "decision branches drifted")
    require([branch.get("precedence") for branch in branches] == [1, 2, 3, 4], "decision precedence drifted")
    global_requirements = decision.get("global_requirements", {})
    require(global_requirements.get("provider_option_leak_count_max") == 0, "provider option leak gate drifted")
    require(global_requirements.get("macos_stub_host_mutation_count_max") == 0, "macOS stub mutation gate drifted")
    require(global_requirements.get("transport_frozen_by_e08") is False, "transport must remain unfrozen")
    require(global_requirements.get("production_contract_allowed_to_stabilize") is False, "Phase A cannot stabilize production contracts")


def verify_frozen_artifacts(experiment: Path) -> None:
    manifest = load_object(experiment / "frozen-artifacts.json")
    require(manifest.get("format_version") == "taskflow-e08-frozen-artifacts/v1-experimental", "frozen manifest version drifted")
    artifacts = manifest.get("artifacts")
    require(isinstance(artifacts, list), "frozen artifacts missing")
    require([item.get("path") for item in artifacts] == sorted(FROZEN_FILES), "frozen artifact paths drifted")
    for item in artifacts:
        expected = item.get("sha256")
        require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected) is not None, f"invalid frozen digest: {item.get('path')}")
        require(sha256(experiment / item["path"]) == expected, f"frozen Phase A artifact drifted: {item['path']}")
    digest_line = (experiment / "protocol.sha256").read_text(encoding="utf-8").strip()
    expected_line = f"{sha256(experiment / 'frozen-artifacts.json')}  frozen-artifacts.json"
    require(digest_line == expected_line, "frozen-artifacts digest drifted")


def verify(experiment: Path = EXPERIMENT, repository: Path = REPOSITORY) -> None:
    verify_fileset(experiment)
    verify_contract(experiment, repository)
    verify_fixture_bindings(experiment, repository)
    verify_state_machines(experiment)
    verify_envelopes(experiment)
    verify_thresholds(experiment)
    verify_fault_matrix(experiment)
    verify_ssh_schema(experiment)
    verify_decision(experiment)
    verify_frozen_artifacts(experiment)


def main() -> int:
    try:
        verify()
    except VerificationError as error:
        print(f"E08 Phase A verification failed: {error}", file=sys.stderr)
        return 1
    print("E08 Phase A worker-protocol contract valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
