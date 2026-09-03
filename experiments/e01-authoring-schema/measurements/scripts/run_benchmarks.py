#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys
import time


SCRIPT = Path(__file__).resolve()
MEASUREMENTS = SCRIPT.parents[1]
ROOT = SCRIPT.parents[4]
PROTOCOL_PATH = MEASUREMENTS / "protocol.json"
RESULTS = MEASUREMENTS / "results"
FAILURES = MEASUREMENTS / "failures"
TEMP_ROOT = Path("/tmp/taskflow-e01-tf00307")
BENCHMARK_ROOT = ROOT / "fixtures/t1-benchmark-harness"
BENCHMARK_BINARY = TEMP_ROOT / "harness/t1bench"
PREPARE = "../../measurements/scripts/prepare_state.py"


def output(*command: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(command, cwd=cwd, text=True).strip()


def run_logged(command: list[str], cwd: Path, log: Path) -> None:
    started = time.monotonic()
    completed = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("$ " + shlex.join(command) + "\n" + completed.stdout + f"\nexit_code={completed.returncode}\nelapsed_seconds={time.monotonic() - started:.9f}\n")
    if completed.returncode != 0:
        raise RuntimeError(f"command failed; see {log}")


def build_harness() -> None:
    BENCHMARK_BINARY.parent.mkdir(parents=True, exist_ok=True)
    cache = TEMP_ROOT / "harness/gocache"
    cache.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["GOCACHE"] = str(cache)
    subprocess.run(["go", "build", "-o", str(BENCHMARK_BINARY), "./cmd/t1bench"], cwd=BENCHMARK_ROOT, env=env, check=True)


def metric_command(candidate: str, spec: dict, metric: str) -> tuple[str, str, dict[str, str]]:
    temp = TEMP_ROOT / candidate
    temp.mkdir(parents=True, exist_ok=True)
    if spec["kind"] == "go":
        entrypoint = spec["entrypoint"]
        if metric == "warm-discovery":
            cache = temp / "go-warm-discovery-cache"
            driver = temp / "warm-discovery-driver"
            prepare = f"env GOCACHE={cache} go build -o {driver} {entrypoint} && {driver} discover W1 >/dev/null"
            command = f"{driver} discover W1 >/dev/null"
            dims = {"driver_binary": "prebuilt-each-sample", "gocache": "candidate-isolated-warm", "discovery_cache": "none", "process": "fresh"}
        elif metric == "cold-discovery":
            cache = temp / "go-cold-discovery-build-cache"
            driver = temp / "cold-discovery-driver"
            prepare = f"env GOCACHE={cache} go build -o {driver} {entrypoint}"
            command = f"{driver} discover W1 >/dev/null"
            dims = {"driver_binary": "prebuilt-each-sample", "gocache": "candidate-isolated-warm", "discovery_cache": "none", "process": "fresh-no-preinvoke"}
        elif metric == "cold-driver-build-or-typecheck":
            cache = temp / "go-cold-build-cache"
            driver = temp / "cold-build-driver"
            prepare = f"python3 {PREPARE} --mode go-cold-build --candidate {candidate}"
            command = f"env GOCACHE={cache} go build -o {driver} {entrypoint}"
            dims = {"driver_binary": "absent-before-sample", "gocache": "candidate-isolated-empty-each-sample"}
        elif metric == "warm-driver-build-or-typecheck":
            cache = temp / "go-warm-build-cache"
            driver = temp / "warm-build-driver"
            prepare = f"python3 {PREPARE} --mode go-warm-build --candidate {candidate} --entrypoint {entrypoint}"
            command = f"env GOCACHE={cache} go build -o {driver} {entrypoint}"
            dims = {"driver_binary": "absent-before-sample", "gocache": "candidate-isolated-prewarmed-each-sample"}
        else:
            raise ValueError(metric)
        return prepare, command, dims

    if metric == "warm-discovery":
        cache = temp / "bun-warm-transpiler-cache"
        value = f"env BUN_RUNTIME_TRANSPILER_CACHE_PATH={cache} bun run cli.ts discover W1 >/dev/null"
        return value, value, {"runtime": "bun-fresh-process", "transpiler_cache": "candidate-isolated-prewarmed-each-sample", "package_install": "locked-and-present"}
    if metric == "cold-discovery":
        cache = temp / "bun-cold-transpiler-cache"
        prepare = f"python3 {PREPARE} --mode bun-cold-discovery --candidate {candidate}"
        command = f"env BUN_RUNTIME_TRANSPILER_CACHE_PATH={cache} bun run cli.ts discover W1 >/dev/null"
        return prepare, command, {"runtime": "bun-fresh-process", "transpiler_cache": "candidate-isolated-empty-each-sample", "package_install": "locked-and-present"}
    if metric == "cold-driver-build-or-typecheck":
        prepare = f"python3 {PREPARE} --mode typescript-cold-check --candidate {candidate}"
        command = "env BUN_RUNTIME_TRANSPILER_CACHE_PATH=0 bun run typecheck >/dev/null"
        return prepare, command, {"typescript": "noEmit-nonincremental-fresh-process", "runtime_transpiler_cache": "disabled", "package_install": "locked-and-present"}
    if metric == "warm-driver-build-or-typecheck":
        prepare = f"python3 {PREPARE} --mode typescript-warm-check --candidate {candidate}"
        command = "env BUN_RUNTIME_TRANSPILER_CACHE_PATH=0 bun run typecheck >/dev/null"
        return prepare, command, {"typescript": "noEmit-nonincremental-preinvoked-each-sample", "runtime_transpiler_cache": "disabled", "package_install": "locked-and-present"}
    raise ValueError(metric)


def collect(protocol: dict, candidate: str, metric_spec: dict, phase: str = "primary") -> None:
    spec = protocol["candidates"][candidate]
    metric = metric_spec["id"]
    destination = RESULTS / phase / candidate / metric
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite {destination}")
    candidate_dir = ROOT / spec["directory"]
    prepare, command, dimensions = metric_command(candidate, spec, metric)
    args = [
        str(BENCHMARK_BINARY),
        "--cmd", command,
        "--n", str(metric_spec["samples"]),
        "--state", metric_spec["state"],
        "--prepare", prepare,
        "--experiment", "E01",
        "--fixture", protocol["benchmark_fixture"],
        "--out", str(destination),
        "--source-revision", protocol["candidate_source_revision"],
        "--cpu", "Apple M5 Max",
        "--cores", "18",
        "--ram-gib", "64",
        "--os-name", "darwin",
        "--os-version", "26.5.2",
        "--os-build", "25F84",
        "--os-arch", "arm64",
    ]
    for key, value in sorted(dimensions.items()):
        args += ["--cache-dim", f"{key}={value}"]
    if spec["kind"] == "typescript":
        args += ["--toolchain", f"bun@{output('bun', '--version')}", "--toolchain", "typescript@5.9.3"]
    try:
        run_logged(args, candidate_dir, destination.with_suffix(".log"))
    except Exception as error:
        FAILURES.mkdir(parents=True, exist_ok=True)
        failure = {
            "candidate": candidate,
            "metric": metric,
            "phase": phase,
            "error": str(error),
            "rerun_allowed_only_after_dated_amendment": True,
        }
        (FAILURES / f"{phase}-{candidate}-{metric}.json").write_text(json.dumps(failure, indent=2) + "\n")
        raise


def write_environment(protocol: dict) -> None:
    data = {
        "schema_version": "taskflow-e01-measurement-environment/v1",
        "candidate_source_revision": protocol["candidate_source_revision"],
        "protocol_sha256": hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "go": output("go", "version"),
        "bun": output("bun", "--version"),
        "task": output("task", "--version"),
        "mise": output("mise", "--version"),
        "codex": output("codex", "--version"),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "hardware": {"cpu": "Apple M5 Max", "cores": 18, "ram_gib": 64},
        "os": {"name": "darwin", "version": "26.5.2", "build": "25F84", "arch": "arm64"},
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "environment.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def warm_record(candidate: str, phase: str = "primary") -> dict:
    return json.loads((RESULTS / phase / candidate / "warm-discovery/record.json").read_text())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol-only", action="store_true")
    parser.add_argument("--resume-after-failure", action="store_true")
    args = parser.parse_args()
    subprocess.run([sys.executable, str(MEASUREMENTS / "scripts/verify_protocol.py")], check=True)
    if args.protocol_only:
        return
    if RESULTS.exists() and not args.resume_after_failure:
        raise SystemExit(f"refusing to overwrite existing results: {RESULTS}")
    if args.resume_after_failure:
        failure = FAILURES / "primary-C-warm-discovery.json"
        if not failure.is_file():
            raise SystemExit(f"permitted rerun requires retained failure record: {failure}")
        if list(RESULTS.rglob("record.json")) or list(RESULTS.rglob("samples.txt")):
            raise SystemExit("permitted rerun expected no accepted record or samples from the rejected first set")
    protocol = json.loads(PROTOCOL_PATH.read_text())
    build_harness()
    write_environment(protocol)
    metrics = protocol["metrics"]
    for candidate in protocol["candidate_order"]["primary"]:
        for metric in metrics:
            collect(protocol, candidate, metric)
    budget = protocol["thresholds"]["warm_discovery_p95_seconds_exclusive"]
    margin = protocol["thresholds"]["near_budget_seconds_inclusive"]
    near = [candidate for candidate in protocol["candidate_order"]["primary"] if abs(warm_record(candidate)["p95"] - budget) <= margin]
    reverse_run = bool(near)
    if reverse_run:
        warm_metric = next(item for item in metrics if item["id"] == "warm-discovery")
        for candidate in protocol["candidate_order"]["reverse_if_near_budget"]:
            collect(protocol, candidate, warm_metric, phase="reverse")
    execution = {
        "schema_version": "taskflow-e01-benchmark-execution/v1",
        "primary_order": protocol["candidate_order"]["primary"],
        "near_budget_candidates": near,
        "reverse_run": reverse_run,
        "reverse_order": protocol["candidate_order"]["reverse_if_near_budget"] if reverse_run else [],
        "decision_p95_rule": protocol["candidate_order"]["score_when_repeated"],
    }
    (RESULTS / "execution.json").write_text(json.dumps(execution, indent=2) + "\n")
    print("run-benchmarks: PASS")


if __name__ == "__main__":
    main()
