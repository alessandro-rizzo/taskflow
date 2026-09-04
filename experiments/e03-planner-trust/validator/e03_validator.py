#!/usr/bin/env python3
"""Independent fail-closed E03 authorization validator (stdlib only)."""

import argparse
import json
import posixpath
import sys
from pathlib import Path


class Rejection(ValueError):
    def __init__(self, path, reason):
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise Rejection("$", f"duplicate member {key!r}")
        out[key] = value
    return out


def _depth(value):
    if isinstance(value, dict):
        return 1 + max((_depth(v) for v in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_depth(v) for v in value), default=0)
    return 1


def _exact(obj, allowed, path):
    if not isinstance(obj, dict):
        raise Rejection(path, "must be an object")
    extra = sorted(set(obj) - set(allowed))
    if extra:
        raise Rejection(f"{path}.{extra[0]}", "unknown field")


def _objects(value, path, maximum):
    if value is None:
        return []
    if not isinstance(value, list):
        raise Rejection(path, "must be an array")
    if len(value) > maximum:
        raise Rejection(path, f"count exceeds {maximum}")
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise Rejection(f"{path}[{index}]", "must be an object")
    return value


def _sid(item, collection, index):
    value = item.get("id")
    if not isinstance(value, str) or not value:
        raise Rejection(f"$.{collection}[{index}].id", "non-empty string required")
    return value


def _safe_path(value, path):
    if not isinstance(value, str):
        raise Rejection(path, "must be a string")
    if "\x00" in value or posixpath.isabs(value) or ".." in value.split("/"):
        raise Rejection(path, "unsafe path")


def _load(raw, maximum):
    if len(raw) > maximum:
        raise Rejection("$", f"document exceeds {maximum} bytes")
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise Rejection("$", "invalid UTF-8") from exc
    decoder = json.JSONDecoder(object_pairs_hook=_pairs)
    try:
        value, end = decoder.raw_decode(text)
    except Rejection:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise Rejection("$", "invalid JSON") from exc
    if text[end:].strip():
        raise Rejection("$", "trailing data")
    return value


