#!/usr/bin/env python3
"""Build the deterministic, fully expanded E06 native execution ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


EXECUTION = Path(__file__).resolve().parents[1]
ROOT = "/private/tmp/taskflow-e06-native-a"
DEVICE_SET = f"{ROOT}/CoreSimulator"
PREFIX = "taskflow-e06-native-a-"
FIXTURE = "experiments/e06-macos-feasibility/phase-b/fixture/E06SmokeApp"
EVIDENCE = "experiments/e06-macos-feasibility/evidence/taskflow-e06-native-a"
NAMESPACES = ("namespace-a", "namespace-b", "namespace-c", "namespace-d")
MECHANISMS = ("fresh-create-boot", "erase-reset", "clone-from-golden")
CALLER_LEASE_TTL_SECONDS = 1.0
CALLER_HEARTBEAT_SECONDS = 0.25
CHILD_SANDBOX_PROFILE = "(version 1) (deny default) (allow file-read*) (allow file-write* (literal \"/private/tmp/taskflow-e06-native-a\") (subpath \"/private/tmp/taskflow-e06-native-a\")) (allow process-exec process-fork) (allow mach-lookup) (allow ipc-posix*) (allow sysctl-read)"


def command(identifier: str, phase: str, argv: list[str], targets: list[str], *, mutates: bool, prerequisites: list[str] | None = None, evidence: str | None = None, child_handle: str | None = None, expected_result: str = "success") -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": identifier,
        "phase": phase,
        "kind": "child-command" if child_handle else "command",
        "argv": ["/usr/bin/sandbox-exec", "-p", CHILD_SANDBOX_PROFILE, *argv],
        "targets": targets,
        "mutates": mutates,
        "expected_result": expected_result,
        "timeout_seconds": 900,
        "prerequisites": prerequisites or [],
        "evidence": evidence or f"{EVIDENCE}/raw/{identifier}.json",
    }
    if child_handle:
        value["child_handle"] = child_handle
    return value


def effect(identifier: str, phase: str, action: str, targets: list[str], *, mutates: bool = False, prerequisites: list[str] | None = None, evidence: str | None = None, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": identifier,
        "phase": phase,
        "kind": "effect",
        "action": action,
        "parameters": parameters or {},
        "targets": targets,
        "mutates": mutates,
        "timeout_seconds": 900,
        "prerequisites": prerequisites or [],
        "evidence": evidence or f"{EVIDENCE}/raw/{identifier}.json",
    }


def namespace_paths(namespace: str) -> list[str]:
    base = f"{ROOT}/{namespace}"
    return [f"{base}/workspace", f"{base}/home", f"{base}/tmp", f"{base}/DerivedData", f"{base}/results"]


def mkdir_namespace(identifier: str, phase: str, namespace: str, prerequisites: list[str] | None = None) -> dict[str, Any]:
    paths = namespace_paths(namespace)
    return command(identifier, phase, ["/bin/mkdir", "-p", *paths], paths, mutates=True, prerequisites=prerequisites)


def remove_namespace(identifier: str, phase: str, namespace: str, prerequisites: list[str] | None = None) -> dict[str, Any]:
    path = f"{ROOT}/{namespace}"
    return command(identifier, phase, ["/bin/rm", "-rf", "--", path], [path], mutates=True, prerequisites=prerequisites)


def copy_fixture(identifier: str, phase: str, namespace: str, prerequisites: list[str]) -> dict[str, Any]:
    target = f"{ROOT}/{namespace}/workspace/E06SmokeApp"
    return command(identifier, phase, ["/usr/bin/ditto", FIXTURE, target], [target], mutates=True, prerequisites=prerequisites)


def simctl(identifier: str, phase: str, arguments: list[str], targets: list[str], *, mutates: bool, prerequisites: list[str] | None = None) -> dict[str, Any]:
    return command(identifier, phase, ["/usr/bin/xcrun", "simctl", "--set", DEVICE_SET, *arguments], targets, mutates=mutates, prerequisites=prerequisites)


def capacity_commands(operations: list[dict[str, Any]], phase: str, label: str, prerequisite: str) -> list[str]:
    memory = f"{phase}.{label}.capacity-memory"
    disk = f"{phase}.{label}.capacity-disk"
    thermal = f"{phase}.{label}.capacity-thermal"
    operations.append(command(memory, phase, ["/usr/bin/vm_stat"], [], mutates=False, prerequisites=[prerequisite]))
    operations.append(command(disk, phase, ["/bin/df", "-Pk", "/private/tmp"], [], mutates=False, prerequisites=[memory]))
    operations.append(command(thermal, phase, ["/usr/bin/swift", "-e", "import Foundation; print(ProcessInfo.processInfo.thermalState.rawValue)"], [f"{ROOT}/controller/cache"], mutates=True, prerequisites=[disk]))
    return [memory, disk, thermal]


def grouped(operation: dict[str, Any], group: str, step: int) -> dict[str, Any]:
    operation["parallel_group"] = group
    operation["parallel_step"] = step
    return operation


def concurrent_native_probe(operations: list[dict[str, Any]], phase: str, label: str, namespaces: list[str], prerequisite: str, assertion_action: str, assertion_parameters: dict[str, Any]) -> str:
    group = f"{phase}.{label}"
    prior: dict[str, str] = {namespace: prerequisite for namespace in namespaces}
    devices = {namespace: f"{PREFIX}{phase.replace('.', '-')}-{label}-{namespace}" for namespace in namespaces}
    identity_ids: list[str] = []
    launch_ids: list[str] = []
    cleanup_ids: list[str] = []
    delete_ids: list[str] = []

    for step, action in enumerate(("remove", "mkdir", "copy", "create", "boot", "ready", "identity", "build", "install", "launch"), start=1):
        for namespace in namespaces:
            identifier = f"{group}.{namespace}.{action}"
            device = devices[namespace]
            if action == "remove":
                operation = remove_namespace(identifier, phase, namespace, [prior[namespace]])
            elif action == "mkdir":
                operation = mkdir_namespace(identifier, phase, namespace, [prior[namespace]])
            elif action == "copy":
                operation = copy_fixture(identifier, phase, namespace, [prior[namespace]])
            elif action == "create":
                operation = simctl(identifier, phase, ["create", device, "com.apple.CoreSimulator.SimDeviceType.iPhone-17", "com.apple.CoreSimulator.SimRuntime.iOS-26-5"], [device], mutates=True, prerequisites=[prior[namespace]])
            elif action == "boot":
                operation = simctl(identifier, phase, ["boot", device], [device], mutates=True, prerequisites=[prior[namespace]])
            elif action == "ready":
                operation = simctl(identifier, phase, ["bootstatus", device, "-b"], [device], mutates=False, prerequisites=[prior[namespace]])
            elif action == "identity":
                operation = simctl(identifier, phase, ["list", "devices", "--json"], [DEVICE_SET], mutates=False, prerequisites=[prior[namespace]])
                identity_ids.append(identifier)
            elif action == "build":
                derived = f"{ROOT}/{namespace}/DerivedData"
                project = f"{ROOT}/{namespace}/workspace/E06SmokeApp/E06SmokeApp.xcodeproj"
                operation = command(identifier, phase, ["/usr/bin/xcodebuild", "-project", project, "-scheme", "E06SmokeApp", "-sdk", "iphonesimulator", "-derivedDataPath", derived, "CODE_SIGNING_ALLOWED=NO", "build"], [derived], mutates=True, prerequisites=[prior[namespace]])
            elif action == "install":
                app = f"{ROOT}/{namespace}/DerivedData/Build/Products/Debug-iphonesimulator/E06SmokeApp.app"
                operation = simctl(identifier, phase, ["install", device, app], [device], mutates=True, prerequisites=[prior[namespace]])
            else:
                operation = simctl(identifier, phase, ["launch", "--console-pty", device, "dev.taskflow.e06.smoke", "--taskflow-namespace", namespace], [device], mutates=True, prerequisites=[prior[namespace]])
                launch_ids.append(identifier)
            operations.append(grouped(operation, group, step))
            prior[namespace] = identifier

    for step, action in ((11, "shutdown"), (12, "delete")):
        for namespace in namespaces:
            identifier = f"{group}.{namespace}.{action}"
            operation = simctl(identifier, phase, [action, devices[namespace]], [devices[namespace]], mutates=True, prerequisites=[prior[namespace]])
            operations.append(grouped(operation, group, step))
            prior[namespace] = identifier
            cleanup_ids.append(identifier)
            if action == "delete":
                delete_ids.append(identifier)

    post_cleanup_identity = f"{group}.post-cleanup-identity"
    operations.append(simctl(post_cleanup_identity, phase, ["list", "devices", "--json"], [DEVICE_SET], mutates=False, prerequisites=delete_ids))
    post_capacity = capacity_commands(operations, phase, f"{label}.post", post_cleanup_identity)
    verify = f"{group}.verify"
    parameters = dict(assertion_parameters)
    pre_capacity = parameters.pop("capacity_operation_ids")
    parameters.update({
        "namespaces": namespaces,
        "devices": [devices[namespace] for namespace in namespaces],
        "lease_ids": [f"lease-{group}-{namespace}" for namespace in namespaces],
        "identity_operation_ids": identity_ids,
        "launch_operation_ids": launch_ids,
        "cleanup_operation_ids": cleanup_ids,
        "post_cleanup_identity_operation_id": post_cleanup_identity,
        "pre_capacity_operation_ids": pre_capacity,
        "post_capacity_operation_ids": post_capacity,
        "contamination_dimensions": ["workspace", "HOME", "TMPDIR", "DerivedData", "installed-app-data", "preferences", "keychain-canary-name", "lease-identifier"],
        "cleanup_deadline_seconds": 30,
    })
    operations.append(effect(verify, phase, assertion_action, [*[path for namespace in namespaces for path in namespace_paths(namespace)], *[devices[namespace] for namespace in namespaces]], prerequisites=[post_capacity[-1]], parameters=parameters))
    return verify


def lifecycle_prepare(operations: list[dict[str, Any]], phase: str, mechanism: str, label: str, prerequisite: str) -> tuple[str, str]:
    device = f"{PREFIX}{phase}-{mechanism}-{label}"
    if mechanism == "fresh-create-boot":
        create = f"{phase}.{mechanism}.{label}.create"
        operations.append(simctl(create, phase, ["create", device, "com.apple.CoreSimulator.SimDeviceType.iPhone-17", "com.apple.CoreSimulator.SimRuntime.iOS-26-5"], [device], mutates=True, prerequisites=[prerequisite]))
        boot_prerequisite = create
    elif mechanism == "erase-reset":
        create = f"{phase}.{mechanism}.{label}.create"
        erase = f"{phase}.{mechanism}.{label}.erase-before"
        operations.append(simctl(create, phase, ["create", device, "com.apple.CoreSimulator.SimDeviceType.iPhone-17", "com.apple.CoreSimulator.SimRuntime.iOS-26-5"], [device], mutates=True, prerequisites=[prerequisite]))
        operations.append(simctl(erase, phase, ["erase", device], [device], mutates=True, prerequisites=[create]))
        boot_prerequisite = erase
    else:
        golden = f"{PREFIX}{phase}-{mechanism}-golden"
        golden_create = f"{phase}.{mechanism}.{label}.golden-create"
        golden_boot = f"{phase}.{mechanism}.{label}.golden-boot"
        golden_ready = f"{phase}.{mechanism}.{label}.golden-ready"
        golden_shutdown = f"{phase}.{mechanism}.{label}.golden-shutdown"
        clone = f"{phase}.{mechanism}.{label}.clone"
        operations.append(simctl(golden_create, phase, ["create", golden, "com.apple.CoreSimulator.SimDeviceType.iPhone-17", "com.apple.CoreSimulator.SimRuntime.iOS-26-5"], [golden], mutates=True, prerequisites=[prerequisite]))
        operations.append(simctl(golden_boot, phase, ["boot", golden], [golden], mutates=True, prerequisites=[golden_create]))
        operations.append(simctl(golden_ready, phase, ["bootstatus", golden, "-b"], [golden], mutates=False, prerequisites=[golden_boot]))
        operations.append(simctl(golden_shutdown, phase, ["shutdown", golden], [golden], mutates=True, prerequisites=[golden_ready]))
        operations.append(simctl(clone, phase, ["clone", golden, device], [golden, device], mutates=True, prerequisites=[golden_shutdown]))
        boot_prerequisite = clone
    boot = f"{phase}.{mechanism}.{label}.boot"
    ready = f"{phase}.{mechanism}.{label}.ready"
    operations.append(simctl(boot, phase, ["boot", device], [device], mutates=True, prerequisites=[boot_prerequisite]))
    operations.append(simctl(ready, phase, ["bootstatus", device, "-b"], [device], mutates=False, prerequisites=[boot]))
    return device, ready


def lifecycle_cleanup(operations: list[dict[str, Any]], phase: str, mechanism: str, label: str, device: str, prerequisite: str) -> tuple[list[str], list[str], str]:
    shutdown = f"{phase}.{mechanism}.{label}.shutdown"
    operations.append(simctl(shutdown, phase, ["shutdown", device], [device], mutates=True, prerequisites=[prerequisite]))
    reset_ids = [shutdown]
    if mechanism == "erase-reset":
        erase = f"{phase}.{mechanism}.{label}.erase-after"
        cleanup = f"{phase}.{mechanism}.{label}.delete"
        operations.append(simctl(erase, phase, ["erase", device], [device], mutates=True, prerequisites=[shutdown]))
        operations.append(simctl(cleanup, phase, ["delete", device], [device], mutates=True, prerequisites=[erase]))
        reset_ids.append(erase)
    else:
        cleanup = f"{phase}.{mechanism}.{label}.delete"
        operations.append(simctl(cleanup, phase, ["delete", device], [device], mutates=True, prerequisites=[shutdown]))
    cleanup_ids = [cleanup]
    if mechanism == "clone-from-golden":
        golden = f"{PREFIX}{phase}-{mechanism}-golden"
        delete_golden = f"{phase}.{mechanism}.{label}.delete-golden"
        operations.append(simctl(delete_golden, phase, ["delete", golden], [golden], mutates=True, prerequisites=[cleanup]))
        cleanup = delete_golden
        cleanup_ids.append(delete_golden)
    return reset_ids, cleanup_ids, cleanup


def caller_loss_probe(operations: list[dict[str, Any]], label: str, namespace: str, prerequisite: str) -> str:
    phase = "fault.caller-loss"
    prefix = f"{phase}.{label}"
    device = f"{PREFIX}fault-caller-loss-{label}"
    retry_device = f"{PREFIX}fault-caller-loss-retry-{label}"
    lease_id = f"lease-fault-caller-loss-{label}-{namespace}"
    lease_path = f"{ROOT}/controller/leases/{lease_id}.json"
    derived = f"{ROOT}/{namespace}/DerivedData"
    project = f"{ROOT}/{namespace}/workspace/E06SmokeApp/E06SmokeApp.xcodeproj"
    app = f"{derived}/Build/Products/Debug-iphonesimulator/E06SmokeApp.app"

    remove = f"{prefix}.prepare-remove"
    mkdir = f"{prefix}.prepare-mkdir"
    copy = f"{prefix}.prepare-copy"
    build = f"{prefix}.build"
    create = f"{prefix}.create"
    boot = f"{prefix}.boot"
    ready = f"{prefix}.ready"
    identity = f"{prefix}.identity"
    install = f"{prefix}.install"
    lease = f"{prefix}.lease-create"
    start = f"{prefix}.caller-start"
    signal = f"{prefix}.caller-loss"
    expire = f"{prefix}.lease-expire"
    shutdown = f"{prefix}.shutdown"
    delete = f"{prefix}.delete"
    namespace_cleanup = f"{prefix}.namespace-cleanup"
    post_cleanup = f"{prefix}.post-cleanup-identity"
    reclaim = f"{prefix}.reclaim-verify"

    operations.append(remove_namespace(remove, phase, namespace, [prerequisite]))
    operations.append(mkdir_namespace(mkdir, phase, namespace, [remove]))
    operations.append(copy_fixture(copy, phase, namespace, [mkdir]))
    operations.append(command(build, phase, ["/usr/bin/xcodebuild", "-project", project, "-scheme", "E06SmokeApp", "-sdk", "iphonesimulator", "-derivedDataPath", derived, "CODE_SIGNING_ALLOWED=NO", "build"], [derived], mutates=True, prerequisites=[copy]))
    operations.append(simctl(create, phase, ["create", device, "com.apple.CoreSimulator.SimDeviceType.iPhone-17", "com.apple.CoreSimulator.SimRuntime.iOS-26-5"], [device], mutates=True, prerequisites=[build]))
    operations.append(simctl(boot, phase, ["boot", device], [device], mutates=True, prerequisites=[create]))
    operations.append(simctl(ready, phase, ["bootstatus", device, "-b"], [device], mutates=False, prerequisites=[boot]))
    operations.append(simctl(identity, phase, ["list", "devices", "--json"], [DEVICE_SET], mutates=False, prerequisites=[ready]))
    operations.append(simctl(install, phase, ["install", device, app], [device], mutates=True, prerequisites=[identity]))
    operations.append(effect(lease, phase, "create-supervised-caller-lease", [lease_path, f"{ROOT}/{namespace}", device], mutates=True, prerequisites=[install], parameters={"lease_id": lease_id, "lease_path": lease_path, "namespace": namespace, "device_name": device, "identity_operation_id": identity, "ttl_seconds": CALLER_LEASE_TTL_SECONDS, "heartbeat_seconds": CALLER_HEARTBEAT_SECONDS}))
    operations.append(command(start, phase, ["/bin/sleep", "30"], [], mutates=False, prerequisites=[lease], child_handle=f"caller-loss-{label}"))
    operations.append(effect(signal, phase, "signal-recorded-child", [f"recorded-child:caller-loss-{label}"], mutates=True, prerequisites=[start], parameters={"signal": "SIGTERM", "owned_process_group_required": True, "retained_owned_targets": [lease_path, f"{ROOT}/{namespace}", device]}))
    operations.append(effect(expire, phase, "observe-caller-lease-expiry", [lease_path, f"{ROOT}/{namespace}", device], mutates=True, prerequisites=[signal], parameters={"lease_id": lease_id, "lease_path": lease_path, "signal_operation_id": signal, "ttl_seconds": CALLER_LEASE_TTL_SECONDS, "heartbeat_seconds": CALLER_HEARTBEAT_SECONDS}))
    operations.append(simctl(shutdown, phase, ["shutdown", device], [device], mutates=True, prerequisites=[expire]))
    operations.append(simctl(delete, phase, ["delete", device], [device], mutates=True, prerequisites=[shutdown]))
    operations.append(remove_namespace(namespace_cleanup, phase, namespace, [delete]))
    operations.append(simctl(post_cleanup, phase, ["list", "devices", "--json"], [DEVICE_SET], mutates=False, prerequisites=[namespace_cleanup]))
    operations.append(effect(reclaim, phase, "verify-caller-loss-reclaim-order-and-deadline", [lease_path, f"{ROOT}/{namespace}", device], mutates=True, prerequisites=[post_cleanup], parameters={"lease_id": lease_id, "lease_path": lease_path, "namespace": namespace, "device_name": device, "expiry_operation_id": expire, "cleanup_operation_ids": [shutdown, delete, namespace_cleanup], "post_cleanup_identity_operation_id": post_cleanup, "cleanup_grace_seconds": 30.0, "expected_events": ["lease.heartbeat.missed", "lease.expired", "orphan.detected", "orphan.reclaimed"]}))

    retry_mkdir = f"{prefix}.retry-mkdir"
    retry_copy = f"{prefix}.retry-copy"
    retry_build = f"{prefix}.retry-build"
    retry_create = f"{prefix}.retry-create"
    retry_boot = f"{prefix}.retry-boot"
    retry_ready = f"{prefix}.retry-ready"
    retry_identity = f"{prefix}.retry-identity"
    retry_install = f"{prefix}.retry-install"
    retry_launch = f"{prefix}.retry-launch"
    retry_shutdown = f"{prefix}.retry-shutdown"
    retry_delete = f"{prefix}.retry-delete"
    retry_cleanup = f"{prefix}.retry-namespace-cleanup"
    retry_post_cleanup = f"{prefix}.retry-post-cleanup-identity"
    retry_verify = f"{prefix}.retry-verify"
    operations.append(mkdir_namespace(retry_mkdir, phase, namespace, [reclaim]))
    operations.append(copy_fixture(retry_copy, phase, namespace, [retry_mkdir]))
    operations.append(command(retry_build, phase, ["/usr/bin/xcodebuild", "-project", project, "-scheme", "E06SmokeApp", "-sdk", "iphonesimulator", "-derivedDataPath", derived, "CODE_SIGNING_ALLOWED=NO", "build"], [derived], mutates=True, prerequisites=[retry_copy]))
    operations.append(simctl(retry_create, phase, ["create", retry_device, "com.apple.CoreSimulator.SimDeviceType.iPhone-17", "com.apple.CoreSimulator.SimRuntime.iOS-26-5"], [retry_device], mutates=True, prerequisites=[retry_build]))
    operations.append(simctl(retry_boot, phase, ["boot", retry_device], [retry_device], mutates=True, prerequisites=[retry_create]))
    operations.append(simctl(retry_ready, phase, ["bootstatus", retry_device, "-b"], [retry_device], mutates=False, prerequisites=[retry_boot]))
    operations.append(simctl(retry_identity, phase, ["list", "devices", "--json"], [DEVICE_SET], mutates=False, prerequisites=[retry_ready]))
    operations.append(simctl(retry_install, phase, ["install", retry_device, app], [retry_device], mutates=True, prerequisites=[retry_identity]))
    operations.append(simctl(retry_launch, phase, ["launch", "--console-pty", retry_device, "dev.taskflow.e06.smoke", "--taskflow-namespace", namespace], [retry_device], mutates=True, prerequisites=[retry_install]))
    operations.append(simctl(retry_shutdown, phase, ["shutdown", retry_device], [retry_device], mutates=True, prerequisites=[retry_launch]))
    operations.append(simctl(retry_delete, phase, ["delete", retry_device], [retry_device], mutates=True, prerequisites=[retry_shutdown]))
    operations.append(remove_namespace(retry_cleanup, phase, namespace, [retry_delete]))
    operations.append(simctl(retry_post_cleanup, phase, ["list", "devices", "--json"], [DEVICE_SET], mutates=False, prerequisites=[retry_cleanup]))
    operations.append(effect(retry_verify, phase, "verify-clean-session-after-caller-loss", [lease_path, f"{ROOT}/{namespace}", retry_device], prerequisites=[retry_post_cleanup], parameters={"lease_id": lease_id, "lease_path": lease_path, "namespace": namespace, "retry_device_name": retry_device, "retry_identity_operation_id": retry_identity, "retry_launch_operation_id": retry_launch, "post_cleanup_identity_operation_id": retry_post_cleanup}))
    return retry_verify


def build_ledger() -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    operations.append(effect("gate.profile-mismatch", "gate", "assert-profile-mismatch-rejected-before-mutation", [], parameters={"expected_rejections": 1}))
    operations.append(effect("gate.root-absence", "gate", "assert-root-absence-before-native", [ROOT], prerequisites=["gate.profile-mismatch"]))
    controller_paths = [f"{ROOT}/controller/home", f"{ROOT}/controller/tmp", f"{ROOT}/controller/cache", f"{ROOT}/controller/config", f"{ROOT}/controller/leases", DEVICE_SET]
    operations.append(command("setup.controller-roots", "attestation", ["/bin/mkdir", "-p", *controller_paths], controller_paths, mutates=True, prerequisites=["gate.root-absence"]))
    operations.append(command("attest.macos-version", "attestation", ["/usr/bin/sw_vers", "-productVersion"], [], mutates=False, prerequisites=["setup.controller-roots"]))
    operations.append(command("attest.macos-build", "attestation", ["/usr/bin/sw_vers", "-buildVersion"], [], mutates=False, prerequisites=["attest.macos-version"]))
    operations.append(command("attest.architecture", "attestation", ["/usr/bin/uname", "-m"], [], mutates=False, prerequisites=["attest.macos-build"]))
    operations.append(command("attest.xcode", "attestation", ["/usr/bin/xcodebuild", "-version"], [], mutates=False, prerequisites=["attest.architecture"]))
    operations.append(simctl("attest.runtimes", "attestation", ["list", "runtimes", "--json"], [DEVICE_SET], mutates=True, prerequisites=["attest.xcode"]))
    operations.append(simctl("attest.device-types", "attestation", ["list", "devicetypes", "--json"], [DEVICE_SET], mutates=True, prerequisites=["attest.runtimes"]))
    initial_capacity = capacity_commands(operations, "attestation", "initial", "attest.device-types")
    operations.append(effect("attest.capacity", "attestation", "assert-capacity-thermal-window", [ROOT], prerequisites=initial_capacity, parameters={"source_operation_ids": initial_capacity, "min_free_ram_gib": 16, "min_free_disk_gib": 200, "thermal_stop": "serious"}))

    previous = "attest.capacity"
    for repetition in range(1, 31):
        namespace = NAMESPACES[(repetition - 1) % 2]
        label = f"r{repetition:02d}"
        phase = "timing.warm-workspace-ready"
        remove = f"{phase}.{label}.remove"
        create = f"{phase}.{label}.mkdir"
        verify = f"{phase}.{label}.verify"
        operations.append(remove_namespace(remove, phase, namespace, [previous]))
        operations.append(mkdir_namespace(create, phase, namespace, [remove]))
        operations.append(effect(verify, phase, "record-timing-and-assert-clean-workspace", namespace_paths(namespace), prerequisites=[create], parameters={"metric": "warm-workspace-ready", "repetition": repetition, "timed_operation_ids": [create]}))
        previous = verify
    workspace_samples = [f"timing.warm-workspace-ready.r{repetition:02d}.verify" for repetition in range(1, 31)]
    operations.append(effect("timing.warm-workspace-ready.aggregate", "timing.warm-workspace-ready", "aggregate-strict-p95", [], prerequisites=[previous], parameters={"metric": "warm-workspace-ready", "sample_result_ids": workspace_samples, "expected_sample_count": 30, "strict_p95_seconds": 3.0}))
    previous = "timing.warm-workspace-ready.aggregate"

    for mechanism in MECHANISMS:
        for repetition in range(1, 31):
            label = f"r{repetition:02d}"
            phase = "timing.simulator-ready-to-install"
            device, ready = lifecycle_prepare(operations, phase, mechanism, label, previous)
            verify = f"{phase}.{mechanism}.{label}.verify"
            prefix = f"{phase}.{mechanism}.{label}"
            if mechanism == "fresh-create-boot":
                timed = [f"{prefix}.create", f"{prefix}.boot", f"{prefix}.ready"]
            elif mechanism == "erase-reset":
                timed = [f"{prefix}.boot", f"{prefix}.ready"]
            else:
                timed = [f"{prefix}.clone", f"{prefix}.boot", f"{prefix}.ready"]
            identity = f"{prefix}.identity"
            operations.append(simctl(identity, phase, ["list", "devices", "--json"], [DEVICE_SET], mutates=False, prerequisites=[ready]))
            operations.append(effect(verify, phase, "record-timing-and-attest-simulator-identity", [device], prerequisites=[identity], parameters={"metric": "simulator-ready-to-install", "mechanism": mechanism, "repetition": repetition, "timed_operation_ids": timed, "identity_operation_id": identity, "expected_device_name": device}))
            _, _, previous = lifecycle_cleanup(operations, phase, mechanism, label, device, verify)
        simulator_samples = [f"timing.simulator-ready-to-install.{mechanism}.r{repetition:02d}.verify" for repetition in range(1, 31)]
        aggregate = f"timing.simulator-ready-to-install.{mechanism}.aggregate"
        operations.append(effect(aggregate, "timing.simulator-ready-to-install", "aggregate-strict-p95", [], prerequisites=[previous], parameters={"metric": "simulator-ready-to-install", "mechanism": mechanism, "sample_result_ids": simulator_samples, "expected_sample_count": 30, "strict_p95_seconds": 15.0}))
        previous = aggregate

    for mechanism in MECHANISMS:
        for repetition in range(1, 16):
            label = f"r{repetition:02d}"
            namespace = NAMESPACES[(repetition - 1) % 2]
            phase = "timing.mobile-lifecycle"
            remove = f"{phase}.{mechanism}.{label}.workspace-remove"
            mkdir = f"{phase}.{mechanism}.{label}.workspace-mkdir"
            copy = f"{phase}.{mechanism}.{label}.workspace-copy"
            operations.append(remove_namespace(remove, phase, namespace, [previous]))
            operations.append(mkdir_namespace(mkdir, phase, namespace, [remove]))
            operations.append(copy_fixture(copy, phase, namespace, [mkdir]))
            device, ready = lifecycle_prepare(operations, phase, mechanism, label, copy)
            identity = f"{phase}.{mechanism}.{label}.identity"
            operations.append(simctl(identity, phase, ["list", "devices", "--json"], [DEVICE_SET], mutates=False, prerequisites=[ready]))
            capacity = capacity_commands(operations, phase, f"{mechanism}.{label}", identity)
            derived = f"{ROOT}/{namespace}/DerivedData"
            project = f"{ROOT}/{namespace}/workspace/E06SmokeApp/E06SmokeApp.xcodeproj"
            build = f"{phase}.{mechanism}.{label}.build"
            install = f"{phase}.{mechanism}.{label}.install"
            launch = f"{phase}.{mechanism}.{label}.launch"
            result = f"{phase}.{mechanism}.{label}.result"
            app = f"{derived}/Build/Products/Debug-iphonesimulator/E06SmokeApp.app"
            operations.append(command(build, phase, ["/usr/bin/xcodebuild", "-project", project, "-scheme", "E06SmokeApp", "-sdk", "iphonesimulator", "-derivedDataPath", derived, "CODE_SIGNING_ALLOWED=NO", "build"], [derived], mutates=True, prerequisites=[capacity[-1]]))
            operations.append(simctl(install, phase, ["install", device, app], [device], mutates=True, prerequisites=[build]))
            operations.append(simctl(launch, phase, ["launch", "--console-pty", device, "dev.taskflow.e06.smoke", "--taskflow-namespace", namespace], [device], mutates=True, prerequisites=[install]))
            operations.append(effect(result, phase, "record-build-install-test-timings-and-structured-result", [device, f"{ROOT}/{namespace}/results"], prerequisites=[launch], parameters={"mechanism": mechanism, "repetition": repetition, "metrics": ["xcode-build", "simulator-install", "mobile-test"], "timed_operation_ids": [build, install, launch], "capacity_operation_ids": capacity, "identity_operation_id": identity, "expected_device_name": device}))
            reset_ids, device_cleanup_ids, cleanup = lifecycle_cleanup(operations, phase, mechanism, label, device, result)
            namespace_cleanup = f"{phase}.{mechanism}.{label}.namespace-cleanup"
            operations.append(remove_namespace(namespace_cleanup, phase, namespace, [cleanup]))
            post_cleanup_identity = f"{phase}.{mechanism}.{label}.post-cleanup-identity"
            operations.append(simctl(post_cleanup_identity, phase, ["list", "devices", "--json"], [DEVICE_SET], mutates=False, prerequisites=[namespace_cleanup]))
            reset_result = f"{phase}.{mechanism}.{label}.reset-cleanup-result"
            operations.append(effect(reset_result, phase, "record-reset-cleanup-timings-and-residue", [device, f"{ROOT}/{namespace}"], prerequisites=[post_cleanup_identity], parameters={"mechanism": mechanism, "repetition": repetition, "reset_operation_ids": reset_ids, "cleanup_operation_ids": [*device_cleanup_ids, namespace_cleanup], "post_cleanup_identity_operation_id": post_cleanup_identity, "expected_absent_device_name": device, "cleanup_deadline_seconds": 30}))
            previous = reset_result

    for repetition in range(1, 21):
        source = NAMESPACES[(repetition - 1) % 2]
        target = NAMESPACES[repetition % 2]
        label = f"r{repetition:02d}"
        phase = "correctness.alternating-namespace-contamination"
        source_remove = f"{phase}.{label}.source-remove"
        source_mkdir = f"{phase}.{label}.source-mkdir"
        source_copy = f"{phase}.{label}.source-copy"
        target_remove = f"{phase}.{label}.target-remove"
        target_mkdir = f"{phase}.{label}.target-mkdir"
        seed = f"{phase}.{label}.seed"
        build = f"{phase}.{label}.build"
        device = f"{PREFIX}{phase.replace('.', '-')}-{label}"
        create = f"{phase}.{label}.create"
        boot_source = f"{phase}.{label}.boot-source"
        ready_source = f"{phase}.{label}.ready-source"
        install_source = f"{phase}.{label}.install-source"
        launch_source = f"{phase}.{label}.launch-source"
        shutdown_source = f"{phase}.{label}.shutdown-source"
        erase = f"{phase}.{label}.erase"
        boot_target = f"{phase}.{label}.boot-target"
        ready_target = f"{phase}.{label}.ready-target"
        install_target = f"{phase}.{label}.install-target"
        launch_target = f"{phase}.{label}.launch-target"
        probe = f"{phase}.{label}.probe"
        shutdown_target = f"{phase}.{label}.shutdown-target"
        delete = f"{phase}.{label}.delete"
        final_remove = f"{phase}.{label}.source-final-remove"
        operations.append(remove_namespace(source_remove, phase, source, [previous]))
        operations.append(mkdir_namespace(source_mkdir, phase, source, [source_remove]))
        operations.append(copy_fixture(source_copy, phase, source, [source_mkdir]))
        operations.append(remove_namespace(target_remove, phase, target, [source_copy]))
        operations.append(mkdir_namespace(target_mkdir, phase, target, [target_remove]))
        operations.append(effect(seed, phase, "seed-synthetic-contamination-markers", namespace_paths(source), mutates=True, prerequisites=[target_mkdir], parameters={"source": source, "target": target, "source_lease_id": f"lease-{label}-{source}", "dimensions": ["workspace", "HOME", "TMPDIR", "DerivedData", "lease-identifier"], "secret_values_forbidden": True}))
        derived = f"{ROOT}/{source}/DerivedData"
        project = f"{ROOT}/{source}/workspace/E06SmokeApp/E06SmokeApp.xcodeproj"
        app = f"{derived}/Build/Products/Debug-iphonesimulator/E06SmokeApp.app"
        operations.append(command(build, phase, ["/usr/bin/xcodebuild", "-project", project, "-scheme", "E06SmokeApp", "-sdk", "iphonesimulator", "-derivedDataPath", derived, "CODE_SIGNING_ALLOWED=NO", "build"], [derived], mutates=True, prerequisites=[seed]))
        operations.append(simctl(create, phase, ["create", device, "com.apple.CoreSimulator.SimDeviceType.iPhone-17", "com.apple.CoreSimulator.SimRuntime.iOS-26-5"], [device], mutates=True, prerequisites=[build]))
        operations.append(simctl(boot_source, phase, ["boot", device], [device], mutates=True, prerequisites=[create]))
        operations.append(simctl(ready_source, phase, ["bootstatus", device, "-b"], [device], mutates=False, prerequisites=[boot_source]))
        operations.append(simctl(install_source, phase, ["install", device, app], [device], mutates=True, prerequisites=[ready_source]))
        operations.append(simctl(launch_source, phase, ["launch", "--console-pty", device, "dev.taskflow.e06.smoke", "--taskflow-namespace", source], [device], mutates=True, prerequisites=[install_source]))
        operations.append(simctl(shutdown_source, phase, ["shutdown", device], [device], mutates=True, prerequisites=[launch_source]))
        operations.append(simctl(erase, phase, ["erase", device], [device], mutates=True, prerequisites=[shutdown_source]))
        operations.append(simctl(boot_target, phase, ["boot", device], [device], mutates=True, prerequisites=[erase]))
        operations.append(simctl(ready_target, phase, ["bootstatus", device, "-b"], [device], mutates=False, prerequisites=[boot_target]))
        operations.append(simctl(install_target, phase, ["install", device, app], [device], mutates=True, prerequisites=[ready_target]))
        operations.append(simctl(launch_target, phase, ["launch", "--console-pty", device, "dev.taskflow.e06.smoke", "--taskflow-namespace", target], [device], mutates=True, prerequisites=[install_target]))
        operations.append(effect(probe, phase, "assert-zero-cross-namespace-observations", [*namespace_paths(source), *namespace_paths(target), device], mutates=True, prerequisites=[launch_target], parameters={"source": source, "target": target, "repetition": repetition, "source_launch_operation_id": launch_source, "target_launch_operation_id": launch_target, "source_lease_id": f"lease-{label}-{source}", "target_lease_id": f"lease-{label}-{target}", "dimensions": ["workspace", "HOME", "TMPDIR", "DerivedData", "installed-app-data", "preferences", "keychain-canary-name", "lease-identifier"]}))
        operations.append(simctl(shutdown_target, phase, ["shutdown", device], [device], mutates=True, prerequisites=[probe]))
        operations.append(simctl(delete, phase, ["delete", device], [device], mutates=True, prerequisites=[shutdown_target]))
        operations.append(remove_namespace(final_remove, phase, source, [delete]))
        previous = final_remove

    for repetition in range(1, 11):
        label = f"r{repetition:02d}"
        phase = "correctness.two-namespace-isolation"
        capacity = capacity_commands(operations, phase, label, previous)
        previous = concurrent_native_probe(operations, phase, label, list(NAMESPACES[:2]), capacity[-1], "assert-zero-path-device-lease-or-identity-collision", {"repetition": repetition, "concurrency": 2, "capacity_operation_ids": capacity})

    for level in (1, 2, 3, 4):
        for repetition in range(1, 6):
            namespaces = list(NAMESPACES[:level])
            label = f"c{level}.r{repetition:02d}"
            phase = "correctness.bounded-maximum-safe-concurrency"
            capacity = capacity_commands(operations, phase, label, previous)
            previous = concurrent_native_probe(operations, phase, label, namespaces, capacity[-1], "record-capacity-and-assert-all-hard-gates", {"concurrency": level, "repetition": repetition, "stop_on_any_gate": True, "min_free_ram_gib": 16, "min_free_disk_gib": 200, "thermal_stop": "serious", "capacity_operation_ids": capacity})

    for repetition in range(1, 6):
        label = f"r{repetition:02d}"
        phase = "fault.simulator-loss"
        namespace = NAMESPACES[(repetition - 1) % 2]
        remove = f"{phase}.{label}.workspace-remove"
        mkdir = f"{phase}.{label}.workspace-mkdir"
        copy = f"{phase}.{label}.workspace-copy"
        build = f"{phase}.{label}.build"
        operations.append(remove_namespace(remove, phase, namespace, [previous]))
        operations.append(mkdir_namespace(mkdir, phase, namespace, [remove]))
        operations.append(copy_fixture(copy, phase, namespace, [mkdir]))
        derived = f"{ROOT}/{namespace}/DerivedData"
        project = f"{ROOT}/{namespace}/workspace/E06SmokeApp/E06SmokeApp.xcodeproj"
        app = f"{derived}/Build/Products/Debug-iphonesimulator/E06SmokeApp.app"
        operations.append(command(build, phase, ["/usr/bin/xcodebuild", "-project", project, "-scheme", "E06SmokeApp", "-sdk", "iphonesimulator", "-derivedDataPath", derived, "CODE_SIGNING_ALLOWED=NO", "build"], [derived], mutates=True, prerequisites=[copy]))
        device, ready = lifecycle_prepare(operations, phase, "fresh-create-boot", label, build)
        install = f"{phase}.{label}.install"
        operations.append(simctl(install, phase, ["install", device, app], [device], mutates=True, prerequisites=[ready]))
        loss = f"{phase}.{label}.inject"
        rejected_use = f"{phase}.{label}.lost-session-use"
        delete_lost = f"{phase}.{label}.delete-lost"
        retry_device = f"{PREFIX}{phase}-retry-{label}"
        retry_create = f"{phase}.{label}.retry-create"
        retry_boot = f"{phase}.{label}.retry-boot"
        retry_ready = f"{phase}.{label}.retry-ready"
        retry_identity = f"{phase}.{label}.retry-identity"
        retry_install = f"{phase}.{label}.retry-install"
        retry_launch = f"{phase}.{label}.retry-launch"
        retry_shutdown = f"{phase}.{label}.retry-shutdown"
        retry_delete = f"{phase}.{label}.retry-delete"
        post_cleanup = f"{phase}.{label}.post-cleanup-identity"
        detect = f"{phase}.{label}.detect"
        operations.append(simctl(loss, phase, ["shutdown", device], [device], mutates=True, prerequisites=[install]))
        operations.append(command(rejected_use, phase, ["/usr/bin/xcrun", "simctl", "--set", DEVICE_SET, "launch", "--console-pty", device, "dev.taskflow.e06.smoke", "--taskflow-namespace", namespace], [device], mutates=True, prerequisites=[loss], expected_result="failure"))
        operations.append(simctl(delete_lost, phase, ["delete", device], [device], mutates=True, prerequisites=[rejected_use]))
        operations.append(simctl(retry_create, phase, ["create", retry_device, "com.apple.CoreSimulator.SimDeviceType.iPhone-17", "com.apple.CoreSimulator.SimRuntime.iOS-26-5"], [retry_device], mutates=True, prerequisites=[delete_lost]))
        operations.append(simctl(retry_boot, phase, ["boot", retry_device], [retry_device], mutates=True, prerequisites=[retry_create]))
        operations.append(simctl(retry_ready, phase, ["bootstatus", retry_device, "-b"], [retry_device], mutates=False, prerequisites=[retry_boot]))
        operations.append(simctl(retry_identity, phase, ["list", "devices", "--json"], [DEVICE_SET], mutates=False, prerequisites=[retry_ready]))
        operations.append(simctl(retry_install, phase, ["install", retry_device, app], [retry_device], mutates=True, prerequisites=[retry_identity]))
        operations.append(simctl(retry_launch, phase, ["launch", "--console-pty", retry_device, "dev.taskflow.e06.smoke", "--taskflow-namespace", namespace], [retry_device], mutates=True, prerequisites=[retry_install]))
        operations.append(simctl(retry_shutdown, phase, ["shutdown", retry_device], [retry_device], mutates=True, prerequisites=[retry_launch]))
        operations.append(simctl(retry_delete, phase, ["delete", retry_device], [retry_device], mutates=True, prerequisites=[retry_shutdown]))
        operations.append(simctl(post_cleanup, phase, ["list", "devices", "--json"], [DEVICE_SET], mutates=False, prerequisites=[retry_delete]))
        operations.append(effect(detect, phase, "assert-lost-session-rejected-and-clean-retry-possible", [device, retry_device], prerequisites=[post_cleanup], parameters={"repetition": repetition, "lost_use_operation_id": rejected_use, "retry_identity_operation_id": retry_identity, "retry_launch_operation_id": retry_launch, "post_cleanup_identity_operation_id": post_cleanup, "lost_device_name": device, "retry_device_name": retry_device, "expected_namespace": namespace}))
        previous = detect

    for fault in ("cancellation",):
        for repetition in range(1, 6):
            label = f"r{repetition:02d}"
            phase = f"fault.{fault}"
            namespace = NAMESPACES[(repetition - 1) % 2]
            handle = f"{fault}-{label}-child"
            start = f"{phase}.{label}.start-child"
            signal = f"{phase}.{label}.signal-child"
            verify = f"{phase}.{label}.verify"
            derived = f"{ROOT}/{namespace}/DerivedData"
            project = f"{ROOT}/{namespace}/workspace/E06SmokeApp/E06SmokeApp.xcodeproj"
            prepare_remove = f"{phase}.{label}.prepare-remove"
            prepare_mkdir = f"{phase}.{label}.prepare-mkdir"
            prepare_copy = f"{phase}.{label}.prepare-copy"
            cleanup = f"{phase}.{label}.cleanup"
            operations.append(remove_namespace(prepare_remove, phase, namespace, [previous]))
            operations.append(mkdir_namespace(prepare_mkdir, phase, namespace, [prepare_remove]))
            operations.append(copy_fixture(prepare_copy, phase, namespace, [prepare_mkdir]))
            operations.append(command(start, phase, ["/usr/bin/xcodebuild", "-project", project, "-scheme", "E06SmokeApp", "-sdk", "iphonesimulator", "-derivedDataPath", derived, "CODE_SIGNING_ALLOWED=NO", "build"], [derived], mutates=True, prerequisites=[prepare_copy], child_handle=handle))
            operations.append(effect(signal, phase, "signal-recorded-child", [f"recorded-child:{handle}"], mutates=True, prerequisites=[start], parameters={"signal": "SIGTERM", "owned_process_group_required": True, "retained_owned_targets": [f"{ROOT}/{namespace}"]}))
            operations.append(remove_namespace(cleanup, phase, namespace, [signal]))
            operations.append(effect(verify, phase, "assert-cleanup-deadline-or-exact-orphan", [f"{ROOT}/{namespace}"], prerequisites=[cleanup], parameters={"fault": fault, "repetition": repetition, "signal_operation_id": signal, "cleanup_operation_id": cleanup, "cleanup_deadline_seconds": 30}))
            previous = verify

    for repetition in range(1, 6):
        previous = caller_loss_probe(operations, f"r{repetition:02d}", NAMESPACES[(repetition - 1) % 2], previous)

    operations.append(effect("limitations.record", "limitations", "record-not-applicable-and-unmeasured-limitations", [], prerequisites=[previous], parameters={"not_applicable": ["cold-vm-boot", "vm-loss", "immutable-base-integrity", "image-import-update"], "unmeasured": ["network-image-distribution", "native-xcode-sdk-runtime-update-and-rollback"]}))
    operations.append(simctl("cleanup.list-owned-set", "cleanup", ["list", "devices", "--json"], [DEVICE_SET], mutates=False, prerequisites=["limitations.record"]))
    operations.append(effect("cleanup.assert-no-owned-devices-or-record-orphans", "cleanup", "assert-no-owned-devices-or-record-exact-orphans", [DEVICE_SET], prerequisites=["cleanup.list-owned-set"]))
    operations.append(command("cleanup.remove-owned-root", "cleanup", ["/bin/rm", "-rf", "--", ROOT], [ROOT], mutates=True, prerequisites=["cleanup.assert-no-owned-devices-or-record-orphans"]))
    operations.append(effect("cleanup.verify-absence", "cleanup", "assert-owned-root-absent-and-no-unrecorded-orphans", [ROOT], prerequisites=["cleanup.remove-owned-root"]))
    operations.append(effect("evidence.finalize", "evidence", "finalize-sanitized-evidence-and-checksums", [EVIDENCE], mutates=True, prerequisites=["cleanup.verify-absence"], parameters={"forbidden": ["device-udid", "host-serial", "host-uuid", "user-path", "secret", "credential"]}))

    return {
        "format_version": "taskflow-e06-expanded-ledger/v1-experimental",
        "manifest_id": "taskflow-e06-native-a",
        "status": "repository-generated-not-approved-not-executed",
        "generator": "scripts/schedule.py",
        "operations": operations,
        "operation_count": len(operations),
        "execution_count": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--emit", action="store_true")
    parser.add_argument("--write-ledger", action="store_true")
    args = parser.parse_args()
    if args.emit and args.write_ledger:
        parser.error("choose one output mode")
    encoded = json.dumps(build_ledger(), separators=(",", ":"), sort_keys=False) + "\n"
    if args.emit:
        print(encoded, end="")
    elif args.write_ledger:
        (EXECUTION / "expanded-ledger.json").write_text(encoded, encoding="utf-8")
        print(f"wrote {EXECUTION / 'expanded-ledger.json'}")
    else:
        print(build_ledger()["operation_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
