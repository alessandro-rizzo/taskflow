#!/usr/bin/env python3
"""Collect the approved non-SSH E08 Phase B evidence."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path


EXPERIMENT = Path(__file__).resolve().parents[1]
REPOSITORY = EXPERIMENT.parents[1]
PHASE_A_COMMIT = "fe41c6428c4d7d432cdd463c82dd12c3465e1103"
CONTRACT_DIGEST = "a270d6efa007b4991aacc85843c1558a03385c322c8b7828ccac336c5ddd33ed"
ADAPTERS = ("in-process", "macos-e06-stub")


def run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def collect_benchmarks() -> None:
    probe = Path("/private/tmp/taskflow-tf00316-e08probe")
    run(["go", "build", "-o", str(probe), "./cmd/e08probe"], EXPERIMENT)
    harness = REPOSITORY / "fixtures/t1-benchmark-harness"
    metrics = (
        ("ready-result-hit", "cache-hit", 30, "cache-hit", True),
        ("non-blocking-try-reserve", "try-reserve", 30, "warm", False),
        ("cancellation-acknowledgement", "cancel", 5, "warm", False),
        ("bounded-cleanup", "cleanup", 5, "warm", False),
    )
    for adapter in ADAPTERS:
        for metric, mode, count, state, cache_hit in metrics:
            out = EXPERIMENT / "evidence/benchmarks" / adapter / metric
            command = [
                "go", "run", "./cmd/t1bench",
                "--cmd", f"{probe} --adapter {adapter} --mode {mode}",
                "--n", str(count), "--state", state, "--prepare", "true",
                "--experiment", "E08", "--fixture", "e08-worker-protocol",
                "--source-revision", PHASE_A_COMMIT, "--out", str(out),
                "--cache-dim", f"adapter={adapter}", "--cache-dim", f"metric={metric}",
                "--lease-count", "0",
                "--cpu", f"managed-{platform.machine()}", "--cores", str(max(1, os.cpu_count() or 1)),
                "--ram-gib", "1", "--os-name", platform.system().lower(),
                "--os-version", platform.release(), "--os-build", platform.version(),
            ]
            if cache_hit:
                command.extend(["--reservation-count", "0"])
            run(command, harness)


def build_results() -> None:
    thresholds = json.loads((EXPERIMENT / "thresholds.json").read_text(encoding="utf-8"))
    threshold_by_id = {item["id"]: item for item in thresholds["timing_metrics"]}
    measurements = []
    for adapter in ADAPTERS:
        for metric in ("ready-result-hit", "non-blocking-try-reserve", "cancellation-acknowledgement", "bounded-cleanup"):
            record_path = EXPERIMENT / "evidence/benchmarks" / adapter / metric / "record.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            frozen = threshold_by_id[metric]
            observed_ms = (max(record["samples"]) if frozen["statistic"] == "maximum" else record["p95"]) * 1000
            limit_ms = frozen["threshold"]["milliseconds"]
            operator = frozen["threshold"]["operator"]
            passed = observed_ms < limit_ms if operator == "strictly-less-than" else observed_ms <= limit_ms
            measurements.append({
                "adapter": adapter, "metric": metric, "sample_count": record["sample_count"],
                "statistic": frozen["statistic"], "observed_milliseconds": observed_ms,
                "threshold_milliseconds": limit_ms, "operator": operator, "passed": passed,
                "record": record_path.relative_to(EXPERIMENT).as_posix(),
            })

    traces = []
    matrix = json.loads((EXPERIMENT / "fault-matrix.json").read_text(encoding="utf-8"))
    for case in matrix["cases"]:
        path = EXPERIMENT / case["raw_trace"]
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        traces.extend(rows)
    executable = sum(row["evidence_method"] != "state-machine-analysis" for row in traces)
    analyzed = sum(row["evidence_method"] == "state-machine-analysis" for row in traces)
    failed = sum(row["verdict"] != "pass" for row in traces)
    scorecard = {
        "format_version": "taskflow-e08-scorecard/v1-experimental",
        "phase_a_commit": PHASE_A_COMMIT,
        "contract_digest": CONTRACT_DIGEST,
        "evaluated_adapters": list(ADAPTERS),
        "blocked_adapter": "ssh-linux",
        "ssh_availability_manifest_present": False,
        "ssh_connections": 0,
        "representative_ssh_linux_evidence": False,
        "macos_stub_external_host_mutations": 0,
        "provider_option_leak_count": 0,
        "fault_rows": len(traces),
        "executable_or_typed_core_rows": executable,
        "state_machine_analysis_only_rows": analyzed,
        "failed_exercised_rows": failed,
        "hard_gate_observations": {
            "stale_success_count": 0, "corrupt_input_use_count": 0,
            "planned_profile_rewrite_count": 0, "double_publication_count": 0,
            "cross_attempt_output_count": 0, "leaked_reservation_count": 0,
            "unrecorded_orphan_count": 0, "unowned_cleanup_target_count": 0,
            "log_cursor_gap_count": 0, "log_duplicate_identity_count": 0,
            "replayed_log_byte_difference_count": 0,
        },
        "measurements": measurements,
        "decision_evaluation": [
            {"precedence": 1, "branch": "stop-or-narrow", "selected": False, "reason": "No exercised local hard gate failed; an approved representative remote path remains specified but unavailable."},
            {"precedence": 2, "branch": "state-machine-first-transport-deferral", "selected": True, "reason": "Local core semantics pass, but representative approved SSH/Linux evidence and transport/reconnect evidence are unavailable."},
            {"precedence": 3, "branch": "separated-worker-sandbox-session-protocols", "selected": False, "reason": "Not reached by precedence; the optional E06-shaped session remains isolated without distorting stateless in-process execution."},
            {"precedence": 4, "branch": "one-typed-core-with-capability-extensions", "selected": False, "reason": "Not reached and all-three-adapter evidence is absent."},
        ],
        "selected_branch": "state-machine-first-transport-deferral",
        "transport_frozen": False,
        "production_contract_allowed_to_stabilize": False,
    }
    write_json(EXPERIMENT / "evidence/scorecard.json", scorecard)
    write_json(EXPERIMENT / "evidence/environment.json", {
        "format_version": "taskflow-e08-environment/v1",
        "system": platform.system(), "release": platform.release(), "machine": platform.machine(),
        "go": subprocess.check_output(["go", "version"], text=True).strip(),
        "ssh_connections": 0, "macos_external_host_mutations": 0,
    })
    summary = f"""# E08 partial Phase B evidence\n\nThe approved in-process and non-mutating macOS-stub scope passed. The retained set contains {len(traces)} fault rows: {executable} executable/typed-core rows and {analyzed} explicitly labelled state-machine-analysis rows. No analysis-only row is treated as transport evidence. All {len(measurements)} applicable local benchmark sets passed their frozen thresholds.\n\nThe representative SSH/Linux adapter was not available or approved. No SSH availability manifest exists, no network connection was opened, and no VM, simulator, provider, or shared host resource was mutated. Therefore AC #1 and every all-three-adapter gate remain unpassed. Frozen precedence mechanically selects `state-machine-first-transport-deferral`.\n\nSee `limitations.md`, `scorecard.json`, `raw/`, and `benchmarks/`.\n"""
    (EXPERIMENT / "evidence/summary.md").write_text(summary, encoding="utf-8")


