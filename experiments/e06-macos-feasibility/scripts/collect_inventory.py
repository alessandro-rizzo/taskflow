#!/usr/bin/env python3
"""Print a sanitized E06 inventory using non-mutating local queries only.

The collector never writes a file, calls CoreSimulator, contacts a provider,
downloads an image, inspects credentials, or performs a lifecycle action.
Committed inventory is a reviewed snapshot; this command is only a reproducible
way to refresh comparable read-only facts into stdout for review.
"""

from __future__ import annotations

import json
import plistlib
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


SAFE_QUERY_EXECUTABLES = frozenset(
    {
        "sw_vers",
        "uname",
        "system_profiler",
        "xcode-select",
        "xcodebuild",
        "limactl",
        "colima",
        "docker",
    }
)

TOOL_NAMES = (
    "tart",
    "orchard",
    "orchardctl",
    "vfkit",
    "utmctl",
    "prlctl",
    "VBoxManage",
    "ipsw",
    "limactl",
    "colima",
    "docker",
    "cp",
    "ditto",
    "diskutil",
    "hdiutil",
    "tmutil",
    "mount_apfs",
    "xcrun",
    "xcodebuild",
)

VERSION_QUERIES = {
    "limactl": ("limactl", "--version"),
    "colima": ("colima", "version"),
    "docker": ("docker", "--version"),
}

SIMULATOR_IMAGES = Path("/Library/Developer/CoreSimulator/Images/images.plist")
SIMULATOR_DEVICES = Path.home() / "Library/Developer/CoreSimulator/Devices"


