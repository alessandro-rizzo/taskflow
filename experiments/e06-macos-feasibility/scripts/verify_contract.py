#!/usr/bin/env python3
"""Verify the frozen E06 Phase A inventory and measurement contract."""

from __future__ import annotations

import hashlib
import importlib.util
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
    "candidate-matrix.json",
    "candidate-procedures.md",
    "contract.json",
    "execution-manifest.schema.json",
    "fixture-bindings.json",
    "frozen-artifacts.json",
    "infrastructure-status.json",
    "inventory/host-profile.json",
    "inventory/raw/local-tool-presence.txt",
    "inventory/raw/simulator-plists.txt",
    "inventory/raw/system-profiler.txt",
    "inventory/raw/xcode-first-launch.txt",
    "inventory/raw/xcodebuild-sdks.txt",
    "inventory/raw/xcodebuild-version.txt",
    "inventory/simulator.json",
    "inventory/tooling.json",
    "measurement-plan.json",
    "protocol.sha256",
    "scripts/collect_inventory.py",
    "scripts/verify_contract.py",
    "tests/test_verify_contract.py",
}

FROZEN_FILES = EXPECTED_FILES - {"frozen-artifacts.json", "protocol.sha256"}
PHASE_B_NAMES = {"decision.json", "evidence", "measurements", "results", "scorecard.json"}
UUID_PATTERN = re.compile(
    r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b"
)


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
    require(found == EXPECTED_FILES, f"Phase A fileset mismatch: missing={sorted(EXPECTED_FILES - found)} extra={sorted(found - EXPECTED_FILES)}")
    for path in experiment.iterdir():
        require(path.name not in PHASE_B_NAMES, f"Phase B artifact is forbidden: {path.name}")


def verify_contract_document(experiment: Path, repository: Path) -> dict[str, Any]:
    contract = load_object(experiment / "contract.json")
    require(contract.get("status") == "phase-a-inventory-frozen", "contract status must remain Phase A frozen")
    require(contract.get("baseline_revision") == "21a55f3ea9eac0016d55b7827e80c01c237c9020", "baseline revision drifted")
    require(contract.get("risks") == ["R4", "R8", "R9"], "risk mapping drifted")
    canonical = contract.get("canonical_requirements", {})
    require(canonical.get("specified_by_phase_a") == ["EXEC-3", "EXEC-4", "EXEC-5", "REP-2"], "canonical Phase A requirements drifted")
    require(canonical.get("predeclared_for_phase_b") == ["AGENT-4", "AGENT-5"], "Phase B requirement mapping drifted")
    stale = [f"MAC-{index}" for index in range(1, 6)]
    require(canonical.get("stale_ticket_references") == stale, "stale MAC provenance drifted")
    without_stale = json.loads(json.dumps(contract))
    without_stale["canonical_requirements"].pop("stale_ticket_references", None)
    require(not any(label in json.dumps(without_stale) for label in stale), "stale MAC label leaked into canonical contract")
    phase = contract.get("phase_boundary", {})
    require(phase.get("phase_b_owner") == "TF-003.14", "Phase B owner drifted")
    forbidden = phase.get("phase_a_forbids", [])
    require("VM or simulator lifecycle mutation" in forbidden, "Phase A must forbid lifecycle mutation")
    require("selected E06 decision branch" in forbidden, "Phase A must forbid a decision result")
    product = (repository / "docs/product-specification.md").read_text(encoding="utf-8")
    roadmap = (repository / "docs/roadmap.md").read_text(encoding="utf-8")
    require("- **EXEC-3:** Workers and disposable sandboxes are separate lifecycles." in product, "EXEC-3 product anchor drifted")
    require("- **EXEC-4:** Profile identity is known before provisioning and attested at" in product, "EXEC-4 product anchor drifted")
    require("- **EXEC-5:** Services, sessions, and scarce devices use durable leases." in product, "EXEC-5 product anchor drifted")
    require("- **REP-2:** The requested and attained reproducibility levels are reported." in product, "REP-2 product anchor drifted")
    require("### E06: macOS VM, Xcode, and simulator feasibility" in roadmap, "E06 roadmap anchor drifted")
    require("- warm macOS workspace/sandbox creation: p95 below 3 seconds;" in roadmap, "workspace budget anchor drifted")
    require("- warm macOS simulator ready-to-install: p95 below 15 seconds;" in roadmap, "simulator budget anchor drifted")
    return contract


