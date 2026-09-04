#!/usr/bin/env python3
"""Verify the frozen E02 contract, optionally enforcing the Phase A tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable


EXPERIMENT = Path(__file__).resolve().parents[1]
REPOSITORY = EXPERIMENT.parents[1]
PROTOCOL = EXPERIMENT / "protocol.json"
PROTOCOL_DIGEST = EXPERIMENT / "protocol.sha256"
SCOPE_HASHES = EXPERIMENT / "scope-hashes.json"
EXPECTED_PROTOCOL_SHA256 = "37fbf82c7f11711b9b477ecda014a1eb8ad4869d0298d8a497f82592a44e8083"
SIGNED_INT64_MIN = -(2**63)
SIGNED_INT64_MAX = 2**63 - 1

EXPECTED_PHASE_A_FILES = {
    "Taskfile.yml",
    "experiment-contract.md",
    "protocol.json",
    "protocol.sha256",
    "scope-hashes.json",
    "scripts/test_verify_contract.py",
    "scripts/verify_contract.py",
}

EXPECTED_BINDINGS = {
    "experiments/e01-authoring-schema/candidates/b-generated-go/go.mod": "0d1be68ebb3aeafda772cc4193f03aed856628147192b1a306273cf36e055e7f",
    "experiments/e01-authoring-schema/candidates/b-generated-go/project.go": "e759b5b113a99a9eecce901e2f66b0c133dae417d3380dff1eea5f1a786f9c96",
    "experiments/e01-authoring-schema/candidates/b-generated-go/runtime.go": "c2123b9a3a14d64b5ab0e1073c958c37293c0732130da5568637cb455263a429",
    "experiments/e01-authoring-schema/candidates/b-generated-go/generator.go": "9daefcb8ed194869d6eafa75d3669d543bc834b5db3de6066d4b3d95aa69c0d9",
    "experiments/e01-authoring-schema/candidates/b-generated-go/outputs/w1-logical-trace.json": "8fbf0840779bf1e41d8fc21bdf9f6351b16e16f1ccfb1184ff28703bab21e0d3",
    "fixtures/t1-plan-conformance/goldens/plan/w1-fast-project-check.plan.json": "3c50f41566609e70a9da3f6e2c10dc49f829c5990320122480c0af5d73b036c9",
    "fixtures/t1-plan-conformance/goldens/plan/w2-cross-target-artifact-pipeline.plan.json": "8ff93136a50e87407e3117355f8cc5c3bef7270bed9524874cc70927b2f50489",
    "fixtures/t1-plan-conformance/goldens/plan/w3-isolated-native-mobile-stack.plan.json": "f36e312c944a534d5edfcfdab0fda0f536042960b1b605b8ae700a77af8411d1",
    "fixtures/t1-plan-conformance/goldens/plan/synthetic-full-coverage.plan.json": "90dc0a7b2b8cddd545099cbeae754c5e763d69ea02459f682cdd2053feb51bb6",
}

EXPECTED_SET_LIKE_PATHS = [
    "$.nodes",
    "$.artifacts",
    "$.services",
    "$.secrets",
    "$.effects",
    "$.nodes[*].needs",
    "$.nodes[*].consumes",
    "$.nodes[*].produces",
    "$.nodes[*].planning_condition.patterns",
    "$.nodes[*].planning_condition.exclude_patterns",
    "$.nodes[*].cache_policy.key_inputs",
]

EXPECTED_SCOPE_PATHS = EXPECTED_BINDINGS.keys() | {
    "experiments/e02-plan-ir/Taskfile.yml",
    "experiments/e02-plan-ir/experiment-contract.md",
    "experiments/e02-plan-ir/protocol.json",
    "experiments/e02-plan-ir/protocol.sha256",
    "experiments/e02-plan-ir/scripts/test_verify_contract.py",
    "experiments/e02-plan-ir/scripts/verify_contract.py",
    "fixtures/t1-benchmark-harness/Taskfile.yml",
    "fixtures/t1-benchmark-harness/go.mod",
    "fixtures/t1-benchmark-harness/record.go",
    "fixtures/t1-benchmark-harness/validate.go",
    "fixtures/t1-benchmark-harness/cmd/t1bench/main.go",
    "fixtures/t1-plan-conformance/Taskfile.yml",
    "fixtures/t1-plan-conformance/go.mod",
    "fixtures/t1-plan-conformance/plan.go",
    "fixtures/t1-plan-conformance/decode.go",
    "fixtures/t1-plan-conformance/canonicalize.go",
    "fixtures/t1-plan-conformance/digest.go",
    "fixtures/t1-plan-conformance/compare.go",
    "fixtures/t1-plan-conformance/validate.go",
    "fixtures/t1-plan-conformance/cmd/t1conform/main.go",
}


class ContractError(ValueError):
    """A deterministic contract verification failure."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON object member: {key}")
        result[key] = value
    return result


