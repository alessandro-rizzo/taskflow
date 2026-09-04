#!/usr/bin/env python3
"""Execute the frozen E03 independent-validator matrix without retaining payloads."""

import copy
import importlib.util
import json
from pathlib import Path
import sys


SCRIPT = Path(__file__).resolve()
EXPERIMENT = SCRIPT.parents[1]
ROOT = SCRIPT.parents[3]
SPEC = importlib.util.spec_from_file_location("e03_validator", EXPERIMENT / "validator/e03_validator.py")
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
POLICY = json.loads((EXPERIMENT / "policies/untrusted-plan-policy.json").read_text())
GOOD = json.loads((ROOT / "experiments/e02-plan-ir/evidence/raw/plans/w1.json").read_text())


def encoded(value):
    return json.dumps(value, separators=(",", ":")).encode()


def mutation(case_id):
    doc = copy.deepcopy(GOOD)
    policy = copy.deepcopy(POLICY)
    if case_id == "parser-duplicate-member":
        return b'{"document_kind":"plan","document_kind":"plan"}', policy
    if case_id == "parser-trailing-document":
        return encoded(doc) + b" {}", policy
    if case_id == "parser-invalid-utf8":
        return b"\xff", policy
    if case_id == "parser-missing-version":
        del doc["format_version"]
    elif case_id == "parser-unknown-version":
        doc["format_version"] = "v999"
    elif case_id == "parser-unknown-field":
        doc["planner_approval"] = True
    elif case_id == "parser-document-size":
        return b" " * (POLICY["maximums"]["document_bytes"] + 1), policy
    elif case_id == "parser-depth":
        return b'{"document_kind":"plan","x":' + b"[" * 40 + b"0" + b"]" * 40 + b"}", policy
    elif case_id == "parser-node-count":
        doc["nodes"] = [copy.deepcopy(GOOD["nodes"][0]) for _ in range(POLICY["maximums"]["nodes"] + 1)]
        for index, node in enumerate(doc["nodes"]):
            node["id"] = f"node-{index}"
            node["needs"] = []
    elif case_id == "policy-unauthorized-target":
        doc["nodes"][1]["execution_profile"]["os"] = "linux"
    elif case_id == "policy-unauthorized-network":
        doc["services"] = [{"id": "internal", "route": "tcp://127.0.0.1"}]
    elif case_id == "policy-unauthorized-secret":
        doc["secrets"] = [{"id": "signing-key", "capability": "read"}]
    elif case_id == "policy-unauthorized-effect":
        doc["services"] = [{"id": "release", "route": "none"}]
        doc["effects"] = [{"id": "publish", "kind": "publish", "target": "release"}]
    elif case_id == "policy-dangling-effect-target":
        doc["effects"] = [{"id": "publish", "kind": "publish", "target": "missing"}]
    elif case_id == "policy-unsafe-absolute-path":
        doc["nodes"][2]["planning_condition"]["patterns"][0] = "/private/e03"
    elif case_id == "policy-unsafe-parent-path":
        doc["nodes"][2]["planning_condition"]["patterns"][0] = "../e03"
    elif case_id == "policy-resource-per-node":
        doc["nodes"][1]["resources"]["memory_mib"] = 4097
    elif case_id == "policy-resource-total":
        for node in doc["nodes"]:
            node["resources"]["cpu_millicores"] = 2000
    elif case_id == "policy-self-authorization":
        doc["policy"] = {"approved": True}
    else:
        raise RuntimeError("unknown frozen case " + case_id)
    return encoded(doc), policy


def main(argv):
    if len(argv) != 2:
        raise SystemExit("usage: run_validator_matrix.py OUTPUT")
    matrix = json.loads((EXPERIMENT / "attacks.json").read_text())
    results = []
    for case in matrix["extended_validator_cases"]:
        raw, policy = mutation(case["id"])
        try:
            VALIDATOR.validate(raw, policy)
            observed = {"outcome": "accepted", "path": None, "reason": "unexpected acceptance"}
        except VALIDATOR.Rejection as exc:
            observed = {"outcome": case["expected_outcome"], "path": exc.path, "reason": exc.reason}
        results.append({
            "case_id": case["id"],
            "expected_outcome": case["expected_outcome"],
            "expected_path": case["expected_path"],
            "observed_outcome": observed["outcome"],
            "observed_path": observed["path"],
            "passed": observed["outcome"] == case["expected_outcome"] and observed["path"] == case["expected_path"],
            "reason": observed["reason"],
        })
    positive = VALIDATOR.validate(encoded(GOOD), POLICY)
    output = {
        "format_version": "taskflow-e03-validator-matrix/v1",
        "known_good_accepted": bool(positive["accepted"]),
        "case_count": len(results),
        "all_passed": all(item["passed"] for item in results),
        "results": results,
    }
    Path(argv[1]).parent.mkdir(parents=True, exist_ok=True)
    Path(argv[1]).write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    if not output["known_good_accepted"] or not output["all_passed"]:
        return 1
    print(f"E03 validator matrix: PASS ({len(results)} negative cases, known-good accepted)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
