#!/usr/bin/env python3
"""Verify the frozen E04 Phase A contract and its repository bindings."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any


EXPERIMENT = Path(__file__).resolve().parents[1]
REPOSITORY = EXPERIMENT.parents[1]
PROTOCOL_PATH = EXPERIMENT / "protocol.json"
PROTOCOL_HASH_PATH = EXPERIMENT / "protocol.sha256"


def fail(message: str) -> None:
    raise SystemExit(f"verify-e04-contract: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"cannot read {display(path)}: {error}")
    require(isinstance(value, dict), f"{display(path)} must contain a JSON object")
    return value


def display(path: Path) -> str:
    try:
        return path.relative_to(REPOSITORY).as_posix()
    except ValueError:
        return str(path)


def repository_path(relative: str) -> Path:
    require(isinstance(relative, str) and relative != "", "repository path must be a non-empty string")
    pure = PurePosixPath(relative)
    require(not pure.is_absolute(), f"absolute repository path is forbidden: {relative}")
    require(".." not in pure.parts and "\\" not in relative, f"unsafe repository path: {relative}")
    candidate = (REPOSITORY / pure).resolve()
    try:
        candidate.relative_to(REPOSITORY.resolve())
    except ValueError:
        fail(f"repository path escapes root: {relative}")
    return candidate


def sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        fail(f"cannot hash {display(path)}: {error}")


def verify_hash_file() -> str:
    try:
        line = PROTOCOL_HASH_PATH.read_text(encoding="utf-8").strip()
    except OSError as error:
        fail(f"cannot read {display(PROTOCOL_HASH_PATH)}: {error}")
    match = re.fullmatch(r"([0-9a-f]{64})  protocol\.json", line)
    require(match is not None, "protocol.sha256 must contain one sha256sum-style protocol.json entry")
    expected = match.group(1)
    actual = sha256(PROTOCOL_PATH)
    require(actual == expected, f"protocol digest mismatch: want {expected}, got {actual}")
    return actual


def verify_document_anchors() -> None:
    product = repository_path("docs/product-specification.md").read_text(encoding="utf-8")
    roadmap = repository_path("docs/roadmap.md").read_text(encoding="utf-8")

    requirement_lines = {
        "REP-1": "Every run uses one immutable source snapshot.",
        "REP-2": "The requested and attained reproducibility levels are reported.",
        "REP-3": "Cache identity includes semantic execution profile and all declared",
        "REP-4": "Ready cache hits return before worker reservation.",
        "REP-5": "Result, tool, and warm-provider caches are distinct.",
        "REP-6": "Artifact provenance is queryable and digest verified.",
        "EXEC-3": "Workers and disposable sandboxes are separate lifecycles.",
        "EXEC-4": "Profile identity is known before provisioning and attested at",
    }
    for requirement_id, text in requirement_lines.items():
        require(
            f"- **{requirement_id}:** {text}" in product,
            f"canonical product requirement anchor drifted: {requirement_id}",
        )
    require("- **SRC-" not in product, "product specification unexpectedly defines SRC-* requirements")
    require("- **CACHE-" not in product, "product specification unexpectedly defines CACHE-* requirements")

    roadmap_anchors = [
        "### E04: immutable source, lightweight sandbox, and cache identity",
        "1. Mutating the source worktree after run creation does not affect execution.",
        "2. Two concurrent W1 runs cannot observe each other's writable outputs.",
        "3. Undeclared source paths and environment values are denied or detected at the",
        "4. Cache identity is computed from source, inputs, process, profile, policy, and",
        "5. A cache hit performs zero provider reservations/acquisitions.",
        "6. A worker with mismatched profile attestation is rejected rather than",
        "7. Result cache, tool cache, and warm worker state are demonstrably distinct.",
    ]
    for anchor in roadmap_anchors:
        require(anchor in roadmap, f"E04 roadmap anchor drifted: {anchor}")


def verify_fixture_bindings(protocol: dict[str, Any]) -> None:
    declaration = protocol.get("fixture_bindings")
    require(isinstance(declaration, dict), "fixture_bindings declaration is required")
    require(
        declaration.get("path") == "experiments/e04-source-sandbox-cache/fixture-bindings.json",
        "fixture binding path changed",
    )
    binding_path = repository_path(declaration["path"])
    actual_manifest_hash = sha256(binding_path)
    require(
        declaration.get("sha256") == actual_manifest_hash,
        f"fixture binding manifest drifted: want {declaration.get('sha256')}, got {actual_manifest_hash}",
    )

    manifest = load_object(binding_path)
    require(
        manifest.get("schema_version") == "taskflow-e04-fixture-bindings/v1",
        "fixture binding schema version changed",
    )
    require(
        manifest.get("source_revision") == "834ee0a95eef05a2a4e434bf9095826ee93a8cc5",
        "fixture binding source revision changed",
    )
    bindings = manifest.get("bindings")
    require(isinstance(bindings, list), "fixture bindings must be a list")
    expected_ids = ["w1-fast-project-check", "t1-integrity-faults", "t1-benchmark-harness"]
    require([item.get("fixture_id") for item in bindings] == expected_ids, "fixture binding set/order changed")

    seen_paths: set[str] = set()
    for binding in bindings:
        files = binding.get("files")
        require(isinstance(files, list) and files, f"{binding.get('fixture_id')} has no bound files")
        paths = [item.get("path") for item in files]
        require(paths == sorted(paths), f"{binding.get('fixture_id')} bound paths are not sorted")
        for item in files:
            relative = item.get("path")
            expected_hash = item.get("sha256")
            require(isinstance(relative, str), "bound fixture path must be a string")
            require(relative not in seen_paths, f"duplicate bound fixture path: {relative}")
            seen_paths.add(relative)
            require(
                isinstance(expected_hash, str) and re.fullmatch(r"[0-9a-f]{64}", expected_hash) is not None,
                f"invalid sha256 for {relative}",
            )
            actual_hash = sha256(repository_path(relative))
            require(actual_hash == expected_hash, f"fixture drift for {relative}: want {expected_hash}, got {actual_hash}")

    by_id = {item["fixture_id"]: item for item in bindings}
    require(by_id["w1-fast-project-check"].get("version") == "t1-experimental-v1", "W1 version changed")
    w1_manifest = repository_path("fixtures/w1/manifest.yaml").read_text(encoding="utf-8")
    require("fixture_id: w1-fast-project-check\n" in w1_manifest, "W1 fixture_id anchor changed")
    require("version: t1-experimental-v1\n" in w1_manifest, "W1 version anchor changed")

    integrity = by_id["t1-integrity-faults"]
    require(integrity.get("version") == "t1-integrity-faults-v2-experimental", "integrity version changed")
    require(
        integrity.get("manifest_schema_version") == "t1-integrity-faults-manifest/v1",
        "integrity manifest schema version changed",
    )
    integrity_readme = repository_path("fixtures/integrity-faults/README.md").read_text(encoding="utf-8")
    require("Fixture id: `t1-integrity-faults`. Version: `t1-integrity-faults-v2-experimental`." in integrity_readme, "integrity fixture anchor changed")
    require("`t1-integrity-faults-manifest/v1`" in integrity_readme, "integrity schema anchor changed")

    benchmark = by_id["t1-benchmark-harness"]
    require(benchmark.get("version") == "taskflow-t1-benchmark/v2", "benchmark harness version changed")
    benchmark_record = repository_path("fixtures/t1-benchmark-harness/record.go").read_text(encoding="utf-8")
    require(
        'const CurrentSchemaVersion = "taskflow-t1-benchmark/v2"' in benchmark_record,
        "benchmark schema anchor changed",
    )


def verify_requirements(protocol: dict[str, Any]) -> None:
    expected = {
        "EXEC-3": "Workers and disposable sandboxes are separate lifecycles.",
        "EXEC-4": "Profile identity is known before provisioning and attested at execution.",
        "REP-1": "Every run uses one immutable source snapshot.",
        "REP-2": "The requested and attained reproducibility levels are reported.",
        "REP-3": "Cache identity includes semantic execution profile and all declared typed inputs.",
        "REP-4": "Ready cache hits return before worker reservation.",
        "REP-5": "Result, tool, and warm-provider caches are distinct.",
        "REP-6": "Artifact provenance is queryable and digest verified.",
    }
    require(protocol.get("requirement_mapping") == expected, "canonical requirement mapping changed")
    require(
        set(protocol.get("requirements_not_established_here", {})) == {"EXEC-1", "EXEC-2", "EXEC-5"},
        "out-of-scope execution requirements changed",
    )

    correction = protocol.get("compatibility_correction")
    require(isinstance(correction, dict), "compatibility correction is required")
    expected_stale = [f"SRC-{index}" for index in range(1, 6)] + [f"CACHE-{index}" for index in range(1, 7)]
    require(correction.get("noncanonical_ticket_labels") == expected_stale, "stale ticket label set changed")
    without_correction = dict(protocol)
    without_correction.pop("compatibility_correction", None)
    canonical_payload = json.dumps(without_correction, sort_keys=True)
    for label in expected_stale:
        require(label not in canonical_payload, f"noncanonical requirement leaked outside correction: {label}")


def verify_identity_contract(protocol: dict[str, Any]) -> None:
    identity = protocol.get("identity_contract")
    require(isinstance(identity, dict), "identity_contract is required")
    require(
        identity.get("mandatory_components") == [
            "source_manifest",
            "typed_input_manifests",
            "resolved_process_and_arguments",
            "execution_profile",
            "sandbox_policy",
            "dependency_manifests",
        ],
        "cache identity component set/order changed",
    )
    require(identity.get("missing_component_result") == "reject-before-lookup", "missing identity must reject before lookup")
    ordering = identity.get("ordering")
    require(isinstance(ordering, list), "identity event ordering is required")
    require(ordering.index("compute-cache-key") < ordering.index("reserve-worker-on-miss-only"), "cache key must precede reservation")
    require(ordering.index("lookup-result-cache") < ordering.index("reserve-worker-on-miss-only"), "lookup must precede reservation")
    require(ordering.index("reserve-worker-on-miss-only") < ordering.index("attest-worker-profile"), "attestation ordering changed")


def verify_measurements(protocol: dict[str, Any]) -> None:
    measurements = protocol.get("measurements")
    require(isinstance(measurements, dict), "measurements contract is required")
    require(measurements.get("execution_order", "").startswith("Serial only"), "measurements must be serial")
    harness = measurements.get("harness", {})
    require(harness.get("schema_version") == "taskflow-t1-benchmark/v2", "measurement harness schema changed")
    require(harness.get("fixture_id") == "t1-benchmark-harness", "measurement harness fixture changed")

    metrics = measurements.get("metrics")
    require(isinstance(metrics, list), "metrics must be a list")
    expected_ids = [
        "local-warm-sandbox-creation-apfs",
        "local-warm-sandbox-creation-copy-control",
        "ready-cache-hit-after-planning",
    ]
    require([metric.get("id") for metric in metrics] == expected_ids, "metric set/order changed")
    for metric in metrics:
        require(metric.get("sample_count") == 30, f"{metric.get('id')} must retain 30 samples")
    require(
        metrics[0].get("threshold") == {"operator": "strictly-less-than", "seconds": 0.25},
        "APFS warm sandbox threshold changed",
    )
    require(metrics[1].get("threshold") is None, "copy control must remain descriptive")
    require(
        metrics[2].get("threshold") == {"operator": "strictly-less-than", "seconds": 0.3},
        "ready-hit latency threshold changed",
    )
    require(
        metrics[2].get("counter_requirements") == {
            "acquisitions_per_sample": 0,
            "reservations_per_sample": 0,
            "sandboxes_per_sample": 0,
        },
        "ready-hit zero-resource counters changed",
    )


def verify_probes_and_branches(protocol: dict[str, Any]) -> None:
    probes = protocol.get("probes")
    require(isinstance(probes, list), "probes must be a list")
    expected_ids = [
        "source-mutation",
        "concurrent-output-isolation",
        "ambient-input-control",
        "pre-reservation-identity",
        "zero-reservation-cache-hit",
        "attestation-mismatch",
        "cache-class-separation",
    ]
    require([probe.get("id") for probe in probes] == expected_ids, "seven-probe set/order changed")
    require([probe.get("roadmap_demonstration") for probe in probes] == list(range(1, 8)), "roadmap demonstration mapping changed")
    evidence_paths = [probe.get("evidence_path") for probe in probes]
    require(len(set(evidence_paths)) == 7, "probe evidence paths must be unique")
    require(all(isinstance(path, str) and path.startswith("evidence/raw/") for path in evidence_paths), "probe evidence path escaped raw directory")
    canonical_ids = set(protocol["requirement_mapping"])
    for probe in probes:
        requirements = probe.get("requirements")
        require(isinstance(requirements, list) and requirements, f"{probe.get('id')} has no requirement mapping")
        require(set(requirements) <= canonical_ids, f"{probe.get('id')} uses a noncanonical requirement")

    branches = protocol.get("decision_branches")
    require(isinstance(branches, list), "decision_branches must be a list")
    require(
        [branch.get("id") for branch in branches] == [
            "native-isolated-default",
            "native-fast-incomplete",
            "pooled-container-linux",
            "redesign-profile-identity",
            "local-hit-remote-miss",
            "stop-or-narrow",
        ],
        "decision branch set/order changed",
    )


def verify_reproducibility_claim(protocol: dict[str, Any]) -> None:
    claim = protocol.get("reproducibility_claim")
    require(isinstance(claim, dict), "reproducibility claim is required")
    require(claim.get("requested_level") == "isolated", "requested level changed")
    require(claim.get("maximum_predeclared_level") == "isolated", "Phase A must not predeclare a hermetic claim")
    require(len(claim.get("required_controls", [])) == 5, "isolated control set changed")
    require(len(claim.get("unproven_hermetic_inputs", [])) == 5, "hermetic limitation set changed")


def verify_phase_boundary(protocol: dict[str, Any]) -> None:
    boundary = protocol.get("phase_boundary")
    require(isinstance(boundary, dict), "phase_boundary is required")
    allowed = boundary.get("allowed_phase_a_files")
    require(isinstance(allowed, list), "allowed Phase A file list is required")
    actual = sorted(
        path.relative_to(EXPERIMENT).as_posix()
        for path in EXPERIMENT.rglob("*")
        if path.is_file()
    )
    require(actual == sorted(allowed), f"Phase A tree contains unexpected or missing files: want {sorted(allowed)}, got {actual}")


def verify_contract(require_phase_a_only: bool) -> str:
    digest = verify_hash_file()
    protocol = load_object(PROTOCOL_PATH)
    require(protocol.get("schema_version") == "taskflow-e04-phase-a-protocol/v1", "protocol schema version changed")
    require(
        protocol.get("experiment") == {
            "phase": "phase-a-contract-only",
            "roadmap_id": "E04",
            "risks": ["R4", "R5", "R9"],
            "status": "predeclared",
            "ticket_id": "TF-003.11",
        },
        "experiment identity/phase changed",
    )
    verify_document_anchors()
    verify_fixture_bindings(protocol)
    verify_requirements(protocol)
    verify_identity_contract(protocol)
    verify_measurements(protocol)
    verify_probes_and_branches(protocol)
    verify_reproducibility_claim(protocol)
    if require_phase_a_only:
        verify_phase_boundary(protocol)
    return digest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase-a-only",
        action="store_true",
        help="also reject any file outside the frozen Phase A contract allowlist",
    )
    args = parser.parse_args()
    digest = verify_contract(args.phase_a_only)
    mode = "phase-a" if args.phase_a_only else "contract"
    print(f"verify-e04-contract: PASS mode={mode} protocol_sha256={digest}")


if __name__ == "__main__":
    main()