def parse_int64(raw: str) -> int:
    if raw == "-0" or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", raw):
        raise ContractError(f"non-canonical integer literal: {raw}")
    value = int(raw)
    if not SIGNED_INT64_MIN <= value <= SIGNED_INT64_MAX:
        raise ContractError(f"integer outside signed 64-bit range: {raw}")
    return value


def reject_non_finite(raw: str) -> Any:
    raise ContractError(f"non-finite JSON number: {raw}")


def load_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=reject_duplicate_members,
            parse_int=parse_int64,
            parse_float=float,
            parse_constant=reject_non_finite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ContractError) as error:
        raise ContractError(f"cannot parse {label}: {error}") from error
    require(isinstance(value, dict), f"{label} must contain one JSON object")
    return value


def load_json(path: Path) -> dict[str, Any]:
    try:
        return load_json_bytes(path.read_bytes(), str(path))
    except OSError as error:
        raise ContractError(f"cannot read {path}: {error}") from error


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as error:
        raise ContractError(f"cannot hash {path}: {error}") from error


def verify_file_hash(path: Path, expected: str, label: str) -> None:
    actual = sha256_file(path)
    require(actual == expected, f"{label}: want {expected}, got {actual}")


def repository_path(relative: str) -> Path:
    path = (REPOSITORY / relative).resolve()
    try:
        path.relative_to(REPOSITORY.resolve())
    except ValueError as error:
        raise ContractError(f"scope path escapes repository: {relative}") from error
    return path


def require_exact_keys(value: dict[str, Any], expected: Iterable[str], label: str) -> None:
    actual = set(value)
    wanted = set(expected)
    require(actual == wanted, f"{label} keys differ: want {sorted(wanted)}, got {sorted(actual)}")