def validate(raw, policy):
    maximums = policy["maximums"]
    plan = _load(raw, maximums["document_bytes"])
    if _depth(plan) > maximums["json_depth"]:
        raise Rejection("$", f"JSON depth exceeds {maximums['json_depth']}")
    root_fields = {"document_kind", "format_version", "fixture_id", "fixture_version", "status",
                   "nodes", "artifacts", "services", "secrets", "effects"}
    _exact(plan, root_fields, "$")
    if plan.get("document_kind") != policy["accepted_document_kind"]:
        raise Rejection("$.document_kind", "unsupported document kind")
    if plan.get("format_version") not in policy["accepted_format_versions"]:
        raise Rejection("$.format_version", "missing or unsupported version")
    if plan.get("fixture_id") not in policy["accepted_fixture_ids"]:
        raise Rejection("$.fixture_id", "fixture is not authorized")
    for field in ("fixture_version", "status"):
        if not isinstance(plan.get(field), str):
            raise Rejection(f"$.{field}", "string required")

    nodes = _objects(plan.get("nodes"), "$.nodes", maximums["nodes"])
    artifacts = _objects(plan.get("artifacts"), "$.artifacts", maximums["artifacts"])
    # Inspect authority-bearing entries before applying the zero-count policy so
    # denials identify the exact untrusted field that requested authority.
    services = _objects(plan.get("services"), "$.services", max(1024, maximums["services"]))
    secrets = _objects(plan.get("secrets"), "$.secrets", max(1024, maximums["secrets"]))
    effects = _objects(plan.get("effects"), "$.effects", max(1024, maximums["effects"]))
    node_ids, artifact_ids, service_ids = set(), set(), set()
    total_cpu = total_memory = 0
    for i, item in enumerate(artifacts):
        _exact(item, {"id", "type", "optional"}, f"$.artifacts[{i}]")
        aid = _sid(item, "artifacts", i)
        if aid in artifact_ids:
            raise Rejection(f"$.artifacts[id={aid}].id", "duplicate id")
        artifact_ids.add(aid)
    for i, item in enumerate(nodes):
        nid = _sid(item, "nodes", i)
        p = f"$.nodes[id={nid}]"
        _exact(item, {"id", "needs", "consumes", "produces", "planning_condition",
                      "outcome_condition", "resources", "execution_profile", "cache_policy"}, p)
        if nid in node_ids:
            raise Rejection(p + ".id", "duplicate id")
        node_ids.add(nid)
        for collection in ("needs", "consumes", "produces"):
            values = item.get(collection, [])
            if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                raise Rejection(p + "." + collection, "string array required")
        condition = item.get("planning_condition")
        if not isinstance(condition, dict):
            raise Rejection(p + ".planning_condition", "object required")
        _exact(condition, {"type", "patterns", "exclude_patterns"}, p + ".planning_condition")
        for field in ("patterns", "exclude_patterns"):
            for j, value in enumerate(condition.get(field, [])):
                _safe_path(value, f"{p}.planning_condition.{field}[{j}]")
        resources = item.get("resources")
        _exact(resources, {"cpu_millicores", "memory_mib"}, p + ".resources")
        cpu, memory = resources.get("cpu_millicores"), resources.get("memory_mib")
        if not isinstance(cpu, int) or isinstance(cpu, bool) or cpu < 0 or cpu > maximums["cpu_millicores_per_node"]:
            raise Rejection(p + ".resources.cpu_millicores", "resource exceeds policy")
        if not isinstance(memory, int) or isinstance(memory, bool) or memory < 0 or memory > maximums["memory_mib_per_node"]:
            raise Rejection(p + ".resources.memory_mib", "resource exceeds policy")
        total_cpu += cpu
        total_memory += memory
        execution = item.get("execution_profile")
        _exact(execution, {"os", "toolchain", "profile_id", "target_role"}, p + ".execution_profile")
        if execution.get("os") not in policy["allowed_execution"]["os"]:
            raise Rejection(p + ".execution_profile.os", "target OS is not authorized")
        if execution.get("toolchain") not in policy["allowed_execution"]["toolchains"]:
            raise Rejection(p + ".execution_profile.toolchain", "toolchain is not authorized")
        if "profile_id" in execution and execution["profile_id"] not in policy["allowed_execution"]["profile_ids"]:
            raise Rejection(p + ".execution_profile.profile_id", "profile is not authorized")
        if "target_role" in execution and execution["target_role"] not in policy["allowed_execution"]["target_roles"]:
            raise Rejection(p + ".execution_profile.target_role", "target is not authorized")
    if total_cpu > maximums["cpu_millicores_total"] or total_memory > maximums["memory_mib_total"]:
        raise Rejection("$.nodes", "aggregate resources exceed policy")
    for i, item in enumerate(services):
        _exact(item, {"id", "route"}, f"$.services[{i}]")
        sid = _sid(item, "services", i)
        if sid in service_ids:
            raise Rejection(f"$.services[id={sid}].id", "duplicate id")
        service_ids.add(sid)
    for i, item in enumerate(secrets):
        _exact(item, {"id", "capability"}, f"$.secrets[{i}]")
        sid = _sid(item, "secrets", i)
        if item.get("capability") not in policy["allowed_secret_capabilities"]:
            raise Rejection(f"$.secrets[id={sid}].capability", "secret capability is not authorized")
    for i, item in enumerate(effects):
        _exact(item, {"id", "kind", "target"}, f"$.effects[{i}]")
        eid = _sid(item, "effects", i)
        target = item.get("target")
        if target not in service_ids:
            raise Rejection(f"$.effects[id={eid}].target", "target does not reference a declared service")
        if item.get("kind") not in policy["allowed_effect_kinds"]:
            raise Rejection(f"$.effects[id={eid}].kind", "effect is not authorized")
    for item in services:
        sid = item["id"]
        if item.get("route") not in policy["allowed_network_routes"]:
            raise Rejection(f"$.services[id={sid}].route", "network route is not authorized")
    for item in nodes:
        nid = item["id"]
        for need in item.get("needs", []):
            if need not in node_ids:
                raise Rejection(f"$.nodes[id={nid}].needs", "unknown node reference")
        for field in ("consumes", "produces"):
            for aid in item.get(field, []):
                if aid not in artifact_ids:
                    raise Rejection(f"$.nodes[id={nid}].{field}", "unknown artifact reference")
    return {"accepted": True, "fixture_id": plan["fixture_id"], "nodes": len(nodes)}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
    try:
        result = validate(Path(args.plan).read_bytes(), policy)
    except Rejection as exc:
        result = {"accepted": False, "path": exc.path, "reason": exc.reason}
        print(json.dumps(result, sort_keys=True) if args.json else str(exc))
        return 1
    print(json.dumps(result, sort_keys=True) if args.json else "accepted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
