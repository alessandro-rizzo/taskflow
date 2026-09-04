#!/usr/bin/env python3
"""Verify immutable E06 Phase A plus result-free Phase-B preparation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


PHASE_B = Path(__file__).resolve().parents[1]
PHASE_A = PHASE_B.parent
REPOSITORY = PHASE_B.parents[2]
PHASE_A_REVISION = "098035bf29656c3fd3b3991224a98fdded3453b7"

PHASE_A_FILES = {
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
    "tests/test_verify_contract.py"
}

EXPECTED_PHASE_B_FILES = {
    "README.md",
    "Taskfile.yml",
    "candidate-resolution.json",
    "command-ledger.json",
    "contract.json",
    "decision-matrix.json",
    "fixture/E06SmokeApp/E06SmokeApp.xcodeproj/project.pbxproj",
    "fixture/E06SmokeApp/E06SmokeApp.xcodeproj/xcshareddata/xcschemes/E06SmokeApp.xcscheme",
    "fixture/E06SmokeApp/E06SmokeApp/AppDelegate.swift",
    "frozen-artifacts.json",
    "manifest-resolution.json",
    "protocol.sha256",
    "reset-policy.json",
    "runner-profile.json",
    "sandbox-policy.json",
    "scope-hashes.json",
    "scripts/guard.py",
    "scripts/runner.py",
    "scripts/verify_phase_b.py",
    "tests/test_phase_b.py"
}


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
    require(isinstance(value, dict), f"{path}: expected JSON object")
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return sha256_bytes(encoded)


def git_bytes(repository: Path, revision: str, relative: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{revision}:{relative}"],
        cwd=repository,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    require(completed.returncode == 0, f"cannot materialize {revision}:{relative}: {completed.stderr.decode('utf-8', 'replace').strip()}")
    return completed.stdout


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_phase_a_anchor(repository: Path = REPOSITORY, phase_a: Path = PHASE_A) -> None:
    with tempfile.TemporaryDirectory(prefix="taskflow-e06-phase-a-anchor-") as temporary:
        snapshot_repository = Path(temporary) / "repository"
        snapshot_experiment = snapshot_repository / "experiments/e06-macos-feasibility"
        for relative in sorted(PHASE_A_FILES):
            data = git_bytes(repository, PHASE_A_REVISION, f"experiments/e06-macos-feasibility/{relative}")
            destination = snapshot_experiment / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            require((phase_a / relative).read_bytes() == data, f"live Phase-A byte drift: {relative}")
        bindings = json.loads((snapshot_experiment / "fixture-bindings.json").read_text(encoding="utf-8"))
        bound_paths = [item["path"] for binding in bindings["bindings"] for item in binding["files"]]
        for relative in ["docs/product-specification.md", "docs/roadmap.md", *bound_paths]:
            destination = snapshot_repository / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(git_bytes(repository, PHASE_A_REVISION, relative))
        snapshot_verifier = load_module("e06_phase_a_snapshot", snapshot_experiment / "scripts/verify_contract.py")
        snapshot_verifier.verify(snapshot_experiment, snapshot_repository)


def verify_fileset(phase_b: Path) -> None:
    found = {
        path.relative_to(phase_b).as_posix()
        for path in phase_b.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc" and path.name != ".DS_Store"
    }
    require(found == EXPECTED_PHASE_B_FILES, f"Phase-B fileset mismatch: missing={sorted(EXPECTED_PHASE_B_FILES - found)} extra={sorted(found - EXPECTED_PHASE_B_FILES)}")
    forbidden = {"evidence", "results", "measurements", "scorecard.json", "execution-manifest.approved.json", "decision.json"}
    require(not any(path.name in forbidden for path in phase_b.iterdir()), "premature Phase-B result or approved manifest")


def verify_frozen(phase_b: Path) -> None:
    manifest = load_object(phase_b / "frozen-artifacts.json")
    expected = sorted(EXPECTED_PHASE_B_FILES - {"frozen-artifacts.json", "protocol.sha256"})
    artifacts = manifest.get("artifacts")
    require(isinstance(artifacts, list) and [item.get("path") for item in artifacts] == expected, "frozen artifact set/order drifted")
    for item in artifacts:
        require(re.fullmatch(r"[0-9a-f]{64}", item.get("sha256", "")) is not None, f"invalid artifact digest: {item.get('path')}")
        require(sha256(phase_b / item["path"]) == item["sha256"], f"frozen Phase-B artifact drift: {item['path']}")
    line = (phase_b / "protocol.sha256").read_text(encoding="utf-8").strip()
    require(line == f"{sha256(phase_b / 'frozen-artifacts.json')}  frozen-artifacts.json", "Phase-B protocol digest mismatch")


def verify_scope(phase_b: Path, repository: Path) -> None:
    scope = load_object(phase_b / "scope-hashes.json")
    require(scope.get("accepted_phase_a_revision") == PHASE_A_REVISION, "scope Phase-A revision drifted")
    bindings = scope.get("bindings")
    require(isinstance(bindings, list) and bindings, "scope bindings missing")
    paths = [item.get("path") for item in bindings]
    require(paths == sorted(paths) and len(paths) == len(set(paths)), "scope paths must be unique and sorted")
    for item in bindings:
        require(sha256(repository / item["path"]) == item.get("sha256"), f"scope binding drift: {item.get('path')}")


def verify_profile(phase_b: Path) -> None:
    profile = load_object(phase_b / "runner-profile.json")
    components = profile.get("components")
    require(isinstance(components, dict) and list(components) == sorted(components), "runner components must be sorted")
    for relative, digest in components.items():
        require(sha256(phase_b / relative) == digest, f"runner component drift: {relative}")
    require(profile.get("runner_digest") == canonical_digest(components), "runner digest drifted")
    require(profile.get("execution_entrypoint") is None, "execution entrypoint must be absent")
    resolution = load_object(phase_b / "manifest-resolution.json")
    resolved_profile = resolution["resolved"]["profile"]
    require(resolved_profile.get("runner_digest") == profile["runner_digest"], "resolution runner digest drifted")
    require(resolved_profile.get("sandbox_policy_digest") == sha256(phase_b / "sandbox-policy.json"), "sandbox policy digest drifted")
    require(resolved_profile.get("reset_policy_digest") == sha256(phase_b / "reset-policy.json"), "reset policy digest drifted")
    without_expected = dict(resolved_profile)
    expected = without_expected.pop("expected_profile_digest")
    require(expected == canonical_digest(without_expected), "expected profile digest drifted")


def verify_semantics(phase_b: Path, repository: Path) -> None:
    contract = load_object(phase_b / "contract.json")
    require(contract.get("status") == "repository-preparation-only", "contract status drifted")
    require(contract.get("accepted_phase_a", {}).get("revision") == PHASE_A_REVISION, "contract anchor drifted")
    forbidden = contract.get("repository_phase_forbids", [])
    for item in ("xcodebuild or CoreSimulator invocation", "VM or simulator lifecycle mutation", "selected E06 decision branch", "completed external execution manifest"):
        require(item in forbidden, f"contract missing prohibition: {item}")
    candidates = load_object(phase_b / "candidate-resolution.json")
    workers = candidates.get("worker_candidates", [])
    require([item.get("id") for item in workers] == ["warm-immutable-vm-restore", "warm-vm-apfs-workspaces", "vm-per-namespace", "trusted-native-host", "coarse-external-runner"], "worker order drifted")
    require([item.get("status") for item in workers].count("blocked-awaiting-separate-approval") == 1, "exactly one candidate must await approval")
    require(candidates.get("execution_count") == 0 and candidates.get("selected_branch") is None, "candidate result exists prematurely")
    simulators = candidates.get("simulator_candidates", [])
    require([item.get("id") for item in simulators] == ["fresh-create-boot", "erase-reset", "clone-from-golden"], "simulator order drifted")
    decision = load_object(phase_b / "decision-matrix.json")
    require(decision.get("precedence") == ["stop-or-narrow", "serialized-macos-capacity", "trusted-native-host"], "decision precedence drifted")
    require(decision.get("selected_branch") is None, "decision selected prematurely")
    require(decision.get("threshold_relaxation_after_results") is False, "threshold relaxation must remain forbidden")
    guard_module = load_module("e06_phase_b_guard", phase_b / "scripts/guard.py")
    guard_module.validate(phase_b)
    app = (phase_b / "fixture/E06SmokeApp/E06SmokeApp/AppDelegate.swift").read_text(encoding="utf-8")
    project = (phase_b / "fixture/E06SmokeApp/E06SmokeApp.xcodeproj/project.pbxproj").read_text(encoding="utf-8")
    scheme = (phase_b / "fixture/E06SmokeApp/E06SmokeApp.xcodeproj/xcshareddata/xcschemes/E06SmokeApp.xcscheme").read_text(encoding="utf-8")
    for marker in ("UserDefaults", "SecItemCopyMatching", "taskflow-e06-marker.txt", "TASKFLOW_E06_RESULT"):
        require(marker in app, f"smoke fixture lacks {marker}")
    require("dev.taskflow.e06.smoke" in project and "CODE_SIGNING_ALLOWED = NO" in project, "smoke project identity or signing boundary missing")
    require("BlueprintIdentifier=\"A00000000000000000000008\"" in scheme, "shared smoke scheme target drifted")
    adr = (repository / "docs/decisions/0010-e06-macos-feasibility.md").read_text(encoding="utf-8")
    require("Status: proposed; awaiting separately approved Phase-B execution" in adr, "ADR must remain proposed")
    require("Pending separately approved execution" in adr, "ADR decision must remain pending")


def verify_phase_b(phase_b: Path = PHASE_B, repository: Path = REPOSITORY, verify_anchor: bool = True) -> None:
    if verify_anchor:
        verify_phase_a_anchor(repository, phase_b.parent)
    verify_fileset(phase_b)
    verify_frozen(phase_b)
    verify_scope(phase_b, repository)
    verify_profile(phase_b)
    verify_semantics(phase_b, repository)


def main() -> int:
    try:
        verify_phase_b()
    except (OSError, json.JSONDecodeError, VerificationError) as error:
        print(f"verify-e06-phase-b: {error}")
        return 1
    print("verify-e06-phase-b: immutable Phase A and result-free Phase-B preparation valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