def validate_protocol_semantics(protocol: dict[str, Any]) -> None:
    require(protocol.get("schema_version") == "taskflow-e02-experiment-protocol/v1", "wrong protocol schema_version")
    require(protocol.get("roadmap_id") == "E02", "wrong roadmap_id")
    require(protocol.get("task_id") == "TF-003.08", "wrong task_id")
    require(protocol.get("status") == "phase-a-contract-only", "protocol is not Phase A only")
    require(protocol.get("base_revision") == "834ee0a95eef05a2a4e434bf9095826ee93a8cc5", "base revision drifted")

    boundaries = protocol["disposable_boundaries"]
    require(boundaries == {
        "all_e02_formats_apis_and_implementations_are_experimental": True,
        "production_go_module_selected": False,
        "public_package_selected": False,
        "daemon_transport_selected": False,
        "compatibility_promise": False,
        "prototype_import_allowed": False,
        "goldens_may_be_generation_inputs": False,
    }, "disposable boundary changed")

    formats = protocol["formats"]
    require(formats == {
        "plan_format_version": "t1-plan-conformance-plan-v2",
        "resume_diff_format_version": "e02-resume-diff-v1",
        "benchmark_schema_version": "taskflow-t1-benchmark/v2",
        "digest": "sha256-lowercase-hex-over-canonical-bytes",
    }, "format contract changed")

    plan = protocol["plan_grammar"]["objects"]["plan"]
    require(plan["required"] == ["document_kind", "format_version", "fixture_id", "fixture_version", "status", "nodes", "artifacts"], "plan required fields changed")
    require(plan["allowed"] == ["document_kind", "format_version", "fixture_id", "fixture_version", "status", "nodes", "artifacts", "services", "secrets", "effects"], "plan allowed fields changed")

    corrections = protocol["compatibility_corrections"]
    require(corrections == {
        "empty_declaration_arrays": {
            "omittable_when_empty": ["services", "secrets", "effects"],
            "missing_means_empty": True,
            "reason": "The bound T1 W1, W2, and W3 plans omit empty declaration arrays; requiring them would contradict the frozen zero-structural-difference gate.",
        },
        "e01_w1_optional_diagnostics": {
            "classification": "schema-only-unmaterialized",
            "plan_artifact_emitted": False,
            "reason": "Candidate B exposes diagnostics as an optional operation output but its trace has no producing work item and the bound W1 plan omits it.",
            "plan_optionality_proved_by": "synthetic-full-coverage",
        },
        "phase_transition": {
            "phase_a_boundary_check_is_explicit": True,
            "reusable_contract_check_allows_phase_b_files": True,
            "phase_b_must_verify_the_committed_corrected_phase_a_snapshot": True,
        },
    }, "compatibility correction changed")

    canonical = protocol["canonical_json"]
    require(canonical["encoding"] == "utf-8", "canonical encoding changed")
    require(canonical["bom"] is False and canonical["whitespace"] == "none", "canonical compactness changed")
    require(canonical["trailing_newline"] is False, "canonical trailing-newline rule changed")
    require(canonical["arrays_ordered_by_default"] is True, "array order default changed")
    require(canonical["open_ended_key_name_heuristic_allowed"] is False, "open-ended canonicalization heuristic enabled")
    require([entry["path"] for entry in canonical["set_like_paths"]] == EXPECTED_SET_LIKE_PATHS, "set-like path table changed")

    scope = protocol["scope"]
    require(set(scope["phase_a_allowed_files"]) == EXPECTED_PHASE_A_FILES, "Phase A file allowlist changed")
    bindings = {entry["path"]: entry["sha256"] for entry in scope["bindings"]}
    require(bindings == EXPECTED_BINDINGS, "bound E01/T1 inputs changed")
    require(scope["fixture_boundaries"] == {
        "w1": "read-only adapter over E01 Candidate B ComposeW1 trace",
        "w2": "E02-local disposable typed concrete graph matching T1 after emission",
        "w3": "E02-local disposable typed concrete graph matching T1 after emission",
        "synthetic": "E02-local disposable typed full-coverage graph matching T1 after emission",
    }, "fixture boundary changed")

    hard = protocol["hard_gates"]
    require(hard["fixtures"] == ["w1", "w2", "w3", "synthetic"], "fixture gate set changed")
    require(hard["t1_validation_violations"] == 0 and hard["t1_structural_differences"] == 0, "T1 zero-difference gate changed")
    require(hard["fresh_processes_per_fixture"] == 20, "fresh-process count changed")
    require(hard["distinct_canonical_byte_sequences_per_fixture"] == 1, "canonical-byte determinism gate changed")
    require(hard["distinct_digests_per_fixture"] == 1, "digest determinism gate changed")
    require(hard["go_python_canonical_byte_differences"] == 0, "cross-language byte gate changed")
    require(hard["go_python_digest_differences"] == 0, "cross-language digest gate changed")
    require(hard["reorder_probe_minimum_elements_per_set_like_path"] == 2, "reorder probe coverage changed")
    require(hard["reorder_digest_differences"] == 0, "reorder gate changed")
    require(hard["authority_counters"] == {"worker_acquisitions": 0, "provider_calls": 0, "secret_resolutions": 0}, "authority gate changed")

    mutations = {item["id"]: item for item in protocol["meaningful_mutations"]}
    require(set(mutations) == {"planning-condition", "execution-profile", "output-type", "output-optionality"}, "meaningful mutation set changed")
    expected_paths = {
        "planning-condition": ["$.nodes[id=lint].planning_condition.patterns"],
        "execution-profile": ["$.nodes[id=test].execution_profile.toolchain"],
        "output-type": ["$.artifacts[id=test-report].type"],
        "output-optionality": ["$.artifacts[id=test-report].optional"],
    }
    require({key: value["expected_paths"] for key, value in mutations.items()} == expected_paths, "resume-diff paths changed")

    performance = protocol["performance_gates"]
    require(performance["execution_order"] == ["w1-plan", "large-generation-canonicalization", "large-reader-validation-digest"], "measurement order changed")
    require(performance["concurrent_measurement_allowed"] is False, "concurrent measurements enabled")
    require(performance["w1_plan"] == {"samples": 30, "state": "warm", "driver": "prebuilt", "process": "fresh-per-sample", "p95_seconds_exclusive": 0.25}, "W1 threshold changed")
    require(performance["large_graph"] == {"nodes": 10000, "deterministic": True, "canonical_bytes_maximum_inclusive": 16777216}, "large-graph threshold changed")
    require(performance["large_generation_and_canonicalization"] == {"samples": 15, "state": "warm", "process": "fresh-per-sample", "p95_seconds_exclusive": 2.0}, "generation scale threshold changed")
    require(performance["large_reader_validation_and_digest"] == {"samples": 15, "state": "warm", "process": "fresh-per-sample", "p95_seconds_exclusive": 2.0}, "reader scale threshold changed")

    reruns = protocol["rerun_rules"]
    require(reruns["maximum_corrected_reruns_per_set"] == 1, "rerun limit changed")
    require(reruns["individual_sample_replacement_allowed"] is False, "individual sample replacement enabled")
    require(reruns["threshold_or_rule_change_after_results_allowed"] is False, "post-result rule changes enabled")
    require(reruns["other_discretionary_reruns_allowed"] is False, "discretionary reruns enabled")

    branches = protocol["decision_branches"]
    require(branches["priority"] == ["stop-revise-semantics", "bounded-dynamic-expansion", "pivot-encoding", "continue-canonical-json"], "decision precedence changed")
    require(branches["production_protocol_selected_before_gate_1"] is False, "production protocol selected early")
    require(protocol["phase_a_verification_command"] == "cd experiments/e02-plan-ir && mise exec -- task check:contract", "verification command changed")


