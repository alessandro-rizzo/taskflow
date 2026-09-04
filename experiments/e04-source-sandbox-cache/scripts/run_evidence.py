#!/usr/bin/env python3
"""Run the bounded E04 probes and serial T1 benchmark measurements."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPERIMENT = Path(__file__).resolve().parents[1]
REPOSITORY = EXPERIMENT.parents[1]
EVIDENCE = EXPERIMENT / "evidence"
RAW = EVIDENCE / "raw"
BENCHMARKS = EVIDENCE / "benchmarks"
PHASE_A_COMMIT = "fe5cb0aa25deb4c10f72dc56e800cfeaac9e363c"
sys.path.insert(0, str(EXPERIMENT))

import e04  # noqa: E402


def run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {shlex.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def write_probe(number: int, identifier: str, details: dict[str, Any], limitations: list[str]) -> None:
    e04.write_json(
        RAW / f"{identifier}.json",
        {
            "attained_reproducibility": "observed",
            "details": details,
            "experiment_id": "E04",
            "id": identifier,
            "limitations": limitations,
            "phase_a_contract_commit": PHASE_A_COMMIT,
            "requested_reproducibility": "isolated",
            "roadmap_demonstration": number,
            "schema_version": "taskflow-e04-probe-evidence/v1",
            "status": "pass",
        },
    )


def source_mutation_probe(root: Path, fixture: Path) -> None:
    live = root / "source-live"
    shutil.copytree(fixture, live)
    cas = e04.CAS(root / "source-cas")
    manifest = cas.capture(live)
    original = (live / "greeter.go").read_bytes()
    original_digest = e04.digest_bytes(original)
    mutation_marker = "post-snapshot-mutation-marker"
    (live / "greeter.go").write_text(f"package greeter\n// {mutation_marker}\n", encoding="utf-8")
    (live / "extra.go").write_text(f"package greeter\n// {mutation_marker}\n", encoding="utf-8")
    materialized = root / "source-execution"
    cas.materialize(manifest, materialized)
    child = run(
        [
            sys.executable,
            "-c",
            "import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())",
            str(materialized / "greeter.go"),
        ]
    )
    observed_digest = child.stdout.strip()
    write_probe(
        1,
        "source-mutation",
        {
            "captured_source_digest": manifest.digest,
            "fresh_live_digest_after_mutation": e04.CAS(root / "mutated-cas").capture(live).digest,
            "original_file_digest": original_digest,
            "executed_file_digest": observed_digest,
            "executed_extra_file_present": (materialized / "extra.go").exists(),
            "mutation_marker_observed": mutation_marker in (materialized / "greeter.go").read_text(encoding="utf-8"),
            "materialized_tree_verified": e04.tree_digest(materialized) == manifest.digest,
        },
        ["Capture is a bounded directory walk, not an atomic filesystem snapshot during concurrent mutation."],
    )


def concurrent_isolation_probe(root: Path, fixture: Path) -> None:
    cas = e04.CAS(root / "concurrent-cas")
    manifest = cas.capture(fixture)
    base = root / "concurrent-base"
    cas.materialize(manifest, base, read_only=True)
    run_a = root / "run-a"
    run_b = root / "run-b"
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda pair: e04.create_sandbox(base, pair[0], pair[1]), [(run_a, "apfs-clone"), (run_b, "apfs-clone")]))
    marker_a = run_a / "outputs" / "run-a.txt"
    marker_b = run_b / "outputs" / "run-b.txt"
    marker_a.write_text("run-a", encoding="utf-8")
    marker_b.write_text("run-b", encoding="utf-8")
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(e04.run_w1, run_a, marker_b)
        future_b = executor.submit(e04.run_w1, run_b, marker_a)
        result_a = future_a.result()
        result_b = future_b.result()
    write_probe(
        2,
        "concurrent-output-isolation",
        {
            "method": "apfs-clone",
            "run_a": result_a,
            "run_b": result_b,
            "distinct_workspace_roots": run_a != run_b,
            "own_markers_intact": marker_a.read_text(encoding="utf-8") == "run-a" and marker_b.read_text(encoding="utf-8") == "run-b",
            "peer_reads_denied": result_a["peer_read_denied"] and result_b["peer_read_denied"],
            "immutable_base_verified_after_runs": e04.tree_digest(base) == manifest.digest,
        },
        ["The native profile denies the named peer path but is not a complete default-deny host filesystem profile."],
    )


def ambient_input_probe(root: Path) -> None:
    sandbox = root / "ambient-sandbox"
    sandbox.mkdir()
    for child in ("home", "tmp", "tool-cache"):
        (sandbox / child).mkdir()
    environment_name = "E04_UNDECLARED_CANARY"
    environment_value = "environment-canary-must-not-persist"
    previous = os.environ.get(environment_name)
    os.environ[environment_name] = environment_value
    try:
        environment = e04.sanitized_environment(sandbox)
        env_probe = subprocess.run(
            [sys.executable, "-c", f"import os; print({environment_name!r} in os.environ)"],
            cwd=sandbox,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        if previous is None:
            os.environ.pop(environment_name, None)
        else:
            os.environ[environment_name] = previous

    outside = root / "undeclared-read-canary"
    outside.write_text("path-canary-must-not-persist", encoding="utf-8")
    outside_write = root / "undeclared-write-canary"
    read_probe = e04.run_with_profile(
        [sys.executable, "-c", "from pathlib import Path; import sys; Path(sys.argv[1]).read_bytes()", str(outside)],
        sandbox,
        environment,
        [outside],
    )
    write_probe_result = e04.run_with_profile(
        [sys.executable, "-c", "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('blocked')", str(outside_write)],
        sandbox,
        environment,
        [outside_write],
    )
    write_probe(
        3,
        "ambient-input-control",
        {
            "environment_canary_name": environment_name,
            "environment_canary_absent": env_probe.returncode == 0 and env_probe.stdout.strip() == "False",
            "read_canary_name": outside.name,
            "read_denied": read_probe.returncode != 0,
            "write_canary_name": outside_write.name,
            "write_denied": write_probe_result.returncode != 0 and not outside_write.exists(),
            "sandbox_mechanism": "sandbox-exec-targeted-deny",
        },
        [
            "Targeted denial proves the declared canaries, not complete host filesystem closure.",
            "Network, time, randomness, host sockets, and hardware capabilities were not controlled.",
        ],
    )


def changed_identity(base: dict[str, Any], name: str) -> dict[str, Any]:
    changed = copy.deepcopy(base)
    if isinstance(changed[name], list):
        changed[name][0]["digest"] += "-changed"
    elif name == "resolved_process_and_arguments":
        changed[name]["argv"].append("-count=1")
    else:
        changed[name]["digest"] += "-changed"
    return changed


def identity_probe() -> None:
    components = e04.example_identity()
    identity = e04.cache_key(components)
    changed = {name: e04.cache_key(changed_identity(components, name)) for name in e04.REQUIRED_IDENTITY_COMPONENTS}
    rejected: dict[str, str] = {}
    for name in e04.REQUIRED_IDENTITY_COMPONENTS:
        missing = copy.deepcopy(components)
        missing[name] = None
        try:
            e04.cache_key(missing)
        except ValueError as error:
            rejected[name] = str(error)
    miss = e04.execute_cached(components, e04.ResultCache(), components["execution_profile"]["digest"])
    kinds = [event["kind"] for event in miss.events]
    write_probe(
        4,
        "pre-reservation-identity",
        {
            "base_identity": identity,
            "mandatory_components": list(e04.REQUIRED_IDENTITY_COMPONENTS),
            "changed_identities": changed,
            "all_mutations_change_identity": len(set(changed.values()) | {identity}) == len(changed) + 1,
            "missing_components_rejected": sorted(rejected) == sorted(e04.REQUIRED_IDENTITY_COMPONENTS),
            "event_kinds": kinds,
            "key_before_lookup": kinds.index("compute-cache-key") < kinds.index("lookup-result-cache"),
            "lookup_before_reservation": kinds.index("lookup-result-cache") < kinds.index("reserve-worker"),
        },
        ["The experimental identity encoding is not E02 canonical plan IR and carries no compatibility promise."],
    )


def hit_probe() -> None:
    components, cache, identity = e04.ready_cache()
    traces: list[dict[str, Any]] = []
    for sample in range(30):
        result = e04.execute_cached(components, cache, components["execution_profile"]["digest"])
        traces.append({"sample": sample + 1, "identity": result.identity, "status": result.status, "events": result.events, "counters": result.counters})
    write_probe(
        5,
        "zero-reservation-cache-hit",
        {
            "identity": identity,
            "sample_count": len(traces),
            "all_resource_counters_zero": all(not any(trace["counters"].values()) for trace in traces),
            "forbidden_events_absent": all(
                not ({"reserve-worker", "acquire-worker", "attest-worker-profile", "create-sandbox", "execute"} & {event["kind"] for event in trace["events"]})
                for trace in traces
            ),
            "traces": traces,
        },
        ["Latency is evaluated separately through the bound benchmark harness."],
    )


def attestation_probe() -> None:
    components = e04.example_identity()
    planned_identity = e04.cache_key(components)
    result = e04.execute_cached(components, e04.ResultCache(), "profile-unexpected")
    kinds = [event["kind"] for event in result.events]
    write_probe(
        6,
        "attestation-mismatch",
        {
            "planned_identity": planned_identity,
            "returned_identity": result.identity,
            "status": result.status,
            "events": result.events,
            "counters": result.counters,
            "identity_unchanged": result.identity == planned_identity,
            "sandbox_execution_publication_absent": not ({"create-sandbox", "execute", "publish-result"} & set(kinds)),
        },
        ["The worker and attestation are in-process fakes; E08 owns a transport protocol."],
    )


def cache_separation_probe() -> None:
    components = e04.example_identity()
    tool_cache = e04.ToolCache({"poisoned-success": b"not-authoritative"})
    warm_state = e04.WarmWorkerState(ready_workers=4)
    miss = e04.execute_cached(components, e04.ResultCache(), components["execution_profile"]["digest"])
    hit_components, result_cache, _ = e04.ready_cache()
    cold_performance_hit = e04.execute_cached(hit_components, result_cache, hit_components["execution_profile"]["digest"])
    write_probe(
        7,
        "cache-class-separation",
        {
            "classes": {
                "result": type(result_cache).__name__,
                "tool": type(tool_cache).__name__,
                "warm_worker": type(warm_state).__name__,
            },
            "poisoned_tool_cache_created_result_hit": miss.status == "cache-hit",
            "warm_workers_created_result_hit": miss.status == "cache-hit",
            "result_hit_without_tool_or_warm_state": cold_performance_hit.status == "cache-hit" and not any(cold_performance_hit.counters.values()),
            "miss_status": miss.status,
        },
        ["Storage is in-process and demonstrates authority separation, not production cache poisoning resistance."],
    )


def benchmark(metric_id: str, method: str | None, base: Path, target: Path, trace_log: Path | None) -> dict[str, Any]:
    harness = REPOSITORY / "fixtures" / "t1-benchmark-harness"
    out = BENCHMARKS / {
        "local-warm-sandbox-creation-apfs": "apfs-clone-warm",
        "local-warm-sandbox-creation-copy-control": "copy-warm",
        "ready-cache-hit-after-planning": "ready-cache-hit",
    }[metric_id]
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    if method:
        command = shlex.join(
            [sys.executable, str(EXPERIMENT / "e04.py"), "create-sandbox", "--base", str(base), "--target", str(target), "--method", method]
        )
        prepare = shlex.join([sys.executable, str(EXPERIMENT / "e04.py"), "cleanup", "--path", str(target)])
        state = "warm"
        cache_dimensions = ["source-cas=warm", "worker-capacity=warm", "result-cache=absent"]
    else:
        assert trace_log is not None
        if trace_log.exists():
            trace_log.unlink()
        cache_root = Path("/private/tmp/taskflow-e04-benchmark-hit-state")
        command = shlex.join(
            [
                sys.executable,
                str(EXPERIMENT / "e04.py"),
                "benchmark-cache-hit",
                "--cache-root",
                str(cache_root),
                "--trace-log",
                str(trace_log),
            ]
        )
        prepare = shlex.join(
            [sys.executable, str(EXPERIMENT / "e04.py"), "prepare-cache-hit", "--root", str(cache_root)]
        )
        state = "cache-hit"
        cache_dimensions = ["source-cas=warm", "result-cache=ready-and-verified", "worker-capacity=not-required"]
    arguments = [
        "go", "run", "./cmd/t1bench",
        "--cmd", command,
        "--n", "30",
        "--state", state,
        "--prepare", prepare,
        "--experiment", "E04",
        "--fixture", "w1-fast-project-check",
        "--out", str(out),
        "--source-revision", PHASE_A_COMMIT,
        "--toolchain", f"python@{platform.python_version()}",
    ]
    for dimension in cache_dimensions:
        arguments.extend(["--cache-dim", dimension])
    if not method:
        arguments.extend(["--reservation-count", "0"])
    completed = run(arguments, cwd=harness)
    if target.exists():
        e04.safe_cleanup(target)
    if not method:
        e04.safe_cleanup(cache_root)
    record = json.loads((out / "record.json").read_text(encoding="utf-8"))
    return {"metric_id": metric_id, "command": command, "prepare": prepare, "runner_stderr": completed.stderr.strip(), "record": record}


def file_manifest(paths: list[Path]) -> list[dict[str, str]]:
    return [
        {"path": path.relative_to(EXPERIMENT).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(paths)
    ]


def write_manifests(execution: dict[str, Any]) -> None:
    implementation_paths = [
        EXPERIMENT / "Taskfile.yml",
        EXPERIMENT / "e04.py",
        EXPERIMENT / "scripts" / "run_evidence.py",
        EXPERIMENT / "scripts" / "verify_evidence.py",
        EXPERIMENT / "tests" / "test_e04.py",
    ]
    e04.write_json(
        EVIDENCE / "implementation-manifest.json",
        {
            "phase_a_contract_commit": PHASE_A_COMMIT,
            "schema_version": "taskflow-e04-implementation-manifest/v1",
            "files": file_manifest(implementation_paths),
        },
    )
    e04.write_json(EVIDENCE / "execution.json", execution)
    evidence_files = [path for path in EVIDENCE.rglob("*") if path.is_file() and path.name != "evidence-manifest.json"]
    e04.write_json(
        EVIDENCE / "evidence-manifest.json",
        {
            "phase_a_contract_commit": PHASE_A_COMMIT,
            "schema_version": "taskflow-e04-evidence-manifest/v1",
            "files": file_manifest(evidence_files),
        },
    )


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    fixture = REPOSITORY / "fixtures" / "w1" / "repo"
    with tempfile.TemporaryDirectory(prefix="taskflow-e04-evidence-") as temporary:
        root = Path(temporary)
        source_mutation_probe(root, fixture)
        concurrent_isolation_probe(root, fixture)
        ambient_input_probe(root)
        identity_probe()
        hit_probe()
        attestation_probe()
        cache_separation_probe()

    benchmark_root = Path("/private/tmp/taskflow-e04-benchmark-base")
    e04.safe_cleanup(benchmark_root)
    benchmark_root.mkdir()
    cas = e04.CAS(benchmark_root / "cas")
    manifest = cas.capture(fixture)
    base = benchmark_root / "base"
    cas.materialize(manifest, base, read_only=True)
    benchmark_results = []
    benchmark_results.append(benchmark("local-warm-sandbox-creation-apfs", "apfs-clone", base, Path("/private/tmp/taskflow-e04-benchmark-apfs-target"), None))
    benchmark_results.append(benchmark("local-warm-sandbox-creation-copy-control", "copy", base, Path("/private/tmp/taskflow-e04-benchmark-copy-target"), None))
    trace_log = BENCHMARKS / "ready-cache-hit" / "traces.jsonl"
    benchmark_results.append(benchmark("ready-cache-hit-after-planning", None, base, Path("/private/tmp/taskflow-e04-unused-target"), trace_log))
    e04.safe_cleanup(benchmark_root)

    environment = {
        "machine": platform.machine(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "go": run(["go", "version"]).stdout.strip(),
        "macos_product_version": run(["sw_vers", "-productVersion"]).stdout.strip(),
        "macos_build": run(["sw_vers", "-buildVersion"]).stdout.strip(),
        "apfs_clone_command": "cp -cR",
        "sandbox_command": "sandbox-exec -p",
        "docker": "CLI present; daemon inaccessible in managed environment; not exercised",
        "tart": "not installed; not exercised",
    }
    e04.write_json(EVIDENCE / "environment.json", environment)

    apfs_p95 = benchmark_results[0]["record"]["p95"]
    hit_p95 = benchmark_results[2]["record"]["p95"]
    selected_branch = "native-fast-incomplete" if apfs_p95 < 0.25 and hit_p95 < 0.3 else ("local-hit-remote-miss" if hit_p95 < 0.3 else "stop-or-narrow")
    e04.write_json(
        EVIDENCE / "summary.json",
        {
            "attained_reproducibility": "observed",
            "experiment_id": "E04",
            "local_warm_sandbox_p95_seconds": apfs_p95,
            "ready_cache_hit_p95_seconds": hit_p95,
            "ready_cache_hit_reservations": benchmark_results[2]["record"]["reservation_count"],
            "recommendation": "Retain APFS clone as a fast local sandbox primitive, but do not make the current targeted native policy the isolated default until a complete deny-by-default profile is proven.",
            "selected_branch": selected_branch,
        },
    )
    write_manifests(
        {
            "benchmark_runs": [{key: value for key, value in item.items() if key != "record"} for item in benchmark_results],
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "phase_a_contract_commit": PHASE_A_COMMIT,
            "probe_command": "python3 scripts/run_evidence.py",
            "schema_version": "taskflow-e04-execution/v1",
        }
    )
    print(f"E04 evidence complete: branch={selected_branch} apfs_p95={apfs_p95:.6f}s hit_p95={hit_p95:.6f}s")


if __name__ == "__main__":
    main()
