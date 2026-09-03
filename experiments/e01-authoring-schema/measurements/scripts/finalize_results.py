#!/usr/bin/env python3
import hashlib
import json
import math
from pathlib import Path


SCRIPT = Path(__file__).resolve()
MEASUREMENTS = SCRIPT.parents[1]
ROOT = SCRIPT.parents[4]
PROTOCOL = json.loads((MEASUREMENTS / "protocol.json").read_text())
AUDIT = json.loads((MEASUREMENTS / "candidate-audit.json").read_text())
TRIALS = json.loads((ROOT / "experiments/e01-authoring-schema/agent-trials/summary.json").read_text())
RESULTS = MEASUREMENTS / "results"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"finalize-results: {message}")


def load_record(candidate: str, metric: str, phase: str = "primary") -> dict:
    record = json.loads((RESULTS / phase / candidate / metric / "record.json").read_text())
    require(record["schema_version"] == PROTOCOL["benchmark_schema"], f"{candidate} {metric} schema")
    require(record["source_revision"] == PROTOCOL["candidate_source_revision"], f"{candidate} {metric} revision")
    require(record["fixture_id"] == PROTOCOL["benchmark_fixture"], f"{candidate} {metric} fixture")
    expected = next(item for item in PROTOCOL["metrics"] if item["id"] == metric)
    require(record["sample_count"] == expected["samples"], f"{candidate} {metric} sample count")
    require(len(record["samples"]) == expected["samples"], f"{candidate} {metric} raw samples")
    require(record["state"] == expected["state"], f"{candidate} {metric} state")
    return record


def digest_files(paths: list[Path]) -> dict[str, str]:
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}


