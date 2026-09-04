#!/usr/bin/env python3
"""Validate the proposed E06 native-host ledger without executing it."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


PHASE_B = Path(__file__).resolve().parents[1]
MUTABLE_ROOT = Path("/private/tmp/taskflow-e06-native-a")
DEVICE_SET = MUTABLE_ROOT / "CoreSimulator"
SIMULATOR_PREFIX = "taskflow-e06-native-a-"


class GuardError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GuardError(message)


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path}: expected JSON object")
    return value


def normalized(path: str) -> Path:
    require(path.startswith("/"), f"path is not absolute: {path}")
    require(".." not in Path(path).parts, f"path traverses parent: {path}")
    return Path(os.path.normpath(path))


def require_owned_path(path: str, allow_root: bool = True) -> None:
    candidate = normalized(path)
    common = Path(os.path.commonpath((str(MUTABLE_ROOT), str(candidate))))
    require(common == MUTABLE_ROOT, f"path escapes mutable root: {path}")
    if not allow_root:
        require(candidate != MUTABLE_ROOT, f"operation requires a descendant, got root: {path}")


def validate_resolution(resolution: dict[str, Any]) -> None:
    require(resolution.get("status") == "blocked-unresolved-not-executable", "resolution must remain blocked")
    require(resolution.get("execution_count") == 0, "resolution execution count must remain zero")
    require(resolution.get("plan_approval_is_not_execution_approval") is True, "separate execution approval must be explicit")
    resolved = resolution.get("resolved", {})
    require(resolved.get("manifest_id") == "taskflow-e06-native-a", "manifest id drifted")
    require(resolved.get("candidate_id") == "trusted-native-host", "candidate drifted")
    paths = resolved.get("paths", {})
    require(paths.get("mutable_root") == str(MUTABLE_ROOT), "mutable root drifted")
    require(paths.get("custom_device_set_root") == str(DEVICE_SET), "custom device set drifted")
    require(paths.get("default_simulator_set_forbidden") is True, "default simulator set must be forbidden")
    for key in ("workspace_roots", "home_roots", "tmp_roots", "derived_data_roots", "result_roots"):
        values = paths.get(key)
        require(isinstance(values, list) and len(values) == 2, f"{key}: expected two namespace paths")
        for value in values:
            require_owned_path(value, allow_root=False)
    resources = resolved.get("resources", {})
    require(resources.get("concurrency_levels") == [1, 2, 3, 4], "concurrency levels drifted")
    require(resources.get("repetitions_per_level") == 5, "concurrency repetitions drifted")
    require(resources.get("min_free_ram_gib") == 16, "RAM floor drifted")
    require(resources.get("min_free_disk_gib") == 200, "disk floor drifted")
    require(resources.get("thermal_stop_signal") == "serious", "thermal stop drifted")
    require(resources.get("per_command_timeout_seconds") == 900, "command timeout drifted")


def validate_ledger(ledger: dict[str, Any]) -> None:
    require(ledger.get("status") == "non-executing-proposal", "ledger must remain non-executing")
    require(ledger.get("execution_count") == 0, "ledger execution count must remain zero")
    require(ledger.get("custom_device_set") == str(DEVICE_SET), "ledger device set drifted")
    commands = ledger.get("commands")
    require(isinstance(commands, list) and commands, "ledger commands are required")
    ids: set[str] = set()
    banned = {"killall", "tart", "orchard", "curl", "wget", "brew"}
    for command in commands:
        command_id = command.get("id")
        require(isinstance(command_id, str) and command_id not in ids, f"duplicate or invalid command id: {command_id}")
        ids.add(command_id)
        argv = command.get("argv")
        require(isinstance(argv, list) and argv and all(isinstance(item, str) for item in argv), f"{command_id}: invalid argv")
        require(not any(item in banned for item in argv), f"{command_id}: forbidden executable or argument")
        require("-rf" not in argv and "--recursive" not in argv, f"{command_id}: broad deletion flag forbidden")
        for target in command.get("targets", []):
            if target.startswith("/"):
                require_owned_path(target)
            else:
                require(target.startswith(SIMULATOR_PREFIX), f"{command_id}: unowned named target: {target}")
        if len(argv) >= 2 and argv[1] == "simctl":
            require("--set" in argv, f"{command_id}: simctl command lacks --set")
            set_index = argv.index("--set")
            require(set_index + 1 < len(argv) and argv[set_index + 1] == str(DEVICE_SET), f"{command_id}: wrong simulator set")
        if argv[0].endswith("xcodebuild"):
            require("-derivedDataPath" in argv, f"{command_id}: xcodebuild lacks DerivedData path")
            index = argv.index("-derivedDataPath")
            require(index + 1 < len(argv), f"{command_id}: missing DerivedData value")
            require_owned_path(argv[index + 1], allow_root=False)
            require("CODE_SIGNING_ALLOWED=NO" in argv, f"{command_id}: signing must be disabled")
    cleanup = ledger.get("cleanup_allowlist", {})
    require(cleanup.get("immutable_base_delete_forbidden") is True, "immutable deletion must be forbidden")
    require(cleanup.get("broad_process_kill_forbidden") is True, "broad process kill must be forbidden")
    require(cleanup.get("simulator_name_prefix") == SIMULATOR_PREFIX, "cleanup simulator prefix drifted")
    for path in cleanup.get("paths", []):
        require_owned_path(path)


def validate(phase_b: Path = PHASE_B) -> dict[str, Any]:
    resolution = load_object(phase_b / "manifest-resolution.json")
    ledger = load_object(phase_b / "command-ledger.json")
    validate_resolution(resolution)
    validate_ledger(ledger)
    return {
        "candidate": resolution["resolved"]["candidate_id"],
        "command_count": len(ledger["commands"]),
        "custom_device_set": ledger["custom_device_set"],
        "execution_allowed": False,
        "manifest_status": resolution["status"],
        "mutable_root": str(MUTABLE_ROOT)
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="validate and print the proposed ledger")
    args = parser.parse_args()
    if not args.dry_run:
        parser.error("repository-only guard supports --dry-run only")
    try:
        result = validate()
    except (OSError, json.JSONDecodeError, GuardError) as error:
        print(f"e06-guard: {error}")
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
