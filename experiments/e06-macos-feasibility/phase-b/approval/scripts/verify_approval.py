#!/usr/bin/env python3
"""Verify the non-executing E06 native-host approval proposal."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


APPROVAL = Path(__file__).resolve().parents[1]
PHASE_B = APPROVAL.parent
PHASE_A = PHASE_B.parent
REPOSITORY = PHASE_B.parents[2]
IMPLEMENTATION_COMMIT = "6decbbd1323fd9a69137129db234028d80b1151d"
IMPLEMENTATION_TREE = "e80c5fb834523430890acbb91b2462fa082fae32"


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"cannot read {path}: {error}") from error
    require(isinstance(value, dict), f"{path}: expected object")
    return value


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def git_output(*arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    require(completed.returncode == 0, completed.stderr.decode("utf-8", "replace").strip())
    return completed.stdout


def git_bytes(relative: str) -> bytes:
    return git_output("show", f"{IMPLEMENTATION_COMMIT}:{relative}")


def verify_immutable_implementation(packet: dict[str, Any]) -> None:
    implementation = packet["implementation"]
    require(implementation["commit"] == IMPLEMENTATION_COMMIT, "implementation commit drifted")
    require(implementation["tree"] == IMPLEMENTATION_TREE, "implementation tree drifted")
    require(git_output("rev-parse", "HEAD").decode().strip() == IMPLEMENTATION_COMMIT, "HEAD is not the reviewed implementation commit")
    require(git_output("rev-parse", f"{IMPLEMENTATION_COMMIT}^{{tree}}").decode().strip() == IMPLEMENTATION_TREE, "implementation tree does not match commit")

    frozen_path = "experiments/e06-macos-feasibility/phase-b/frozen-artifacts.json"
    frozen = json.loads(git_bytes(frozen_path))
    for item in frozen["artifacts"]:
        relative = f"experiments/e06-macos-feasibility/phase-b/{item['path']}"
        committed = git_bytes(relative)
        require(digest_bytes(committed) == item["sha256"], f"committed frozen digest drift: {relative}")
        require((REPOSITORY / relative).read_bytes() == committed, f"live frozen implementation drift: {relative}")
    for relative in (frozen_path, "experiments/e06-macos-feasibility/phase-b/protocol.sha256"):
        require((REPOSITORY / relative).read_bytes() == git_bytes(relative), f"live frozen implementation drift: {relative}")

    protocol_line = git_bytes("experiments/e06-macos-feasibility/phase-b/protocol.sha256").decode().strip()
    require(protocol_line.split()[0] == implementation["phase_b_protocol_digest"], "Phase-B protocol digest binding drifted")
    schema_path = PHASE_A / "execution-manifest.schema.json"
    command_path = PHASE_B / "command-ledger.json"
    require(digest(schema_path) == implementation["execution_manifest_schema_sha256"], "schema digest drifted")
    require(digest(command_path) == implementation["command_ledger_sha256"], "command ledger digest drifted")
    require(digest(APPROVAL / "cleanup-ledger.json") == implementation["cleanup_ledger_sha256"], "cleanup ledger digest drifted")
    require(digest(APPROVAL / "host-attestation.json") == implementation["safe_host_attestation_sha256"], "host attestation digest drifted")


def resolve_ref(schema_root: dict[str, Any], reference: str) -> dict[str, Any]:
    require(reference.startswith("#/"), f"unsupported schema reference: {reference}")
    value: Any = schema_root
    for part in reference[2:].split("/"):
        value = value[part]
    require(isinstance(value, dict), f"schema reference is not an object: {reference}")
    return value


def check_type(instance: Any, expected: Any) -> bool:
    names = expected if isinstance(expected, list) else [expected]
    matches = {
        "object": lambda value: isinstance(value, dict),
        "array": lambda value: isinstance(value, list),
        "string": lambda value: isinstance(value, str),
        "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": lambda value: isinstance(value, bool),
        "null": lambda value: value is None,
    }
    return any(name in matches and matches[name](instance) for name in names)


def validate_schema(instance: Any, schema: dict[str, Any], root: dict[str, Any], location: str = "$") -> None:
    if "$ref" in schema:
        validate_schema(instance, resolve_ref(root, schema["$ref"]), root, location)
    for subschema in schema.get("allOf", []):
        validate_schema(instance, subschema, root, location)
    if "not" in schema:
        try:
            validate_schema(instance, schema["not"], root, location)
        except VerificationError:
            pass
        else:
            raise VerificationError(f"{location}: forbidden by not")
    if "const" in schema:
        require(instance == schema["const"], f"{location}: const mismatch")
    if "enum" in schema:
        require(instance in schema["enum"], f"{location}: enum mismatch")
    if "type" in schema:
        require(check_type(instance, schema["type"]), f"{location}: type mismatch")
    if isinstance(instance, dict):
        required = schema.get("required", [])
        require(all(key in instance for key in required), f"{location}: missing required property")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            require(set(instance) <= set(properties), f"{location}: additional property")
        for key, value in instance.items():
            if key in properties:
                validate_schema(value, properties[key], root, f"{location}.{key}")
    if isinstance(instance, list):
        if "minItems" in schema:
            require(len(instance) >= schema["minItems"], f"{location}: too few items")
        if "maxItems" in schema:
            require(len(instance) <= schema["maxItems"], f"{location}: too many items")
        if schema.get("uniqueItems"):
            canonical = [json.dumps(item, sort_keys=True) for item in instance]
            require(len(canonical) == len(set(canonical)), f"{location}: duplicate items")
        if "items" in schema:
            for index, value in enumerate(instance):
                validate_schema(value, schema["items"], root, f"{location}[{index}]")
        if "contains" in schema:
            found = False
            for value in instance:
                try:
                    validate_schema(value, schema["contains"], root, location)
                except VerificationError:
                    continue
                found = True
                break
            require(found, f"{location}: contains constraint failed")
    if isinstance(instance, str):
        if "minLength" in schema:
            require(len(instance) >= schema["minLength"], f"{location}: string too short")
        if "pattern" in schema:
            require(re.search(schema["pattern"], instance) is not None, f"{location}: pattern mismatch")
        if schema.get("format") == "date-time":
            try:
                datetime.fromisoformat(instance.replace("Z", "+00:00"))
            except ValueError as error:
                raise VerificationError(f"{location}: invalid date-time") from error
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "exclusiveMinimum" in schema:
            require(instance > schema["exclusiveMinimum"], f"{location}: exclusive minimum failed")
        if "minimum" in schema:
            require(instance >= schema["minimum"], f"{location}: minimum failed")
        if "maximum" in schema:
            require(instance <= schema["maximum"], f"{location}: maximum failed")


def build_schema_specimen(packet: dict[str, Any]) -> dict[str, Any]:
    manifest = copy.deepcopy(packet["manifest"])
    command_reference = manifest.pop("commands_from")
    cleanup_reference = manifest.pop("cleanup_from")
    command_ledger = load(REPOSITORY / command_reference["path"])
    cleanup_ledger = load(REPOSITORY / cleanup_reference["path"])
    require(digest(REPOSITORY / command_reference["path"]) == command_reference["sha256"], "manifest command reference drifted")
    require(digest(REPOSITORY / cleanup_reference["path"]) == cleanup_reference["sha256"], "manifest cleanup reference drifted")
    require(len(command_ledger["commands"]) == command_reference["count"], "command count drifted")
    require(len(cleanup_ledger["commands"]) == cleanup_reference["additional_command_count"], "cleanup command count drifted")
    manifest["commands"] = command_ledger["commands"] + cleanup_ledger["commands"]
    manifest["approval"]["approved_by"] = "__SCHEMA_CHECK_ONLY_NOT_AN_APPROVAL__"
    manifest["approval"]["approved_at"] = "2000-01-01T00:00:00Z"
    manifest["host"]["exclusive_window_start"] = "2000-01-01T00:00:00Z"
    manifest["host"]["exclusive_window_end"] = "2000-01-01T00:01:00Z"
    return manifest


def verify_unresolved(packet: dict[str, Any]) -> None:
    manifest = packet["manifest"]
    require(packet["status"] == "blocked-not-ready-for-execution", "packet must remain blocked")
    require(manifest["approval"]["approved_by"] is None, "approval identity must remain unresolved")
    require(manifest["approval"]["approved_at"] is None, "approval time must remain unresolved")
    require(manifest["host"]["exclusive_window_start"] is None, "window start must remain unresolved")
    require(manifest["host"]["exclusive_window_end"] is None, "window end must remain unresolved")
    require(packet["execution_count"] == 0, "execution evidence exists in proposal")
    require("an execution-capable runner and exact expanded measurement/fault sample schedule" in packet["unresolved"], "execution runner blocker missing")
    attestation = load(APPROVAL / "host-attestation.json")
    require(attestation["execution_attestation_complete"] is False and attestation["execution_count"] == 0, "host attestation must remain incomplete")
    require(any("CoreSimulator" in item for item in attestation["not_refreshed"]), "CoreSimulator blocker missing")


def verify() -> None:
    packet = load(APPROVAL / "approval-packet.json")
    verify_immutable_implementation(packet)
    verify_unresolved(packet)
    schema = load(PHASE_A / "execution-manifest.schema.json")
    validate_schema(build_schema_specimen(packet), schema, schema)


def main() -> int:
    try:
        verify()
    except (KeyError, OSError, json.JSONDecodeError, VerificationError) as error:
        print(f"verify-e06-approval-proposal: {error}")
        return 1
    print("verify-e06-approval-proposal: immutable bindings and all resolved manifest fields valid; execution remains blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