def verify_protocol_digest() -> dict[str, Any]:
    raw = PROTOCOL.read_bytes()
    actual = sha256_bytes(raw)
    require(actual == EXPECTED_PROTOCOL_SHA256, f"protocol digest drift: want {EXPECTED_PROTOCOL_SHA256}, got {actual}")
    parts = PROTOCOL_DIGEST.read_text(encoding="utf-8").strip().split()
    require(parts == [EXPECTED_PROTOCOL_SHA256, "protocol.json"], "protocol.sha256 content changed")
    return load_json_bytes(raw, "protocol.json")


def verify_bound_inputs(protocol: dict[str, Any]) -> None:
    for entry in protocol["scope"]["bindings"]:
        path = repository_path(entry["path"])
        require(path.is_file(), f"missing bound input: {entry['path']}")
        verify_file_hash(path, entry["sha256"], f"bound input drift: {entry['path']}")

        if entry["id"].startswith("t1-plan-"):
            document = load_json(path)
            require(document.get("document_kind") == "plan", f"bound T1 input is not a plan: {entry['path']}")
            require(document.get("format_version") == "t1-plan-conformance-plan-v2", f"bound T1 plan version drift: {entry['path']}")
        if entry["id"] == "e01-candidate-b-w1-trace":
            trace = load_json(path)
            require(trace.get("status") == "experiment-only-not-plan-ir", "E01 trace status changed")
            require(trace.get("execution") == "fake", "E01 trace execution boundary changed")
            require(len(trace.get("typed_handle_relations", [])) == 6, "E01 W1 relation count changed")


def verify_scope_hashes() -> None:
    manifest = load_json(SCOPE_HASHES)
    require_exact_keys(manifest, {"schema_version", "hash_algorithm", "entries"}, "scope-hashes.json")
    require(manifest["schema_version"] == "taskflow-e02-scope-hashes/v1", "scope hash schema changed")
    require(manifest["hash_algorithm"] == "sha256", "scope hash algorithm changed")
    entries = manifest["entries"]
    require(isinstance(entries, list), "scope hash entries must be an array")
    paths = [entry.get("path") for entry in entries]
    require(len(paths) == len(set(paths)), "scope hash paths contain duplicates")
    require(set(paths) == set(EXPECTED_SCOPE_PATHS), "scope hash path set changed")
    for entry in entries:
        require_exact_keys(entry, {"path", "sha256"}, f"scope entry {entry.get('path')}")
        path = repository_path(entry["path"])
        require(path.is_file(), f"missing scope file: {entry['path']}")
        verify_file_hash(path, entry["sha256"], f"scope hash drift: {entry['path']}")


def verify_phase_a_file_boundary() -> None:
    actual = {
        str(path.relative_to(EXPERIMENT))
        for path in EXPERIMENT.rglob("*")
        if path.is_file()
    }
    require(actual == EXPECTED_PHASE_A_FILES, f"Phase A file boundary changed: want {sorted(EXPECTED_PHASE_A_FILES)}, got {sorted(actual)}")


def verify_contract(require_phase_a_only: bool = False) -> str:
    protocol = verify_protocol_digest()
    validate_protocol_semantics(protocol)
    verify_bound_inputs(protocol)
    verify_scope_hashes()
    if require_phase_a_only:
        verify_phase_a_file_boundary()
    return EXPECTED_PROTOCOL_SHA256


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase-a-only",
        action="store_true",
        help="also reject any file outside the frozen Phase A allowlist",
    )
    args = parser.parse_args()
    try:
        digest = verify_contract(args.phase_a_only)
    except (ContractError, OSError, KeyError, TypeError) as error:
        print(f"verify-contract: FAIL: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(f"verify-contract: PASS {digest}")


if __name__ == "__main__":
    main()