def verify_fixture_bindings(experiment: Path, repository: Path) -> None:
    manifest = load_object(experiment / "fixture-bindings.json")
    require(manifest.get("source_revision") == "21a55f3ea9eac0016d55b7827e80c01c237c9020", "fixture source revision drifted")
    bindings = manifest.get("bindings")
    require(isinstance(bindings, list) and [item.get("fixture_id") for item in bindings] == ["w3-isolated-native-mobile-stack", "t1-benchmark-harness"], "fixture binding set/order drifted")
    expected_counts = {"w3-isolated-native-mobile-stack": 9, "t1-benchmark-harness": 2}
    for binding in bindings:
        files = binding.get("files")
        require(isinstance(files, list) and len(files) == expected_counts[binding["fixture_id"]], f"fixture file count drifted: {binding.get('fixture_id')}")
        paths = [item.get("path") for item in files]
        require(paths == sorted(paths), f"fixture paths must be sorted: {binding.get('fixture_id')}")
        for item in files:
            relative = item.get("path")
            expected = item.get("sha256")
            require(isinstance(relative, str) and ".." not in Path(relative).parts, f"unsafe fixture path: {relative}")
            require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected) is not None, f"invalid fixture digest: {relative}")
            actual = sha256(repository / relative)
            require(actual == expected, f"fixture drift: {relative}: want {expected}, got {actual}")


def verify_inventory(experiment: Path) -> None:
    host = load_object(experiment / "inventory/host-profile.json")
    tooling = load_object(experiment / "inventory/tooling.json")
    simulator = load_object(experiment / "inventory/simulator.json")
    require(host.get("collection_mode") == "non-mutating-local-read-only", "host inventory mode drifted")
    require(host.get("hardware", {}).get("architecture") == "arm64", "host architecture drifted")
    require(host.get("reservation", {}).get("status") == "unreserved", "host must remain unreserved")
    privacy = host.get("privacy", {})
    require(all(privacy.get(key) is False for key in ("host_serial_recorded", "hardware_uuid_recorded", "user_identity_recorded", "device_udids_recorded")), "host privacy flags must remain false")
    require(tooling.get("xcode", {}).get("first_launch_status_exit") == 0, "Xcode first-launch observation drifted")
    require(tooling.get("macos_vm_tools", {}).get("present") == [], "snapshot unexpectedly claims a macOS VM tool")
    require(simulator.get("collection_mode") == "sanitized-plist-read-only", "simulator collection mode drifted")
    require(simulator.get("live_simctl_query", {}).get("retained_collector_uses_simctl") is False, "retained collector must not use simctl")
    require(simulator.get("default_device_set", {}).get("allowed_for_e06") is False, "default simulator set must be forbidden")
    require(simulator.get("default_device_set", {}).get("device_udids_recorded") is False, "device UDIDs must not be recorded")
    inventory_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((experiment / "inventory").rglob("*"))
        if path.is_file()
    )
    require("/Users/" not in inventory_text, "inventory leaked a user home path")
    require(UUID_PATTERN.search(inventory_text) is None, "inventory leaked a UUID or device UDID")