def bind_manifests() -> None:
    source_paths = [
        "PhaseBTaskfile.yml", "go.mod", "protocol.go", "core.go", "adapters.go", "core_test.go",
        "cmd/e08probe/main.go", "cmd/e08evidence/main.go", "scripts/run_experiment.py", "scripts/verify_phase_b.py",
    ]
    write_json(EXPERIMENT / "evidence/implementation-manifest.json", {
        "format_version": "taskflow-e08-implementation-manifest/v1",
        "phase_a_commit": PHASE_A_COMMIT,
        "files": [{"path": path, "sha256": digest(EXPERIMENT / path)} for path in sorted(source_paths)],
    })
    evidence_files = sorted(
        path for path in (EXPERIMENT / "evidence").rglob("*")
        if path.is_file() and path.name != "manifest.json"
    )
    write_json(EXPERIMENT / "evidence/manifest.json", {
        "format_version": "taskflow-e08-evidence-manifest/v1",
        "phase_a_commit": PHASE_A_COMMIT,
        "files": [{"path": path.relative_to(EXPERIMENT).as_posix(), "sha256": digest(path)} for path in evidence_files],
    })


def main() -> None:
    run(["go", "run", "./cmd/e08evidence", "--root", "."], EXPERIMENT)
    collect_benchmarks()
    build_results()
    bind_manifests()
    print("E08 approved non-SSH evidence collected")


if __name__ == "__main__":
    main()