def main() -> None:
    execution = json.loads((RESULTS / "execution.json").read_text())
    require(execution["primary_order"] == PROTOCOL["candidate_order"]["primary"], "execution order")
    candidates = {}
    budget = PROTOCOL["thresholds"]["warm_discovery_p95_seconds_exclusive"]
    for candidate in PROTOCOL["candidate_order"]["primary"]:
        metrics = {item["id"]: load_record(candidate, item["id"]) for item in PROTOCOL["metrics"]}
        primary_p95 = metrics["warm-discovery"]["p95"]
        decision_p95 = primary_p95
        if execution["reverse_run"]:
            reverse = load_record(candidate, "warm-discovery", "reverse")
            decision_p95 = max(primary_p95, reverse["p95"])
        audit = AUDIT["candidates"][candidate]
        candidates[candidate] = {
            "approach": audit["approach"],
            "hard_gates": audit["hard_gates"],
            "authored_loc": audit["authored_loc"],
            "authored_loc_pass": audit["authored_loc"] <= PROTOCOL["thresholds"]["maximum_authored_loc"],
            "low_level_concept_count": len(audit["low_level_concepts"]),
            "low_level_concepts_pass": len(audit["low_level_concepts"]) <= PROTOCOL["thresholds"]["maximum_low_level_concepts"],
            "warm_discovery_median_seconds": metrics["warm-discovery"]["median"],
            "warm_discovery_primary_p95_seconds": primary_p95,
            "warm_discovery_decision_p95_seconds": decision_p95,
            "warm_discovery_pass": decision_p95 < budget,
            "cold_discovery_median_seconds": metrics["cold-discovery"]["median"],
            "cold_discovery_p95_seconds": metrics["cold-discovery"]["p95"],
            "cold_driver_build_or_typecheck_median_seconds": metrics["cold-driver-build-or-typecheck"]["median"],
            "cold_driver_build_or_typecheck_p95_seconds": metrics["cold-driver-build-or-typecheck"]["p95"],
            "warm_driver_build_or_typecheck_median_seconds": metrics["warm-driver-build-or-typecheck"]["median"],
            "warm_driver_build_or_typecheck_p95_seconds": metrics["warm-driver-build-or-typecheck"]["p95"],
            "agent_trial_pass": TRIALS["success"],
        }
    a = candidates["A"]
    b = candidates["B"]
    loc_boundary = math.floor(a["authored_loc"] * 0.85)
    concept_boundary = math.floor(a["low_level_concept_count"] * 0.85)
    b_further_improvement = b["authored_loc"] <= loc_boundary or b["low_level_concept_count"] <= concept_boundary
    common_pass = lambda value: (
        value["hard_gates"] == "pass"
        and value["authored_loc_pass"]
        and value["low_level_concepts_pass"]
        and value["warm_discovery_pass"]
        and value["agent_trial_pass"]
    )
    require(common_pass(a), "A unexpectedly failed a continue gate")
    require(common_pass(b), "B unexpectedly failed a continue gate")
    require(b_further_improvement, "B did not meet the frozen further-improvement rule")
    require(AUDIT["candidate_b_additional_gates"] == {
        "stale_output_rejected": True,
        "diagnostic_maps_to_authored_declaration": True,
    }, "B additional gates")
    require(TRIALS["attempts_succeeded"] == 2 and TRIALS["attempts_required"] == 2, "agent trial result")
    scorecard = {
        "schema_version": "taskflow-e01-scorecard/v1",
        "roadmap_id": "E01",
        "task_id": "TF-003.07",
        "candidate_source_revision": PROTOCOL["candidate_source_revision"],
        "protocol_sha256": hashlib.sha256((MEASUREMENTS / "protocol.json").read_bytes()).hexdigest(),
        "reverse_warm_discovery_run": execution["reverse_run"],
        "candidates": candidates,
        "candidate_b_comparison_to_a": {
            "a_loc": a["authored_loc"],
            "b_loc": b["authored_loc"],
            "maximum_b_loc_for_15_percent_rule": loc_boundary,
            "loc_reduction_fraction": (a["authored_loc"] - b["authored_loc"]) / a["authored_loc"],
            "a_concepts": a["low_level_concept_count"],
            "b_concepts": b["low_level_concept_count"],
            "maximum_b_concepts_for_15_percent_rule": concept_boundary,
            "concept_reduction_fraction": (a["low_level_concept_count"] - b["low_level_concept_count"]) / a["low_level_concept_count"],
            "further_improvement_pass": b_further_improvement,
            "stale_output_rejected": True,
            "source_mapped_generator_diagnostic": True,
            "burden_assessment": "acceptable for an E01 recommendation, not a production implementation: 7 annotation lines, 171 generator LOC, 158 generated LOC, and one tag-reflection site remain explicit Gate 1 inputs",
        },
        "agent_trial": {
            "attempts": 2,
            "successes": 2,
            "shared_bundle": True,
            "bundle_digest": TRIALS["outcomes"][0]["bundle_digest"],
            "source_read_attempts": 0,
            "pass": True,
        },
        "chosen_branch": "B-wins",
        "recommendation": "Use code generation from Go declarations as the E01 input to Gate 1; define generator/version ergonomics before any foundation or public SDK work.",
        "contracts_stabilized_now": [],
    }
    (MEASUREMENTS / "scorecard.json").write_text(json.dumps(scorecard, indent=2, sort_keys=True) + "\n")
    raw_paths = list(RESULTS.rglob("*"))
    raw_paths += list((MEASUREMENTS / "failures").rglob("*"))
    raw_paths += list((MEASUREMENTS / "amendments").rglob("*"))
    raw_paths += list((ROOT / "experiments/e01-authoring-schema/agent-trials/results").rglob("*"))
    raw_paths += list((ROOT / "experiments/e01-authoring-schema/agent-trials/setup-failures").rglob("*"))
    raw_paths += list((ROOT / "experiments/e01-authoring-schema/agent-trials/setup-amendments").rglob("*"))
    raw_files = [path for path in raw_paths if path.is_file()]
    evidence = {
        "schema_version": "taskflow-e01-evidence-manifest/v1",
        "protocol_sha256": scorecard["protocol_sha256"],
        "files": digest_files(raw_files),
    }
    (MEASUREMENTS / "evidence-manifest.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print("finalize-results: PASS B-wins")


if __name__ == "__main__":
    main()