def load_collector(experiment: Path):
    path = experiment / "scripts/collect_inventory.py"
    spec = importlib.util.spec_from_file_location("e06_collect_inventory", path)
    require(spec is not None and spec.loader is not None, "cannot load collector")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_collector(experiment: Path) -> None:
    module = load_collector(experiment)
    expected = {
        "sw_vers",
        "uname",
        "system_profiler",
        "xcode-select",
        "xcodebuild",
        "limactl",
        "colima",
        "docker",
    }
    require(set(module.SAFE_QUERY_EXECUTABLES) == expected, "collector query allowlist drifted")
    forbidden = {"simctl", "tart", "orchard", "diskutil", "DevToolsSecurity", "ps", "sysctl"}
    require(set(module.SAFE_QUERY_EXECUTABLES).isdisjoint(forbidden), "collector can execute a forbidden query")
    fake = module.sanitized_device({"name": "test", "UDID": "secret", "state": 1})
    require("UDID" not in fake and "secret" not in json.dumps(fake), "collector retained a device UDID")


def verify_candidates(experiment: Path) -> None:
    matrix = load_object(experiment / "candidate-matrix.json")
    workers = matrix.get("worker_candidates")
    worker_ids = [item.get("id") for item in workers] if isinstance(workers, list) else []
    require(worker_ids == ["warm-immutable-vm-restore", "warm-vm-apfs-workspaces", "vm-per-namespace", "trusted-native-host", "coarse-external-runner"], "worker candidate set/order drifted")
    require([item.get("status") for item in workers].count("conditional-unreserved") == 1, "exactly one worker candidate must be conditional-unreserved")
    simulators = matrix.get("simulator_candidates")
    require([item.get("id") for item in simulators] == ["clone-from-golden", "erase-reset", "fresh-create-boot"], "simulator candidate set/order drifted")
    procedures = (experiment / "candidate-procedures.md").read_text(encoding="utf-8")
    for item in workers + simulators:
        require(item.get("required_prerequisites"), f"candidate lacks prerequisites: {item.get('id')}")
        marker = item.get("procedure")
        require(isinstance(marker, str) and f"## {marker}" in procedures, f"candidate procedure missing: {item.get('id')}")
    require("killall" in procedures and "never invokes `killall`" in procedures, "broad process-kill prohibition missing")


def verify_measurements(experiment: Path) -> None:
    plan = load_object(experiment / "measurement-plan.json")
    require(plan.get("benchmark_harness", {}).get("schema_version") == "taskflow-t1-benchmark/v2", "benchmark schema drifted")
    metrics = plan.get("timing_metrics")
    require(isinstance(metrics, list), "timing metrics must be a list")
    expected_counts = {
        "cold-vm-boot": 15,
        "warm-workspace-ready": 30,
        "simulator-ready-to-install": 30,
        "xcode-build": 15,
        "simulator-install": 15,
        "mobile-test": 15,
        "candidate-reset": 15,
        "candidate-cleanup": 15,
        "image-import-update": 15,
    }
    require({item.get("id"): item.get("sample_count") for item in metrics} == expected_counts, "timing metric counts drifted")
    by_id = {item["id"]: item for item in metrics}
    require(by_id["warm-workspace-ready"].get("threshold") == {"operator": "strictly-less-than", "p95_seconds": 3.0}, "workspace threshold drifted")
    require(by_id["simulator-ready-to-install"].get("threshold") == {"operator": "strictly-less-than", "p95_seconds": 15.0}, "simulator threshold drifted")
    for metric in metrics:
        require(all(metric.get(field) for field in ("start", "end", "preparation", "raw_path")), f"metric boundary incomplete: {metric.get('id')}")
    probes = {item.get("id"): item for item in plan.get("correctness_probes", [])}
    require(probes.get("alternating-namespace-contamination", {}).get("repetitions") == 20, "handoff probe drifted")
    require(probes.get("two-namespace-isolation", {}).get("repetitions") == 10, "two-namespace probe drifted")
    require(probes.get("bounded-maximum-safe-concurrency", {}).get("repetitions_per_level") == 5, "concurrency probe drifted")
    failures = plan.get("failure_recovery_probes")
    require([item.get("id") for item in failures] == ["vm-loss", "simulator-loss", "cancellation", "caller-loss"], "failure probe set/order drifted")
    require(all(item.get("repetitions") == 5 for item in failures), "failure probes must retain five repetitions")
    branches = [item.get("id") for item in plan.get("decision_branches", [])]
    require(branches == ["warm-vm-cloned-workspace", "vm-per-namespace", "trusted-native-host", "coarse-external-runner", "serialized-macos-capacity", "stop-or-narrow"], "decision branch set/order drifted")
    require(plan.get("hard_gates", {}).get("threshold_relaxation_after_results") is False, "post-result threshold relaxation must remain forbidden")


