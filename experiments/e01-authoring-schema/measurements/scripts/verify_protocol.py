#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path


MEASUREMENTS = Path(__file__).resolve().parents[1]
PROTOCOL = MEASUREMENTS / "protocol.json"
HASH_FILE = MEASUREMENTS / "protocol.sha256"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"verify-protocol: {message}")


def main() -> None:
    raw = PROTOCOL.read_bytes()
    protocol = json.loads(raw)
    require(protocol["schema_version"] == "taskflow-e01-measurement-protocol/v1", "wrong schema version")
    require(protocol["candidate_source_revision"] == "ca87b81869b3b22630a3772da481d5088b0816ef", "source binding drifted")
    require(protocol["phase_a_contract_commit"] == "1c88ddb", "Phase A binding drifted")
    require(protocol["candidate_order"]["primary"] == ["C", "D", "B", "A"], "primary order drifted")
    require(protocol["candidate_order"]["reverse_if_near_budget"] == ["A", "B", "D", "C"], "reverse order drifted")
    metrics = {item["id"]: item for item in protocol["metrics"]}
    require(metrics["warm-discovery"]["samples"] == 30, "warm discovery must retain 30 samples")
    for metric_id in ("cold-discovery", "cold-driver-build-or-typecheck", "warm-driver-build-or-typecheck"):
        require(metrics[metric_id]["samples"] == 15, f"{metric_id} must retain 15 samples")
    thresholds = protocol["thresholds"]
    require(thresholds == {
        "maximum_authored_loc": 42,
        "maximum_low_level_concepts": 7,
        "warm_discovery_p95_seconds_exclusive": 0.15,
        "near_budget_seconds_inclusive": 0.01,
        "b_further_improvement_fraction_inclusive": 0.15,
    }, "thresholds drifted")
    require(set(protocol["candidates"]) == {"A", "B", "C", "D"}, "candidate set drifted")
    require(protocol["agent_trial"]["attempts"] == 2, "agent attempt count drifted")
    expected = HASH_FILE.read_text().strip().split()[0]
    actual = hashlib.sha256(raw).hexdigest()
    require(actual == expected, f"protocol digest mismatch: expected {expected}, got {actual}")
    print(f"verify-protocol: PASS {actual}")


if __name__ == "__main__":
    main()
