#!/usr/bin/env python3
"""Apply the frozen E05 gates and ordered decision matrix."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def median(runs, field):
    return statistics.median(field(run) for run in runs)


def evaluate(root):
    thresholds = json.loads((Path(__file__).resolve().parents[1] / "thresholds.json").read_text())
    runs = json.loads((root / "results/simulation-metrics.json").read_text())["runs"]
    life = json.loads((root / "results/lifecycle.json").read_text())
    durability = json.loads((root / "raw/durability/summary.json").read_text())
    sqlite_ops = json.loads((root / "measurements/sqlite-operations.json").read_text())
    operational = json.loads((root / "measurements/operational-proxy.json").read_text())
    t1_startup = json.loads((root / "measurements/t1-warm-startup/record.json").read_text())

    grouped = {}
    for mode in sorted({run["mode"] for run in runs}):
        grouped[mode] = {}
        for scale in (1, 4, 20):
            selected = [run for run in runs if run["mode"] == mode and run["scale"] == scale]
            grouped[mode][str(scale)] = {
                "makespan_ticks_median": median(selected, lambda r: r["makespan_ticks"]),
                "throughput_median": median(selected, lambda r: r["throughput_nodes_per_tick"]),
                "queue_p95_median": median(selected, lambda r: r["queue_p95_ticks"]),
                "interactive_queue_p95_median": median(selected, lambda r: r["queue_p95_by_class_ticks"]["interactive"]),
                "background_queue_p95_median": median(selected, lambda r: r["queue_p95_by_class_ticks"]["background"]),
                "capacity_violations": sum(r["capacity_violation_count"] for r in selected),
                "max_wait_ratio": max(r["max_ready_wait_over_longest_service"] for r in selected),
                "minimum_jain_by_class": {klass: min(r["jain_service_by_class"][klass] for r in selected)
                                           for klass in ("interactive", "background")},
                "maximum_starved": max(r["starved_request_count"] for r in selected),
                "minimum_terminal_ratio": min(r["non_cancelled_terminal_ratio"] for r in selected),
                "maximum_drain_leases": max(r["active_lease_count_at_drain"] for r in selected),
                "provider_utilization_median": {provider: median(selected, lambda r, p=provider: r["provider_utilization_percent"][p])
                                                  for provider in ("local", "linux", "macos", "simulator", "device")},
            }

    fifo = grouped["shared-fifo"]
    safe = grouped["independent-provider-guard"]
    weighted = grouped["shared-weighted-aging"]
    for scale in (1, 4, 20):
        key = str(scale)
        weighted[key]["fairness_pass"] = (
            weighted[key]["maximum_starved"] == 0
            and min(weighted[key]["minimum_jain_by_class"].values()) >= .95
            and weighted[key]["max_wait_ratio"] <= 10
            and weighted[key]["interactive_queue_p95_median"] <= fifo[key]["interactive_queue_p95_median"]
            and weighted[key]["background_queue_p95_median"] <= 2 * fifo[key]["background_queue_p95_median"])
        throughput_ratio = weighted[key]["throughput_median"] / safe[key]["throughput_median"]
        makespan_ratio = weighted[key]["makespan_ticks_median"] / safe[key]["makespan_ticks_median"]
        interactive_base = safe[key]["interactive_queue_p95_median"]
        interactive_ratio = weighted[key]["interactive_queue_p95_median"] / interactive_base if interactive_base else 0
        saturated = [p for p, value in safe[key]["provider_utilization_median"].items() if value >= 80]
        max_regression = max((safe[key]["provider_utilization_median"][p] - weighted[key]["provider_utilization_median"][p]
                              for p in saturated), default=0)
        weighted[key]["material_benefit"] = {
            "throughput_ratio": throughput_ratio, "makespan_ratio": makespan_ratio,
            "interactive_queue_ratio": interactive_ratio,
            "saturated_provider_utilization_regression_pp": max_regression,
            "pass": (throughput_ratio >= 1.15 or makespan_ratio <= .85)
                    and interactive_ratio <= .8 and max_regression <= 2}

    durability_keys = [key.removesuffix("_max") for key in thresholds["durability"]
                       if key != "fresh_process_case_count"]
    durability_pass = durability["fresh_process_case_count"] == 60 and all(durability[key] == 0 for key in durability_keys)
    cleanup = operational["cleanup"]
    cleanup_pass = cleanup["sample_count"] == 30 and cleanup["p95_seconds"] <= 1 and cleanup["max_seconds"] <= 2
    quiet = operational["quiescent_controller"]
    operations_pass = (t1_startup["sample_count"] == 30 and t1_startup["p95"] <= .25
                       and sqlite_ops["startup_reopen_p95_seconds"] <= .25 and quiet["sample_seconds"] == 30
                       and quiet["idle_cpu_p95_percent"] <= 1 and quiet["idle_rss_p95_mib"] <= 40
                       and quiet["clean_stop_seconds"] <= 1 and quiet["resident_process_count"] <= 1
                       and quiet["state_directory_count"] <= 1 and quiet["external_service_count"] == 0
                       and quiet["manual_pre_run_start_count"] == 0
                       and sqlite_ops["incompatible_schema_failed_closed"] and sqlite_ops["backup_restore_rehearsal_passed"])
    attachment_pass = life["false_attachment_count"] == 0 and life["duplicate_active_run_avoided_count"] >= 1
    safety_pass = all(weighted[str(scale)]["capacity_violations"] == 0
                      and weighted[str(scale)]["maximum_drain_leases"] == 0
                      and weighted[str(scale)]["minimum_terminal_ratio"] == 1 for scale in (1, 4, 20))
    fairness_pass = all(weighted[str(scale)]["fairness_pass"] for scale in (1, 4, 20))
    hard_pass = safety_pass and fairness_pass and cleanup_pass
    material20 = weighted["20"]["material_benefit"]["pass"]
    material_any = weighted["4"]["material_benefit"]["pass"] or material20
    single_regression = weighted["1"]["makespan_ticks_median"] / safe["1"]["makespan_ticks_median"] - 1
    unique_ownership_results = int(durability_pass) + int(attachment_pass)
    broker = grouped["broker-only"]["20"]
    broker_throughput_ratio = broker["throughput_median"] / weighted["20"]["throughput_median"]
    broker_queue_difference = abs(broker["queue_p95_median"] - weighted["20"]["queue_p95_median"]) / max(1, weighted["20"]["queue_p95_median"])

    if not durability_pass:
        branch, order = "stronger-state-model", 1
    elif not hard_pass:
        branch, order = "stop", 2
    elif (material20 and single_regression <= .05 and operations_pass and attachment_pass):
        branch, order = "full-daemon", 3
    elif material_any and attachment_pass and durability_pass and (single_regression > .05 or not operations_pass):
        branch, order = "on-demand-daemon", 4
    elif (broker_throughput_ratio >= .95 and broker_queue_difference <= .1 and unique_ownership_results == 0):
        branch, order = "broker-only", 5
    else:
        branch, order = "stop-narrow", 6

    return {"format_version": "e05-scorecard-v1-experimental", "selected_branch": branch,
            "decision_precedence_order": order, "candidate_distributions": grouped,
            "gates": {"weighted_safety": safety_pass, "weighted_fairness_all_scales": fairness_pass,
                      "durability": durability_pass, "cleanup": cleanup_pass, "attachment": attachment_pass,
                      "operations": operations_pass, "material_benefit_scale_20": material20,
                      "material_benefit_scale_4_or_20": material_any,
                      "single_agent_makespan_regression_fraction": single_regression,
                      "unique_full_run_ownership_passing_result_count": unique_ownership_results,
                      "broker_throughput_over_weighted": broker_throughput_ratio,
                      "broker_interactive_queue_difference_fraction": broker_queue_difference},
            "thresholds_source": "thresholds.json", "decision_matrix_source": "decision-matrix.json"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.root)
    (args.root / "results/scorecard.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"selected_branch": result["selected_branch"]}, sort_keys=True))


if __name__ == "__main__":
    main()