def verify_blocker_and_schema(experiment: Path) -> None:
    status = load_object(experiment / "infrastructure-status.json")
    require(status.get("status") == "external-blocker", "infrastructure must remain an explicit external blocker")
    require(status.get("reservation") is None, "Phase A must not record a reservation")
    require(status.get("current_host", {}).get("exclusive") is False, "current host must remain unreserved")
    require(len(status.get("blockers", [])) == 5, "blocker set drifted")
    require(len(status.get("next_safe_actions", [])) == 3, "next-safe-action set drifted")
    schema = load_object(experiment / "execution-manifest.schema.json")
    definitions = schema.get("$defs", {})
    properties = schema.get("properties", {})
    paths = properties.get("paths", {}).get("properties", {})
    cleanup = properties.get("cleanup_allowlist", {}).get("properties", {})
    approval = properties.get("approval", {}).get("properties", {})
    require(paths.get("default_simulator_set_forbidden", {}).get("const") is True, "manifest must forbid default simulator set")
    require(definitions.get("mutablePath", {}).get("not") == {"pattern": "(^|/)\\.\\.(/|$)"}, "manifest mutable paths must reject parent traversal")
    require(definitions.get("evidencePath", {}).get("not") == {"pattern": "(^|/)\\.\\.(/|$)"}, "manifest evidence paths must reject parent traversal")
    require(cleanup.get("immutable_base_delete_forbidden", {}).get("const") is True, "manifest must forbid base-image deletion")
    require(cleanup.get("broad_process_kill_forbidden", {}).get("const") is True, "manifest must forbid broad process killing")
    require(approval.get("plan_approval_is_not_execution_approval", {}).get("const") is True, "manifest must require separate execution approval")
    require(properties.get("resources", {}).get("properties", {}).get("concurrency_levels", {}).get("contains") == {"const": 2}, "manifest concurrency levels must include two")


def verify_frozen_artifacts(experiment: Path) -> None:
    manifest = load_object(experiment / "frozen-artifacts.json")
    artifacts = manifest.get("artifacts")
    require(isinstance(artifacts, list), "frozen artifacts must be a list")
    paths = [item.get("path") for item in artifacts]
    require(paths == sorted(FROZEN_FILES), "frozen artifact set/order drifted")
    for item in artifacts:
        expected = item.get("sha256")
        require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected) is not None, f"invalid frozen digest: {item.get('path')}")
        actual = sha256(experiment / item["path"])
        require(actual == expected, f"frozen artifact drift: {item['path']}: want {expected}, got {actual}")
    line = (experiment / "protocol.sha256").read_text(encoding="utf-8").strip()
    match = re.fullmatch(r"([0-9a-f]{64})  frozen-artifacts\.json", line)
    require(match is not None, "protocol.sha256 must contain one frozen-artifacts.json entry")
    actual = sha256(experiment / "frozen-artifacts.json")
    require(match.group(1) == actual, f"frozen-artifacts manifest digest mismatch: want {match.group(1)}, got {actual}")


def verify(experiment: Path = EXPERIMENT, repository: Path = REPOSITORY) -> None:
    verify_fileset(experiment)
    verify_contract_document(experiment, repository)
    verify_fixture_bindings(experiment, repository)
    verify_inventory(experiment)
    verify_collector(experiment)
    verify_candidates(experiment)
    verify_measurements(experiment)
    verify_blocker_and_schema(experiment)
    verify_frozen_artifacts(experiment)


def main() -> int:
    try:
        verify()
    except (OSError, VerificationError) as error:
        print(f"verify-e06-contract: {error}", file=sys.stderr)
        return 1
    print("verify-e06-contract: Phase A inventory and measurement contract valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
