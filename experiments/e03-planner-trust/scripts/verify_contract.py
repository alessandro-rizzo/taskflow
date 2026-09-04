#!/usr/bin/env python3
"""Verify the frozen, result-free E03 Phase A contract."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


SCRIPT = Path(__file__).resolve()
EXPERIMENT = SCRIPT.parents[1]
ROOT = SCRIPT.parents[3]
HEX256 = re.compile(r"[0-9a-f]{64}")

EXPECTED_LIMITS = {
    "per_attempt_wall_seconds_maximum": 2,
    "candidate_suite_wall_seconds_maximum": 30,
    "cpu_seconds_hard": 1,
    "address_space_bytes_hard": 268435456,
    "file_descriptors_hard": 64,
    "combined_output_bytes_maximum": 1048576,
    "accepted_w1_plan_bytes_maximum": 1048576,
    "descendant_cleanup_seconds_maximum": 1,
    "processes_hard_when_supported": 32,
    "unsupported_hard_limit_result": "trusted_local_limitation",
}

EXPECTED_CATALOGUE = [
    (
        "fs-read-outside-source",
        "filesystem",
        "blocked",
        "A real planner sandbox must reject any read of a path outside the declared source view, regardless of how the path is constructed.",
    ),
    (
        "env-read-ambient",
        "environment",
        "blocked",
        "A real planner sandbox must not expose the daemon's ambient process environment or credentials to project code.",
    ),
    (
        "net-dial-loopback",
        "network",
        "blocked",
        "A real planner sandbox must deny outbound network connections and local socket access unless explicitly declared and authorized.",
    ),
    (
        "process-spawn-and-persist",
        "process",
        "bounded",
        "A real planner sandbox must ensure no spawned descendant process outlives the planning invocation.",
    ),
    (
        "resource-unbounded-growth",
        "resource",
        "bounded",
        "A real planner sandbox must enforce CPU, memory, file-descriptor, output, and wall-time limits on project code.",
    ),
    (
        "output-secret-leak",
        "output",
        "blocked",
        "A real planner sandbox or plan validator must ensure no secret material or unsafe path ever appears in the emitted plan.",
    ),
]

EXPECTED_EXTENDED = {
    "parser-duplicate-member",
    "parser-trailing-document",
    "parser-invalid-utf8",
    "parser-missing-version",
    "parser-unknown-version",
    "parser-unknown-field",
    "parser-document-size",
    "parser-depth",
    "parser-node-count",
    "policy-unauthorized-target",
    "policy-unauthorized-network",
    "policy-unauthorized-secret",
    "policy-unauthorized-effect",
    "policy-dangling-effect-target",
    "policy-unsafe-absolute-path",
    "policy-unsafe-parent-path",
    "policy-resource-per-node",
    "policy-resource-total",
    "policy-self-authorization",
}

EXPECTED_CANDIDATES = [
    "native",
    "pooled-container",
    "helper-vm",
    "static-descriptor",
]

EXPECTED_BRANCHES = [
    "stop-or-narrow-on-correctness",
    "native",
    "pooled-container",
    "helper-vm",
    "static-descriptor",
    "stop-or-narrow-on-latency",
]


class ContractError(RuntimeError):
    pass


def no_duplicate_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON member {key!r}")
        result[key] = value
    return result


def load_json(path):
    try:
        text = path.read_bytes().decode("utf-8", "strict")
        return json.loads(text, object_pairs_hook=no_duplicate_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load {path.relative_to(ROOT)}: {exc}") from exc


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ContractError(message)


def verify_protocol_checksum():
    recorded = (EXPERIMENT / "protocol.sha256").read_text(encoding="ascii").strip()
    require(HEX256.fullmatch(recorded) is not None, "protocol.sha256 is not one SHA-256")
    require(recorded == sha256(EXPERIMENT / "protocol.json"), "protocol checksum mismatch")


def verify_catalogue(attacks):
    require(
        attacks.get("schema_version") == "taskflow-e03-attack-matrix/v1",
        "attack matrix version drift",
    )
    require(
        attacks.get("catalogue_version") == "t1-malicious-planner-v1-experimental",
        "malicious catalogue version drift",
    )
    actual = [
        (
            entry.get("id"),
            entry.get("category"),
            entry.get("expected_outcome"),
            entry.get("diagnostic_assertion"),
        )
        for entry in attacks.get("catalogue_entries", [])
    ]
    require(actual == EXPECTED_CATALOGUE, "T1 catalogue metadata/order drift")
    for entry in attacks["catalogue_entries"]:
        require(entry.get("cases"), f"catalogue entry {entry['id']} has no real E03 cases")
        require(entry.get("safe_target"), f"catalogue entry {entry['id']} has no safe target")
    extended = [entry.get("id") for entry in attacks.get("extended_validator_cases", [])]
    require(len(extended) == len(set(extended)), "duplicate extended validator case id")
    require(set(extended) == EXPECTED_EXTENDED, "extended validator case coverage drift")
    for entry in attacks["extended_validator_cases"]:
        require(entry.get("expected_path"), f"extended case {entry['id']} lacks expected_path")
        require(
            entry.get("expected_outcome") in {"blocked", "bounded"},
            f"extended case {entry['id']} has invalid outcome",
        )
    require(
        attacks.get("required_outcome_vocabulary")
        == ["blocked", "bounded", "trusted_local_limitation"],
        "attack outcome vocabulary drift",
    )
    require(
        attacks.get("unavailable_is_candidate_state_not_attack_outcome") is True,
        "unavailable must remain a candidate state",
    )


def verify_contract_invariants(protocol, attacks, limits, policy, container, native):
    require(
        protocol.get("schema_version") == "taskflow-e03-experiment-protocol/v1",
        "protocol version drift",
    )
    require(protocol.get("roadmap_id") == "E03", "roadmap id drift")
    require(protocol.get("task_id") == "TF-003.10", "task id drift")
    require(protocol.get("status") == "phase-a-contract-only", "phase status drift")
    require(
        protocol.get("base_revision")
        == "21a55f3ea9eac0016d55b7827e80c01c237c9020",
        "base revision drift",
    )

    requirements = protocol["requirements"]
    require(
        requirements["canonical"]
        == ["SEC-1", "SEC-2", "SEC-3", "PLAN-2", "PLAN-5", "AGENT-6"],
        "canonical requirement mapping drift",
    )
    require(
        requirements["undefined_in_product_specification"]
        == ["SEC-4", "SEC-5", "SEC-6"],
        "undefined SEC requirement record drift",
    )
    require(
        requirements["undefined_aliases_may_be_invented"] is False,
        "undefined SEC aliases must not be invented",
    )

    require(protocol["hard_limits"] == EXPECTED_LIMITS, "protocol hard limits drift")
    require(limits.get("schema_version") == "taskflow-e03-resource-limits/v1", "limits version drift")
    require(
        {key: value for key, value in limits.items() if key != "schema_version"}
        == EXPECTED_LIMITS,
        "limits policy disagrees with protocol",
    )

    candidates = sorted(protocol["candidates"], key=lambda item: item["order"])
    require([item["id"] for item in candidates] == EXPECTED_CANDIDATES, "candidate order drift")
    require(
        protocol["performance_gate"]["candidate_order"] == EXPECTED_CANDIDATES,
        "benchmark candidate order drift",
    )
    perf = protocol["performance_gate"]
    require(perf["samples_per_exercised_candidate"] == 30, "benchmark sample count drift")
    require(perf["p95_seconds_exclusive"] == 0.25, "warm W1 threshold drift")
    require(perf["concurrent_measurement_allowed"] is False, "measurements must remain serial")
    require(perf["correctness_gate_must_pass_before_sampling"] is True, "correctness must precede timing")

    require(
        protocol["decision_branches"]["priority"] == EXPECTED_BRANCHES,
        "decision branch priority drift",
    )
    require(
        protocol["decision_branches"]["correctness_and_secret_leakage_precede_latency_or_availability"]
        is True,
        "correctness priority must remain explicit",
    )
    reruns = protocol["rerun_rules"]
    require(reruns["maximum_corrected_reruns_per_candidate"] == 1, "rerun count drift")
    require(reruns["individual_sample_replacement_allowed"] is False, "sample replacement enabled")
    require(reruns["threshold_or_branch_change_after_results_allowed"] is False, "post-result drift enabled")

    input_contract = protocol["planner_input_contract"]
    require(input_contract["environment"]["inherit_parent"] is False, "parent environment inheritance enabled")
    require(input_contract["daemon_provider_or_secret_handles"] == [], "authority handle supplied")
    require(input_contract["runtime_or_credential_sockets"] == [], "runtime socket supplied")
    require(protocol["threat_model"]["real_secret_allowed"] is False, "real secrets allowed")
    require(protocol["safe_attack_boundary"]["image_pull_allowed"] is False, "image pull allowed")
    require(protocol["safe_attack_boundary"]["vm_creation_or_start_allowed"] is False, "VM creation allowed")

    gate = protocol["hard_gates"]
    for key in [
        "selected_source_digest_changes",
        "outside_canary_changes",
        "planner_visible_daemon_provider_secret_canary_bytes",
        "retained_evidence_canary_or_encoded_canary_bytes",
        "unauthorized_listener_accepts",
        "surviving_descendants",
        "post_exit_marker_writes",
        "accepted_unauthorized_plans",
    ]:
        require(gate[key] == 0, f"hard gate {key} must remain zero")
    require(
        gate["trusted_local_limitation_qualifies_for_untrusted_agent_planning"] is False,
        "trusted-local limitation cannot qualify untrusted planning",
    )

    validator = protocol["independent_validator"]
    require(validator["language"] == "python3-standard-library", "validator language drift")
    require(validator["may_import_planner_or_e02_go_implementation"] is False, "validator imports planner")
    require(validator["planner_supplied_policy_is_authoritative"] is False, "planner policy became authoritative")
    require(validator["must_accept_known_good"] is True, "known-good positive control removed")

    require(policy.get("schema_version") == "taskflow-e03-untrusted-plan-policy/v1", "plan policy version drift")
    require(policy["maximums"]["document_bytes"] == 1048576, "plan policy byte limit drift")
    require(policy["maximums"]["services"] == 0, "network/service authority granted")
    require(policy["maximums"]["secrets"] == 0, "secret authority granted")
    require(policy["maximums"]["effects"] == 0, "effect authority granted")
    require(policy["allowed_network_routes"] == [], "network route allowlist is not empty")
    require(policy["allowed_secret_capabilities"] == [], "secret allowlist is not empty")
    require(policy["allowed_effect_kinds"] == [], "effect allowlist is not empty")
    require(policy["trusted_policy_digest_required_by_runner"] is True, "trusted policy digest not required")

    require(container.get("schema_version") == "taskflow-e03-container-policy/v1", "container policy version drift")
    require(container["image"]["remote_pull_allowed"] is False, "container pull enabled")
    require(container["runtime"]["network"] == "none", "container network enabled")
    require(container["runtime"]["read_only_root"] is True, "container root is writable")
    require(container["runtime"]["cap_drop"] == ["ALL"], "container capabilities not fully dropped")
    require(container["runtime"]["host_runtime_socket_mounts"] == [], "runtime socket mounted")
    require(container["runtime"]["host_credential_mounts"] == [], "credential mounted")

    require(native.count("{{PLANNER_EXECUTABLE}}") == 1, "native executable placeholder drift")
    require(native.count("{{SELECTED_SOURCE_VIEW}}") == 1, "native source placeholder drift")
    require(native.count("{{DECLARED_INPUTS}}") == 1, "native input placeholder drift")
    require(native.count("{{INVOCATION_SCRATCH}}") == 1, "native scratch placeholder drift")
    require("(deny default)" in native, "native profile is not deny-first")
    require("allow network" not in native, "native profile grants network")

    verify_catalogue(attacks)


def verify_bindings(protocol):
    paths = set()
    roles = set()
    for binding in protocol.get("bindings", []):
        path = binding.get("path")
        role = binding.get("role")
        expected = binding.get("sha256")
        require(path not in paths, f"duplicate binding path {path}")
        require(role not in roles, f"duplicate binding role {role}")
        require(HEX256.fullmatch(expected or "") is not None, f"invalid binding digest for {path}")
        paths.add(path)
        roles.add(role)
        actual_path = ROOT / path
        require(actual_path.is_file(), f"bound input missing: {path}")
        require(sha256(actual_path) == expected, f"bound input drift: {path}")
    require(len(paths) == 26, "expected exactly 26 read-only input bindings")


def actual_phase_a_files():
    return {
        path.relative_to(EXPERIMENT).as_posix()
        for path in EXPERIMENT.rglob("*")
        if path.is_file()
    }


def verify_phase_a_paths(actual, allowed, forbidden):
    actual = set(actual)
    allowed = set(allowed)
    require(actual == allowed, f"Phase A tree mismatch: missing={sorted(allowed-actual)} extra={sorted(actual-allowed)}")
    for path in actual:
        for prefix in forbidden:
            require(not (path == prefix.rstrip("/") or path.startswith(prefix)), f"Phase B path present: {path}")


def verify_scope_hashes(scope, protocol):
    require(scope.get("schema_version") == "taskflow-e03-scope-hashes/v1", "scope manifest version drift")
    entries = scope.get("entries", [])
    by_path = {}
    for entry in entries:
        path = entry.get("path")
        expected = entry.get("sha256")
        require(path not in by_path, f"duplicate scope path {path}")
        require(HEX256.fullmatch(expected or "") is not None, f"invalid scope digest for {path}")
        by_path[path] = expected

    contract_paths = {
        f"experiments/e03-planner-trust/{path}"
        for path in protocol["phase_a"]["allowed_files"]
        if path != "scope-hashes.json"
    }
    binding_paths = {binding["path"] for binding in protocol["bindings"]}
    expected_paths = contract_paths | binding_paths
    require(set(by_path) == expected_paths, "scope manifest path set drift")
    for relative, expected in by_path.items():
        path = ROOT / relative
        require(path.is_file(), f"scope path missing: {relative}")
        require(sha256(path) == expected, f"scope hash drift: {relative}")


def wrapper_description(path):
    proc = subprocess.run(
        [sys.executable, str(path), "--describe"],
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    require(proc.returncode == 0, f"wrapper describe failed: {path.name}: {proc.stderr.strip()}")
    try:
        return json.loads(proc.stdout, object_pairs_hook=no_duplicate_object)
    except json.JSONDecodeError as exc:
        raise ContractError(f"wrapper describe is not JSON: {path.name}: {exc}") from exc


def verify_wrappers(protocol):
    attack = wrapper_description(EXPERIMENT / "scripts/run_attacks.py")
    benchmark = wrapper_description(EXPERIMENT / "scripts/run_benchmarks.py")
    require(attack["candidate_order"] == EXPECTED_CANDIDATES, "attack wrapper order drift")
    require(attack["one_complete_suite_per_candidate"] is True, "attack wrapper permits partial suite")
    require(attack["per_attempt_seconds_maximum"] == 2, "attack wrapper attempt bound drift")
    require(attack["per_candidate_suite_seconds_maximum"] == 30, "attack wrapper suite bound drift")
    require(attack["phase_a_execution_allowed"] is False, "attack execution enabled in Phase A")
    require(benchmark["candidate_order"] == EXPECTED_CANDIDATES, "benchmark wrapper order drift")
    require(benchmark["samples_per_exercised_candidate"] == 30, "benchmark wrapper samples drift")
    require(benchmark["p95_seconds_exclusive"] == 0.25, "benchmark wrapper threshold drift")
    require(benchmark["concurrent_measurement_allowed"] is False, "benchmark concurrency enabled")
    require(benchmark["phase_a_execution_allowed"] is False, "benchmark execution enabled in Phase A")
    require(protocol["wrappers"]["attack"]["candidate_order"] == attack["candidate_order"], "protocol/attack wrapper disagreement")
    require(protocol["wrappers"]["benchmark"]["candidate_order"] == benchmark["candidate_order"], "protocol/benchmark wrapper disagreement")


def verify(phase_a_only=True):
    protocol = load_json(EXPERIMENT / "protocol.json")
    attacks = load_json(EXPERIMENT / "attacks.json")
    limits = load_json(EXPERIMENT / "policies/limits.json")
    policy = load_json(EXPERIMENT / "policies/untrusted-plan-policy.json")
    container = load_json(EXPERIMENT / "policies/container.json")
    native = (EXPERIMENT / "policies/native.sb.in").read_text(encoding="utf-8")
    verify_protocol_checksum()
    verify_contract_invariants(protocol, attacks, limits, policy, container, native)
    verify_bindings(protocol)
    scope = load_json(EXPERIMENT / "scope-hashes.json")
    verify_scope_hashes(scope, protocol)
    verify_wrappers(protocol)
    if phase_a_only:
        verify_phase_a_paths(
            actual_phase_a_files(),
            protocol["phase_a"]["allowed_files"],
            protocol["phase_a"]["forbidden_before_contract_commit"],
        )
    return protocol


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-a-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        protocol = verify(phase_a_only=args.phase_a_only)
    except (ContractError, OSError, KeyError, TypeError) as exc:
        print(f"verify_contract.py: {exc}", file=sys.stderr)
        return 1
    print(
        "E03 Phase A contract verified: "
        f"{len(protocol['bindings'])} inputs, "
        f"{len(protocol['catalogue_contract']['stable_t1_ids'])} catalogue entries, "
        "19 extended validator cases, no Phase B files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
