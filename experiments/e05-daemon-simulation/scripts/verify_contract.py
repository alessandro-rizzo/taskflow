#!/usr/bin/env python3
"""Verify the frozen E05 Phase A contract and reject Phase B material."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


FROZEN_ARTIFACTS = [
    "README.md",
    "Taskfile.yml",
    "contract.json",
    "decision-matrix.json",
    "fixture-bindings.json",
    "policies.json",
    "scripts/verify_contract.py",
    "tests/test_verify_contract.py",
    "thresholds.json",
    "workload.json",
]

ALLOWED_TOP_LEVEL = {
    "README.md",
    "Taskfile.yml",
    "contract.json",
    "decision-matrix.json",
    "fixture-bindings.json",
    "frozen-artifacts.json",
    "policies.json",
    "protocol.sha256",
    "scripts",
    "tests",
    "thresholds.json",
    "workload.json",
}

FORBIDDEN_PHASE_B_NAMES = {
    "decision.json",
    "evidence",
    "measurements",
    "results",
    "run_experiment.py",
    "scorecard.json",
    "simulator.py",
    "sqlite_store.py",
    "summary.json",
}

EXPECTED_FIXTURE_DIGESTS = {
    "fixtures/w1/manifest.yaml": "18a61f791c198e16f3e478243213e6d48bb3223357c14f6a674c2f3862415169",
    "fixtures/w2/graph.json": "68d599c31ebe04c085610a98ff37e1775db650e2d034d553ac291632fcd7d45b",
    "fixtures/w3/examples/namespace-a.json": "b86378913dcc9f7e80c8a47cf387f68a5a6130d88592fa02be72229e85a3583e",
    "fixtures/w3/examples/namespace-b.json": "22db508434c6997cc8ec4bd9b0dee4bc0a01181380ca196e0abb875c865ab682",
    "fixtures/w3/examples/scenario-caller-loss.json": "88fbb5623f79bfcf572759bfe6f16a5371a423f24b098969a0194923b33800cc",
    "fixtures/t1-lifecycle-faults/lifecycle.go": "a8152ae131029baf5110adc58569f7ad2a0e06109781200aec311ceb6b68425c",
    "fixtures/t1-lifecycle-faults/lease_state.go": "4a70cb20e995f9d4b69e29a561c04e3f856113d50c6bef7e557b4e76a1e42e23",
}

EXPECTED_THRESHOLDS = {
    "safety": {
        "capacity_violation_count_max": 0,
        "active_lease_count_at_drain_max": 0,
        "non_cancelled_terminal_ratio_min": 1.0,
    },
    "weighted_fairness": {
        "starved_request_count_max": 0,
        "per_class_jain_service_index_min": 0.95,
        "max_ready_wait_over_longest_compatible_service_max": 10.0,
        "interactive_queue_p95_over_fifo_max": 1.0,
        "background_queue_p95_over_fifo_max": 2.0,
    },
    "material_shared_benefit": {
        "throughput_over_safe_independent_min": 1.15,
        "makespan_over_safe_independent_max": 0.85,
        "throughput_or_makespan": True,
        "interactive_queue_p95_over_safe_independent_max": 0.8,
        "saturated_provider_utilization_regression_percentage_points_max": 2.0,
    },
    "attachment": {
        "false_attachment_count_max": 0,
        "duplicate_active_run_avoided_count_min": 1,
    },
    "durability": {
        "fresh_process_case_count": 60,
        "committed_event_loss_count_max": 0,
        "committed_event_duplicate_count_max": 0,
        "visible_uncommitted_transition_count_max": 0,
        "event_sequence_gap_or_reorder_count_max": 0,
        "sqlite_integrity_failure_count_max": 0,
        "post_recovery_capacity_violation_count_max": 0,
    },
    "cleanup": {
        "reaper_interval_ticks": 1,
        "max_ticks_after_expiry": 1,
        "wall_clock_samples": 30,
        "wall_clock_p95_seconds_max": 1.0,
        "wall_clock_max_seconds_max": 2.0,
    },
    "operations": {
        "warm_startup_reopen_samples": 30,
        "warm_startup_reopen_p95_seconds_max": 0.25,
        "quiescent_sample_seconds": 30,
        "idle_cpu_p95_percent_max": 1.0,
        "idle_rss_p95_mib_max": 40.0,
        "clean_stop_seconds_max": 1.0,
        "resident_process_count_max": 1,
        "state_directory_count_max": 1,
        "external_service_count_max": 0,
        "manual_pre_run_start_count_max": 0,
    },
    "full_daemon": {
        "single_agent_makespan_regression_fraction_max": 0.05,
    },
    "broker_only": {
        "throughput_over_full_daemon_min": 0.95,
        "queue_p95_difference_from_full_daemon_fraction_max": 0.1,
        "unique_full_run_ownership_passing_result_count_max": 0,
    },
}

EXPECTED_CANDIDATE_IDS = [
    "independent-unguarded-negative-control",
    "independent-provider-guard",
    "broker-only",
    "shared-fifo",
    "shared-strict-interactive",
    "shared-weighted-aging",
]

EXPECTED_POLICY_CANDIDATES = [
    {
        "id": "independent-unguarded-negative-control",
        "kind": "negative-control",
        "negative_control": True,
        "throughput_comparator": False,
        "run_state_owner": "client",
        "resource_owner": "client",
        "queue_policy": "none",
        "retry_ticks": 0,
    },
    {
        "id": "independent-provider-guard",
        "kind": "independent-cli",
        "negative_control": False,
        "throughput_comparator": True,
        "run_state_owner": "client",
        "resource_owner": "provider-atomic-guard",
        "queue_policy": "per-client",
        "retry_ticks": 1,
    },
    {
        "id": "broker-only",
        "kind": "resource-broker",
        "negative_control": False,
        "throughput_comparator": False,
        "run_state_owner": "client",
        "resource_owner": "shared-broker",
        "queue_policy": "broker-oldest-eligible",
        "retry_ticks": 0,
    },
    {
        "id": "shared-fifo",
        "kind": "shared-daemon",
        "negative_control": False,
        "throughput_comparator": False,
        "run_state_owner": "shared-controller",
        "resource_owner": "shared-controller",
        "queue_policy": "oldest-ready-eligible",
        "retry_ticks": 0,
    },
    {
        "id": "shared-strict-interactive",
        "kind": "shared-daemon",
        "negative_control": False,
        "throughput_comparator": False,
        "run_state_owner": "shared-controller",
        "resource_owner": "shared-controller",
        "queue_policy": "interactive-before-background",
        "retry_ticks": 0,
    },
    {
        "id": "shared-weighted-aging",
        "kind": "shared-daemon",
        "negative_control": False,
        "throughput_comparator": False,
        "run_state_owner": "shared-controller",
        "resource_owner": "shared-controller",
        "queue_policy": "weighted-round-robin-with-aging",
        "retry_ticks": 0,
        "interactive_weight": 3,
        "background_weight": 1,
        "age_promotion_ticks": 36,
    },
]

EXPECTED_WORKFLOW_TEMPLATES = {
    "W1": {
        "fixture_id": "w1-fast-project-check",
        "nodes": [
            {"id": "format", "duration_ticks": 3, "resources": {"local": 1}, "needs": []},
            {"id": "test", "duration_ticks": 5, "resources": {"local": 1}, "needs": []},
            {"id": "lint", "duration_ticks": 4, "resources": {"local": 1}, "needs": []},
            {"id": "check", "duration_ticks": 1, "resources": {}, "needs": ["format", "test", "lint"]},
        ],
    },
    "W2": {
        "fixture_id": "w2-cross-target-artifact-pipeline",
        "nodes": [
            {"id": "build", "duration_ticks": 8, "resources": {"linux": 1}, "needs": []},
            {"id": "test", "duration_ticks": 6, "resources": {"linux": 1}, "needs": ["build"]},
            {"id": "inspect", "duration_ticks": 2, "resources": {"local": 1}, "needs": ["build"]},
        ],
    },
    "W3": {
        "fixture_id": "w3-isolated-native-mobile-stack",
        "variant_assignment": "odd-numbered agents use simulator; even-numbered agents use device",
        "nodes": [
            {"id": "linux-service", "duration_ticks": 18, "resources": {"linux": 1}, "needs": [], "lease": "namespace-session"},
            {"id": "macos-build", "duration_ticks": 10, "resources": {"macos": 1}, "needs": []},
            {"id": "mobile-e2e-simulator", "duration_ticks": 12, "resources": {"macos": 1, "simulator": 1}, "needs": ["linux-service", "macos-build"], "variant": "simulator"},
            {"id": "mobile-e2e-device", "duration_ticks": 12, "resources": {"macos": 1, "device": 1}, "needs": ["linux-service", "macos-build"], "variant": "device"},
            {"id": "cleanup", "duration_ticks": 2, "resources": {}, "needs": ["mobile-e2e-selected"]},
        ],
    },
}

EXPECTED_ATTACHMENT_CASES = [
    "all identity and authorization fields match",
    "project differs",
    "source differs",
    "operation differs",
    "arguments differ",
    "plan digest differs",
    "namespace policy differs",
    "caller is unauthorized",
]

EXPECTED_DECISION_REFS = {
    "stronger-state-model": ["durability"],
    "stop": ["safety", "weighted_fairness", "cleanup"],
    "full-daemon": ["safety", "weighted_fairness", "material_shared_benefit", "attachment", "durability", "cleanup", "operations", "full_daemon"],
    "on-demand-daemon": ["safety", "weighted_fairness", "material_shared_benefit", "attachment", "durability", "cleanup", "operations", "full_daemon"],
    "broker-only": ["safety", "cleanup", "broker_only"],
    "stop-narrow": [],
}

EXPECTED_PHASE_A_ALLOWS = [
    "frozen contract",
    "frozen workload",
    "frozen policy candidates",
    "frozen thresholds",
    "frozen decision matrix",
    "fixture digest bindings",
    "contract verifier",
    "contract verifier tests",
    "contract-only task command",
]

EXPECTED_PHASE_A_FORBIDS = [
    "scheduler simulation",
    "SQLite adapter",
    "benchmark execution",
    "raw traces",
    "measurement summaries",
    "scorecard results",
    "selected decision branch",
]

EXPECTED_BRANCHES = [
    "stronger-state-model",
    "stop",
    "full-daemon",
    "on-demand-daemon",
    "broker-only",
    "stop-narrow",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ContractVerifier:
    def __init__(self, experiment_root: Path, repository_root: Path) -> None:
        self.experiment_root = experiment_root.resolve()
        self.repository_root = repository_root.resolve()
        self.errors: List[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def load_json(self, relative: str) -> Dict[str, Any]:
        path = self.experiment_root / relative
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.error(f"{relative}: cannot load JSON: {exc}")
            return {}
        if not isinstance(value, dict):
            self.error(f"{relative}: top-level value must be an object")
            return {}
        return value

    def exact_keys(self, value: Dict[str, Any], expected: Iterable[str], label: str) -> None:
        got = set(value)
        want = set(expected)
        if got != want:
            self.error(
                f"{label}: exact keys required; missing={sorted(want - got)} extra={sorted(got - want)}"
            )

    def verify_phase_boundary(self) -> None:
        try:
            entries = {path.name for path in self.experiment_root.iterdir()}
        except OSError as exc:
            self.error(f"phase boundary: cannot list experiment root: {exc}")
            return
        unexpected = sorted(entries - ALLOWED_TOP_LEVEL)
        missing = sorted(ALLOWED_TOP_LEVEL - entries)
        if unexpected:
            self.error(f"phase boundary: unexpected top-level entries: {unexpected}")
        if missing:
            self.error(f"phase boundary: missing Phase A entries: {missing}")

        for path in self.experiment_root.rglob("*"):
            if "__pycache__" in path.parts:
                continue
            if path.name in FORBIDDEN_PHASE_B_NAMES:
                self.error(f"phase boundary: Phase B artifact is forbidden: {path.relative_to(self.experiment_root)}")
            if path.is_file() and path.suffix in {".db", ".sqlite", ".sqlite3", ".jsonl", ".gz"}:
                self.error(f"phase boundary: Phase B evidence file is forbidden: {path.relative_to(self.experiment_root)}")

    def verify_frozen_artifacts(self) -> None:
        manifest = self.load_json("frozen-artifacts.json")
        self.exact_keys(manifest, {"format_version", "hash_algorithm", "artifacts"}, "frozen-artifacts.json")
        if manifest.get("format_version") != "e05-phase-a-frozen-artifacts-v1-experimental":
            self.error("frozen-artifacts.json: format_version must remain experimental v1")
        if manifest.get("hash_algorithm") != "sha256":
            self.error("frozen-artifacts.json: hash_algorithm must be sha256")

        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list):
            self.error("frozen-artifacts.json: artifacts must be a list")
            artifacts = []
        paths: List[str] = []
        for index, entry in enumerate(artifacts):
            if not isinstance(entry, dict):
                self.error(f"frozen-artifacts.json: artifacts[{index}] must be an object")
                continue
            self.exact_keys(entry, {"path", "sha256"}, f"frozen-artifacts.json artifacts[{index}]")
            relative = entry.get("path")
            declared = entry.get("sha256")
            if not isinstance(relative, str):
                self.error(f"frozen-artifacts.json: artifacts[{index}].path must be a string")
                continue
            paths.append(relative)
            path = self.experiment_root / relative
            if not path.is_file():
                self.error(f"frozen-artifacts.json: missing artifact {relative}")
                continue
            actual = sha256(path)
            if declared != actual:
                self.error(f"frozen-artifacts.json: digest mismatch for {relative}: want {declared}, got {actual}")
        if paths != FROZEN_ARTIFACTS:
            self.error(f"frozen-artifacts.json: artifact order/set must be {FROZEN_ARTIFACTS}, got {paths}")

        protocol_path = self.experiment_root / "protocol.sha256"
        try:
            protocol = protocol_path.read_text(encoding="utf-8")
        except OSError as exc:
            self.error(f"protocol.sha256: cannot read: {exc}")
            return
        expected_line = f"{sha256(self.experiment_root / 'frozen-artifacts.json')}  frozen-artifacts.json\n"
        if protocol != expected_line:
            self.error("protocol.sha256: must contain the current frozen-artifacts.json digest")

    def verify_contract(self) -> None:
        contract = self.load_json("contract.json")
        self.exact_keys(
            contract,
            {
                "format_version",
                "experiment_id",
                "task_id",
                "status",
                "baseline_revision",
                "question",
                "risks",
                "canonical_requirements",
                "scope",
                "phase_boundary",
                "phase_b_evidence_contract",
                "verification_command",
            },
            "contract.json",
        )
        if contract.get("format_version") != "e05-phase-a-contract-v1-experimental":
            self.error("contract.json: format_version must remain experimental v1")
        if contract.get("experiment_id") != "E05" or contract.get("task_id") != "TF-003.12":
            self.error("contract.json: experiment_id/task_id mismatch")
        if contract.get("status") != "phase-a-frozen-contract":
            self.error("contract.json: status must be phase-a-frozen-contract")
        if contract.get("risks") != ["R6", "R7"]:
            self.error("contract.json: risks must remain R6 and R7")

        requirements = contract.get("canonical_requirements", {})
        self.exact_keys(
            requirements,
            {"exercised", "partially_exercised", "not_claimed", "stale_ticket_references", "stale_reference_policy"},
            "contract.json canonical_requirements",
        )
        expected_exercised = ["AGENT-2", "AGENT-3", "AGENT-5", "EXEC-2", "EXEC-3", "EXEC-5", "DUR-1", "DUR-3"]
        if requirements.get("exercised") != expected_exercised:
            self.error("contract.json: canonical exercised requirements changed")
        if list(requirements.get("partially_exercised", {}).keys()) != ["AGENT-4"]:
            self.error("contract.json: only AGENT-4 may be partially exercised")
        if requirements.get("not_claimed") != ["AGENT-1", "AGENT-6", "DUR-2"]:
            self.error("contract.json: non-claims changed")
        if requirements.get("stale_ticket_references") != ["CONC-1", "CONC-2", "CONC-3", "CONC-4", "DUR-4"]:
            self.error("contract.json: stale ticket reference list changed")

        scope = contract.get("scope", {})
        self.exact_keys(
            scope,
            {"provider_classes", "real_builds", "real_providers", "production_daemon", "production_module", "prototype_imports", "fixture_imports", "phase_a_results"},
            "contract.json scope",
        )
        expected_providers = ["local", "linux", "macos", "simulator", "device"]
        if scope.get("provider_classes") != expected_providers:
            self.error("contract.json: fake provider classes changed")
        for key in ["real_builds", "real_providers", "production_daemon", "production_module", "prototype_imports", "fixture_imports", "phase_a_results"]:
            if scope.get(key) is not False:
                self.error(f"contract.json: scope.{key} must be false in Phase A")

        phase_boundary = contract.get("phase_boundary", {})
        self.exact_keys(
            phase_boundary,
            {"phase_a_allows", "phase_a_forbids", "phase_b_precondition"},
            "contract.json phase_boundary",
        )
        if phase_boundary.get("phase_a_allows") != EXPECTED_PHASE_A_ALLOWS:
            self.error("contract.json: Phase A allowed-artifact list changed")
        if phase_boundary.get("phase_a_forbids") != EXPECTED_PHASE_A_FORBIDS:
            self.error("contract.json: Phase A forbidden-artifact list changed")
        precondition = phase_boundary.get("phase_b_precondition", "")
        if not isinstance(precondition, str) or "accepted" not in precondition or "commit" not in precondition:
            self.error("contract.json: Phase B requires an accepted Phase A commit")
        if contract.get("verification_command") != "mise exec -- task --dir experiments/e05-daemon-simulation check:phase-a":
            self.error("contract.json: verification command changed")

    def verify_workload(self) -> None:
        workload = self.load_json("workload.json")
        self.exact_keys(
            workload,
            {
                "format_version",
                "experiment_id",
                "primary_agent_count",
                "submission_count",
                "requested_max_concurrency_per_agent",
                "scale_sweep_agent_counts",
                "provider_capacities",
                "lease_policy",
                "agents",
                "plans_per_agent",
                "submission_waves",
                "workflow_templates",
                "tie_order_seeds",
                "lifecycle_cases",
                "durability_cases",
                "operational_samples",
            },
            "workload.json",
        )
        if workload.get("format_version") != "e05-workload-v1-experimental":
            self.error("workload.json: format_version must remain experimental v1")
        if workload.get("experiment_id") != "E05":
            self.error("workload.json: experiment_id must be E05")
        if workload.get("primary_agent_count") != 20:
            self.error("workload.json: primary_agent_count must be 20")
        if workload.get("submission_count") != 60:
            self.error("workload.json: submission_count must be 60")
        if workload.get("requested_max_concurrency_per_agent") != 32:
            self.error("workload.json: requested max concurrency must be 32")
        if workload.get("scale_sweep_agent_counts") != [1, 4, 20]:
            self.error("workload.json: scale sweep must be 1, 4, and 20 agents")
        if workload.get("provider_capacities") != {"local": 4, "linux": 4, "macos": 2, "simulator": 2, "device": 1}:
            self.error("workload.json: provider capacities changed")
        if workload.get("lease_policy") != {"ttl_ticks": 5, "heartbeat_interval_ticks": 2, "reaper_interval_ticks": 1}:
            self.error("workload.json: lease TTL, heartbeat, or reaper interval changed")

        agents = workload.get("agents", [])
        if not isinstance(agents, list) or len(agents) != 20:
            self.error("workload.json: exactly 20 agents are required")
            agents = []
        ids = [agent.get("id") for agent in agents if isinstance(agent, dict)]
        namespaces = [agent.get("namespace") for agent in agents if isinstance(agent, dict)]
        classes = [agent.get("class") for agent in agents if isinstance(agent, dict)]
        if len(set(ids)) != 20 or len(set(namespaces)) != 20:
            self.error("workload.json: agent ids and namespaces must be unique")
        if classes.count("interactive") != 10 or classes.count("background") != 10:
            self.error("workload.json: workload must contain 10 interactive and 10 background agents")
        if workload.get("plans_per_agent") != ["W1", "W2", "W3"]:
            self.error("workload.json: each agent must submit W1, W2, and W3")
        if len(agents) * len(workload.get("plans_per_agent", [])) != workload.get("submission_count"):
            self.error("workload.json: submission_count does not match agents times plans")

        expected_waves = [
            (0, "background", "W1", 10),
            (2, "interactive", "W1", 10),
            (4, "background", "W2", 10),
            (6, "interactive", "W2", 10),
            (8, "background", "W3", 10),
            (10, "interactive", "W3", 10),
        ]
        waves = workload.get("submission_waves", [])
        normalized_waves = [
            (wave.get("tick"), wave.get("class"), wave.get("workflow"), wave.get("agents"))
            for wave in waves
            if isinstance(wave, dict)
        ]
        if normalized_waves != expected_waves:
            self.error("workload.json: submission waves changed")
        if sum(item[3] for item in normalized_waves if isinstance(item[3], int)) != 60:
            self.error("workload.json: submission waves must total 60")

        templates = workload.get("workflow_templates", {})
        if templates != EXPECTED_WORKFLOW_TEMPLATES:
            self.error("workload.json: frozen workflow templates changed")
        node_durations = []
        for template in templates.values():
            if isinstance(template, dict):
                node_durations.extend(
                    node.get("duration_ticks")
                    for node in template.get("nodes", [])
                    if isinstance(node, dict)
                )
        if not node_durations or max(node_durations) != 18:
            self.error("workload.json: longest declared node service time must remain 18 ticks")
        if templates.get("W3", {}).get("variant_assignment") != "odd-numbered agents use simulator; even-numbered agents use device":
            self.error("workload.json: W3 simulator/device assignment changed")

        if workload.get("tie_order_seeds") != list(range(1, 31)):
            self.error("workload.json: tie-order seeds must be exactly 1 through 30")
        lifecycle = workload.get("lifecycle_cases", {})
        if lifecycle.get("client_disconnect") != {"accepted_run_survives_client": True, "abandoned_namespace_expires": True}:
            self.error("workload.json: client-disconnect cases changed")
        if lifecycle.get("attachment") != EXPECTED_ATTACHMENT_CASES:
            self.error("workload.json: attachment identity cases changed")
        if lifecycle.get("concurrency_groups") != ["queue-all", "keep-newest-pending", "cancel-superseded-active"]:
            self.error("workload.json: concurrency-group cases changed")
        durability = workload.get("durability_cases", {})
        phases = durability.get("phases", [])
        timings = durability.get("timings", [])
        seeds = durability.get("seeds", [])
        case_count = len(phases) * len(timings) * len(seeds)
        if phases != ["admission", "execution", "cleanup"] or timings != ["before-commit", "after-commit"] or seeds != list(range(1, 11)):
            self.error("workload.json: durability matrix changed")
        if durability.get("expected_case_count") != 60 or case_count != 60:
            self.error("workload.json: durability matrix must contain exactly 60 cases")
        if workload.get("operational_samples") != {"disconnect_reopen": 30, "warm_startup_reopen": 30, "quiescent_seconds": 30}:
            self.error("workload.json: operational sample counts changed")

    def verify_policies(self) -> None:
        policies = self.load_json("policies.json")
        self.exact_keys(policies, {"format_version", "experiment_id", "common_rules", "candidates"}, "policies.json")
        if policies.get("format_version") != "e05-policy-candidates-v1-experimental":
            self.error("policies.json: format_version must remain experimental v1")
        expected_common = {
            "multi_resource_reservation": "atomic-all-or-none",
            "capacity_wait_consumes_execution_slot": False,
            "provider_capacity_enforcement": "hard",
            "terminal_drain_required": True,
            "within_class_agent_order": "round-robin",
            "seeded_tie_break_only": True,
        }
        if policies.get("common_rules") != expected_common:
            self.error("policies.json: common scheduling rules changed")
        candidates = policies.get("candidates", [])
        ids = [candidate.get("id") for candidate in candidates if isinstance(candidate, dict)]
        if ids != EXPECTED_CANDIDATE_IDS:
            self.error(f"policies.json: candidate order/set must be {EXPECTED_CANDIDATE_IDS}")
        if candidates != EXPECTED_POLICY_CANDIDATES:
            self.error("policies.json: frozen candidate definitions changed")
        negative = [candidate.get("id") for candidate in candidates if candidate.get("negative_control") is True]
        comparators = [candidate.get("id") for candidate in candidates if candidate.get("throughput_comparator") is True]
        if negative != ["independent-unguarded-negative-control"]:
            self.error("policies.json: only unguarded independent mode may be the negative control")
        if comparators != ["independent-provider-guard"]:
            self.error("policies.json: safe independent provider guard must be the sole throughput comparator")
        weighted = next((candidate for candidate in candidates if candidate.get("id") == "shared-weighted-aging"), {})
        if (weighted.get("interactive_weight"), weighted.get("background_weight"), weighted.get("age_promotion_ticks")) != (3, 1, 36):
            self.error("policies.json: weighted-aging parameters must remain 3:1 with promotion at 36 ticks")

    def verify_thresholds(self) -> None:
        thresholds = self.load_json("thresholds.json")
        expected_sections = {"format_version", "experiment_id", "statistics", *EXPECTED_THRESHOLDS.keys()}
        self.exact_keys(thresholds, expected_sections, "thresholds.json")
        if thresholds.get("format_version") != "e05-thresholds-v1-experimental":
            self.error("thresholds.json: format_version must remain experimental v1")
        if thresholds.get("experiment_id") != "E05":
            self.error("thresholds.json: experiment_id must be E05")
        for section, expected in EXPECTED_THRESHOLDS.items():
            if thresholds.get(section) != expected:
                self.error(f"thresholds.json: frozen {section} thresholds changed")

    def verify_decision_matrix(self) -> None:
        matrix = self.load_json("decision-matrix.json")
        self.exact_keys(
            matrix,
            {"format_version", "experiment_id", "selected_branch", "no_post_result_threshold_relaxation", "precedence"},
            "decision-matrix.json",
        )
        if matrix.get("format_version") != "e05-decision-matrix-v1-experimental":
            self.error("decision-matrix.json: format_version must remain experimental v1")
        if matrix.get("selected_branch") is not None:
            self.error("decision-matrix.json: selected_branch must remain null in Phase A")
        if matrix.get("no_post_result_threshold_relaxation") is not True:
            self.error("decision-matrix.json: post-result threshold relaxation must remain forbidden")
        precedence = matrix.get("precedence", [])
        orders = [entry.get("order") for entry in precedence if isinstance(entry, dict)]
        branches = [entry.get("branch") for entry in precedence if isinstance(entry, dict)]
        if orders != list(range(1, 7)):
            self.error("decision-matrix.json: precedence orders must be 1 through 6")
        if branches != EXPECTED_BRANCHES:
            self.error(f"decision-matrix.json: branch precedence must be {EXPECTED_BRANCHES}")
        valid_refs = set(EXPECTED_THRESHOLDS)
        for index, entry in enumerate(precedence):
            if not isinstance(entry, dict):
                self.error(f"decision-matrix.json: precedence[{index}] must be an object")
                continue
            self.exact_keys(entry, {"order", "branch", "when", "threshold_refs"}, f"decision-matrix.json precedence[{index}]")
            refs = entry.get("threshold_refs", [])
            unknown = sorted(set(refs) - valid_refs) if isinstance(refs, list) else ["non-list"]
            if unknown:
                self.error(f"decision-matrix.json: precedence[{index}] has unknown threshold refs {unknown}")
            branch = entry.get("branch")
            if branch in EXPECTED_DECISION_REFS and refs != EXPECTED_DECISION_REFS[branch]:
                self.error(f"decision-matrix.json: threshold refs changed for {branch}")

    def verify_fixture_bindings(self) -> None:
        bindings_document = self.load_json("fixture-bindings.json")
        self.exact_keys(bindings_document, {"format_version", "hash_algorithm", "bindings"}, "fixture-bindings.json")
        if bindings_document.get("format_version") != "e05-fixture-bindings-v1-experimental":
            self.error("fixture-bindings.json: format_version must remain experimental v1")
        if bindings_document.get("hash_algorithm") != "sha256":
            self.error("fixture-bindings.json: hash_algorithm must be sha256")
        bindings = bindings_document.get("bindings", [])
        paths = [binding.get("path") for binding in bindings if isinstance(binding, dict)]
        if set(paths) != set(EXPECTED_FIXTURE_DIGESTS) or len(paths) != len(EXPECTED_FIXTURE_DIGESTS):
            self.error("fixture-bindings.json: fixture path set changed")
        for index, binding in enumerate(bindings):
            if not isinstance(binding, dict):
                self.error(f"fixture-bindings.json: bindings[{index}] must be an object")
                continue
            self.exact_keys(binding, {"path", "sha256", "identity"}, f"fixture-bindings.json bindings[{index}]")
            relative = binding.get("path")
            if relative not in EXPECTED_FIXTURE_DIGESTS:
                continue
            expected = EXPECTED_FIXTURE_DIGESTS[relative]
            if binding.get("sha256") != expected:
                self.error(f"fixture-bindings.json: frozen digest changed for {relative}")
            fixture_path = self.repository_root / relative
            if not fixture_path.is_file():
                self.error(f"fixture-bindings.json: live fixture missing: {relative}")
                continue
            actual = sha256(fixture_path)
            if actual != expected:
                self.error(f"fixture-bindings.json: live fixture digest mismatch for {relative}: want {expected}, got {actual}")
            self.verify_fixture_identity(relative, fixture_path, binding.get("identity", {}))

    def verify_fixture_identity(self, relative: str, path: Path, identity: Dict[str, Any]) -> None:
        if relative.endswith(".json"):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self.error(f"fixture-bindings.json: cannot inspect {relative}: {exc}")
                return
            for key in ["fixture_id", "version", "scenario"]:
                if key in identity and document.get(key) != identity[key]:
                    self.error(f"fixture-bindings.json: {relative} identity {key} mismatch")
            return
        text = path.read_text(encoding="utf-8")
        if relative.endswith("manifest.yaml"):
            for key in ["fixture_id", "version"]:
                match = re.search(rf"^{re.escape(key)}:\s*([^\s]+)\s*$", text, re.MULTILINE)
                if not match or match.group(1) != identity.get(key):
                    self.error(f"fixture-bindings.json: {relative} identity {key} mismatch")
            return
        constant = identity.get("constant")
        version = identity.get("version")
        pattern = rf'const\s+{re.escape(str(constant))}\s*=\s*"{re.escape(str(version))}"'
        if not re.search(pattern, text):
            self.error(f"fixture-bindings.json: {relative} constant/version mismatch")

    def run(self) -> int:
        self.verify_phase_boundary()
        self.verify_frozen_artifacts()
        self.verify_contract()
        self.verify_workload()
        self.verify_policies()
        self.verify_thresholds()
        self.verify_decision_matrix()
        self.verify_fixture_bindings()
        if self.errors:
            for message in sorted(set(self.errors)):
                print(f"ERROR: {message}", file=sys.stderr)
            return 1
        print("E05 Phase A contract verified: frozen inputs, thresholds, bindings, and boundary are valid.")
        return 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    script = Path(__file__).resolve()
    default_experiment = script.parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-root", type=Path, default=default_experiment)
    parser.add_argument("--repository-root", type=Path, default=default_experiment.parents[1])
    return parser.parse_args(argv)


def main(argv: Sequence[str] = ()) -> int:
    args = parse_args(argv)
    return ContractVerifier(args.experiment_root, args.repository_root).run()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