def query(argv: Sequence[str]) -> dict[str, Any]:
    """Run one allowlisted query without a shell and capture its result."""

    if not argv or argv[0] not in SAFE_QUERY_EXECUTABLES:
        raise ValueError(f"query executable is not allowlisted: {argv!r}")
    completed = subprocess.run(
        list(argv),
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )
    return {
        "argv": list(argv),
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def stdout(argv: Sequence[str]) -> str:
    result = query(argv)
    if result["exit_code"] != 0:
        return ""
    return result["stdout"].strip()


def parse_label(text: str, label: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(label)}:\s*(.+?)\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


def collect_host() -> dict[str, Any]:
    profile = stdout(
        (
            "system_profiler",
            "SPHardwareDataType",
            "SPSoftwareDataType",
            "-detailLevel",
            "mini",
        )
    )
    memory = parse_label(profile, "Memory")
    memory_match = re.fullmatch(r"([0-9]+) GB", memory or "")
    core_text = parse_label(profile, "Total Number of Cores")
    core_match = re.match(r"([0-9]+)", core_text or "")
    disk = shutil.disk_usage("/private/tmp")
    return {
        "hardware": {
            "model_name": parse_label(profile, "Model Name"),
            "model_identifier": parse_label(profile, "Model Identifier"),
            "model_number": parse_label(profile, "Model Number"),
            "chip": parse_label(profile, "Chip"),
            "architecture": stdout(("uname", "-m")),
            "core_count": int(core_match.group(1)) if core_match else None,
            "core_description": core_text,
            "memory_gib": int(memory_match.group(1)) if memory_match else None,
        },
        "operating_system": {
            "name": "macOS",
            "version": stdout(("sw_vers", "-productVersion")),
            "build": stdout(("sw_vers", "-buildVersion")),
            "kernel": stdout(("uname", "-r")),
        },
        "virtualization_framework_present": Path(
            "/System/Library/Frameworks/Virtualization.framework"
        ).is_dir(),
        "hypervisor_framework_present": Path(
            "/System/Library/Frameworks/Hypervisor.framework"
        ).is_dir(),
        "storage_bytes": {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
        },
        "privacy": {
            "host_serial_recorded": False,
            "hardware_uuid_recorded": False,
            "user_identity_recorded": False,
        },
    }


def parse_xcode_version(text: str) -> dict[str, str | None]:
    lines = [line.strip() for line in text.splitlines()]
    version = next(
        (line.removeprefix("Xcode ") for line in lines if line.startswith("Xcode ")),
        None,
    )
    build = next(
        (
            line.removeprefix("Build version ")
            for line in lines
            if line.startswith("Build version ")
        ),
        None,
    )
    return {
        "version": version,
        "build": build,
    }


def collect_tooling() -> dict[str, Any]:
    xcode_version = query(("xcodebuild", "-version"))
    first_launch = query(("xcodebuild", "-checkFirstLaunchStatus"))
    showsdks = query(("xcodebuild", "-showsdks"))
    tools: dict[str, Any] = {}
    for name in TOOL_NAMES:
        location = shutil.which(name)
        tools[name] = {"present": location is not None, "path": location}
        if location and name in VERSION_QUERIES:
            result = query(VERSION_QUERIES[name])
            tools[name]["version_output"] = result["stdout"].strip()
            tools[name]["version_exit_code"] = result["exit_code"]
    return {
        "developer_directory": stdout(("xcode-select", "-p")),
        "xcode": {
            **parse_xcode_version(xcode_version["stdout"]),
            "version_exit_code": xcode_version["exit_code"],
            "first_launch_status_exit": first_launch["exit_code"],
            "showsdks_exit_code": showsdks["exit_code"],
            "showsdks_stdout": showsdks["stdout"].strip(),
        },
        "tools": tools,
        "network_contacted": False,
        "provider_queried": False,
    }


def load_plist(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as handle:
            value = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException):
        return None
    return value if isinstance(value, dict) else None


def sanitized_device(document: dict[str, Any]) -> dict[str, Any]:
    """Whitelist non-unique device facts; deliberately drop UDID."""

    result = {
        "name": document.get("name"),
        "device_type": document.get("deviceType"),
        "runtime": document.get("runtime"),
        "state": document.get("state"),
        "is_deleted": document.get("isDeleted"),
        "is_ephemeral": document.get("isEphemeral"),
    }
    if document.get("lastBootedAt") is not None:
        result["last_booted_at"] = str(document["lastBootedAt"])
    return result


def sanitized_runtime(document: dict[str, Any]) -> dict[str, Any]:
    info = document.get("runtimeInfo", {})
    signature = document.get("signatureState", {})
    write_policy = document.get("writePolicy", {})
    return {
        "bundle_identifier": info.get("bundleIdentifier"),
        "build": info.get("build"),
        "architectures": info.get("supportedArchitectures", []),
        "signature_states": sorted(signature) if isinstance(signature, dict) else [],
        "write_policies": sorted(write_policy) if isinstance(write_policy, dict) else [],
    }


def collect_simulator() -> dict[str, Any]:
    images = load_plist(SIMULATOR_IMAGES) or {}
    runtimes = [
        sanitized_runtime(item)
        for item in images.get("images", [])
        if isinstance(item, dict)
    ]
    devices: list[dict[str, Any]] = []
    if SIMULATOR_DEVICES.is_dir():
        for path in sorted(SIMULATOR_DEVICES.glob("*/device.plist")):
            document = load_plist(path)
            if document is not None:
                devices.append(sanitized_device(document))
    state_counts = Counter(str(item.get("state")) for item in devices)
    return {
        "collection_mode": "sanitized-plist-read-only",
        "runtime_images": runtimes,
        "default_device_set": {
            "allowed_for_e06": False,
            "device_count": len(devices),
            "state_counts": dict(sorted(state_counts.items())),
            "devices": devices,
            "device_udids_recorded": False,
        },
        "live_simctl_query": {
            "attempted_by_collector": False,
            "status": "not-attempted-by-design",
        },
    }


def collect() -> dict[str, Any]:
    return {
        "format_version": "taskflow-e06-read-only-collector/v1-experimental",
        "contract": {
            "writes_files": False,
            "network_allowed": False,
            "provider_queries_allowed": False,
            "coresimulator_queries_allowed": False,
            "credentials_allowed": False,
        },
        "host": collect_host(),
        "tooling": collect_tooling(),
        "simulator": collect_simulator(),
    }


def main() -> int:
    print(json.dumps(collect(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
