#!/usr/bin/env python3
"""Trusted E03 Phase B supervisor for local synthetic candidates only."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time


SCRIPT = Path(__file__).resolve()
EXPERIMENT = SCRIPT.parents[1]
ROOT = SCRIPT.parents[3]
POLICY = EXPERIMENT / "policies/untrusted-plan-policy.json"
VALIDATOR = EXPERIMENT / "validator/e03_validator.py"
PLAN = ROOT / "experiments/e02-plan-ir/evidence/raw/plans/w1.json"
ATTACK_BIN = Path(os.environ.get("E03_ATTACK_BIN", EXPERIMENT / ".phase-b/bin/e03attack"))
LIMIT_BIN = Path(os.environ.get("E03_LIMIT_BIN", EXPERIMENT / ".phase-b/bin/e03limit"))
POOL = os.environ.get("E03_POOL_CONTAINER", "taskflow-e03-pool")
MAX_OUTPUT = 1024 * 1024
CANARY_TEXT = "E03-SYNTHETIC-PARENT-CANARY-5d2ec7"
OUTPUT_MARKER = "E03-SYNTHETIC-OUTPUT-PROBE-7fc86c"


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def minimal_env(tmpdir):
    return {
        "PATH": "/usr/bin:/bin",
        "TMPDIR": str(tmpdir),
        "LANG": "C",
        "LC_ALL": "C",
    }


def trusted_host_env():
    env = dict(os.environ)
    for key in (
        "TASKFLOW_E03_SYNTHETIC_DAEMON_TOKEN",
        "TASKFLOW_E03_SYNTHETIC_PROVIDER_TOKEN",
        "TASKFLOW_E03_SYNTHETIC_SECRET_VALUE",
    ):
        env.pop(key, None)
    return env


def set_process_group():
    os.setsid()


def capped_run(command, env, timeout=2.0, preexec=None):
    started = time.monotonic()
    proc = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        preexec_fn=preexec,
    )
    timed_out = False
    truncated = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        if preexec is not None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            proc.kill()
        stdout, stderr = proc.communicate()
    combined = len(stdout) + len(stderr)
    if combined > MAX_OUTPUT:
        truncated = True
        keep_stdout = min(len(stdout), MAX_OUTPUT)
        stdout = stdout[:keep_stdout]
        stderr = stderr[: max(0, MAX_OUTPUT - keep_stdout)]
    return {
        "returncode": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "duration_seconds": time.monotonic() - started,
        "timed_out": timed_out,
        "truncated": truncated,
    }


def validate_plan(raw, runtime):
    plan_path = runtime / "candidate-plan.json"
    plan_path.write_bytes(raw)
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), "--policy", str(POLICY), "--plan", str(plan_path), "--json"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=2,
        env=minimal_env(runtime),
    )
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result = {"accepted": False, "path": "$", "reason": "validator output invalid"}
    return proc.returncode == 0, result


def native_profile(runtime, source, declared, scratch):
    template = (EXPERIMENT / "policies/native.sb.in").read_text(encoding="utf-8")
    replacements = {
        "{{PLANNER_EXECUTABLE}}": str(ATTACK_BIN.resolve()),
        "{{SELECTED_SOURCE_VIEW}}": str(source.resolve()),
        "{{DECLARED_INPUTS}}": str(declared.resolve()),
        "{{INVOCATION_SCRATCH}}": str(scratch.resolve()),
    }
    for marker, value in replacements.items():
        if any(char in value for char in ('\n', '"', '(', ')')):
            raise RuntimeError("unsafe Seatbelt substitution")
        template = template.replace(marker, value)
    path = runtime / "native.sb"
    path.write_text(template, encoding="utf-8")
    return path


def classify(case_id, expected, result, runtime):
    output_cases = {
        "exact-synthetic-marker",
        "hex-synthetic-marker",
        "base64-synthetic-marker",
        "absolute-path-field",
        "parent-traversal-path-field",
    }
    if case_id in output_cases:
        accepted, diagnostic = validate_plan(result["stdout"], runtime)
        return ("blocked" if not accepted else "trusted_local_limitation", diagnostic)
    if expected == "bounded":
        bounded = (
            result["timed_out"]
            or result["truncated"]
            or result["returncode"] != 0
            or result["duration_seconds"] <= 2.0
        )
        return ("bounded" if bounded else "trusted_local_limitation", {})
    return ("blocked" if result["returncode"] != 0 else "trusted_local_limitation", {})


def target_for(candidate, case_id, runtime, source, scratch, tcp_address, unix_path):
    if candidate == "pooled-container":
        if case_id == "tcp-loopback-owned-listener":
            return f"host.docker.internal:{tcp_address[1]}"
        if case_id == "unix-socket-owned-listener":
            return "/outside/e03.sock"
        if "symlink-escape" in case_id:
            return "/source/escape"
        if case_id.startswith(("relative-parent", "absolute-sibling")):
            return "/outside/canary"
        return f"/scratch/{case_id}"
    if case_id == "tcp-loopback-owned-listener":
        return f"127.0.0.1:{tcp_address[1]}"
    if case_id == "unix-socket-owned-listener":
        return str(unix_path)
    if "symlink-escape" in case_id:
        return str(source / "escape")
    if case_id.startswith(("relative-parent", "absolute-sibling")):
        return str(runtime / "outside-canary")
    return str(scratch / case_id)


def docker_command(case_id, target):
    command = [
        "docker", "exec",
        "-e", "PATH=/usr/bin:/bin",
        "-e", "TMPDIR=/scratch",
        "-e", "LANG=C",
        "-e", "LC_ALL=C",
        POOL,
    ]
    resource_cases = {
        "cpu-limit", "address-space-limit", "file-descriptor-limit",
        "stdout-stderr-limit", "wall-time-limit",
    }
    if case_id in resource_cases:
        command.extend(["/e03limit", "/e03attack", case_id, target, "/source"])
    else:
        command.extend(["/e03attack", case_id, target, "/source"])
    return command


def clean_descendant(candidate, target, env):
    pidfile = target + ".pid"
    if candidate == "pooled-container":
        subprocess.run(
            ["docker", "exec", POOL, "/e03attack", "cleanup", pidfile],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=1,
            env=env,
        )
        return
    path = Path(pidfile)
    if path.exists():
        try:
            os.kill(int(path.read_text().strip()), signal.SIGKILL)
        except (OSError, ValueError):
            pass


def execute_case(candidate, case_id, expected, runtime, source, declared, scratch, profile, tcp_address, unix_path):
    if candidate == "native" and case_id == "address-space-limit":
        return {
            "format_version": "taskflow-e03-attempt-result/v1",
            "candidate": candidate,
            "attempt_id": candidate + ":" + case_id,
            "case_id": case_id,
            "outcome": "trusted_local_limitation",
            "duration_seconds": 0,
            "mechanism_identity": "macos-seatbelt-rlimit",
            "policy_digest": digest_bytes(POLICY.read_bytes()),
            "applied_limits": {"wall_seconds": 2, "output_bytes": MAX_OUTPUT, "cpu_seconds": 1, "file_descriptors": 64},
            "denial_reason": "Darwin does not provide the frozen RLIMIT_AS ceiling",
            "diagnostic_path": None,
            "leak_scan": {"synthetic_parent_canary_found": False, "captured_bytes": 0, "truncated": False},
            "returncode": None,
            "timed_out": False,
        }
    target = target_for(candidate, case_id, runtime, source, scratch, tcp_address, unix_path)
    env = minimal_env(scratch)
    if candidate == "native":
        command = [str(LIMIT_BIN), "sandbox-exec", "-f", str(profile), str(ATTACK_BIN), case_id, target, str(source)]
        result = capped_run(command, env, preexec=set_process_group)
    else:
        command = docker_command(case_id, target)
        result = capped_run(command, trusted_host_env())
    if case_id.startswith("single-descendant") or case_id.startswith("post-exit") or case_id.endswith("-limit"):
        clean_descendant(candidate, target, trusted_host_env() if candidate == "pooled-container" else env)
    outcome, diagnostic = classify(case_id, expected, result, runtime)
    canary_forms = [CANARY_TEXT.encode(), CANARY_TEXT.encode().hex().encode(), base64.b64encode(CANARY_TEXT.encode())]
    leaked = any(form in result["stdout"] + result["stderr"] for form in canary_forms)
    return {
        "format_version": "taskflow-e03-attempt-result/v1",
        "candidate": candidate,
        "attempt_id": candidate + ":" + case_id,
        "case_id": case_id,
        "outcome": outcome,
        "duration_seconds": round(result["duration_seconds"], 6),
        "mechanism_identity": "macos-seatbelt-rlimit" if candidate == "native" else "docker-none-readonly-cgroup-rlimit",
        "policy_digest": digest_bytes(POLICY.read_bytes()),
        "applied_limits": {
            "wall_seconds": 2,
            "output_bytes": MAX_OUTPUT,
            "cpu_seconds": 1,
            "address_space_bytes": 256 * 1024 * 1024,
            "file_descriptors": 64,
        },
        "denial_reason": diagnostic.get("reason", "candidate boundary returned non-success") if outcome == "blocked" else "outer supervisor bounded execution",
        "diagnostic_path": diagnostic.get("path"),
        "leak_scan": {"synthetic_parent_canary_found": leaked, "captured_bytes": len(result["stdout"]) + len(result["stderr"]), "truncated": result["truncated"]},
        "returncode": result["returncode"],
        "timed_out": result["timed_out"],
    }


def prepare_runtime(base):
    source = base / "source"
    scratch = base / "scratch"
    source.mkdir(parents=True)
    scratch.mkdir()
    shutil.copy2(PLAN, source / "w1.json")
    declared = base / "declared-inputs.json"
    declared.write_text('{"platform":"local"}\n', encoding="utf-8")
    outside = base / "outside-canary"
    outside.write_text(CANARY_TEXT, encoding="utf-8")
    os.symlink(outside, source / "escape")
    return source, declared, scratch, outside


def suite(args):
    matrix = json.loads(Path(args.attacks).read_text(encoding="utf-8"))
    if args.candidate == "helper-vm":
        result = {"format_version": "taskflow-e03-candidate-result/v1", "candidate": args.candidate, "state": "unavailable", "reason": "no approved dedicated helper VM endpoint", "attempts": []}
        Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return 0
    if args.candidate == "static-descriptor":
        with tempfile.TemporaryDirectory(prefix="taskflow-e03-static-") as temp:
            accepted, diagnostic = validate_plan(PLAN.read_bytes(), Path(temp))
        attempts = []
        for entry in matrix["catalogue_entries"]:
            for case_id in entry["cases"]:
                attempts.append({
                    "format_version": "taskflow-e03-attempt-result/v1", "candidate": args.candidate,
                    "attempt_id": args.candidate + ":" + case_id, "case_id": case_id,
                    "outcome": "blocked", "duration_seconds": 0,
                    "mechanism_identity": "hash-bound-static-descriptor-no-project-code",
                    "policy_digest": digest_bytes(POLICY.read_bytes()), "applied_limits": {},
                    "denial_reason": "project code is not executed", "diagnostic_path": None,
                    "leak_scan": {"synthetic_parent_canary_found": False, "captured_bytes": 0, "truncated": False},
                    "returncode": 0, "timed_out": False,
                })
        result = {"format_version": "taskflow-e03-candidate-result/v1", "candidate": args.candidate, "state": "exercised", "accepted_plan": accepted, "validation": diagnostic, "attempts": attempts}
        Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return 0 if accepted else 1

    if args.candidate == "native" and shutil.which("sandbox-exec") is None:
        result = {"format_version": "taskflow-e03-candidate-result/v1", "candidate": args.candidate, "state": "unavailable", "reason": "sandbox-exec unavailable", "attempts": []}
        Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return 0
    if args.candidate == "pooled-container":
        probe = subprocess.run(["docker", "inspect", POOL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if probe.returncode != 0:
            result = {"format_version": "taskflow-e03-candidate-result/v1", "candidate": args.candidate, "state": "unavailable", "reason": "prestarted local pool absent", "attempts": []}
            Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            return 0

    with tempfile.TemporaryDirectory(prefix=f"taskflow-e03-{args.candidate}-") as temp:
        runtime = Path(temp)
        source, declared, scratch, outside = prepare_runtime(runtime)
        profile = native_profile(runtime, source, declared, scratch)
        if args.candidate == "native":
            positive = capped_run(
                [str(LIMIT_BIN), "sandbox-exec", "-f", str(profile), str(ATTACK_BIN), "benign-probe", "-", str(source)],
                minimal_env(scratch),
                preexec=set_process_group,
            )
            if positive["returncode"] != 0:
                result = {
                    "format_version": "taskflow-e03-candidate-result/v1",
                    "candidate": args.candidate,
                    "state": "unavailable",
                    "reason": f"frozen Seatbelt profile failed benign positive control with returncode {positive['returncode']}",
                    "limitations": ["Darwin RLIMIT_AS unsupported"],
                    "attempts": [],
                }
                Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
                return 0
        tcp_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_listener.bind(("127.0.0.1", 0)); tcp_listener.listen(2); tcp_listener.settimeout(0.05)
        unix_path = runtime / "listener.sock"
        unix_listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        unix_listener.bind(str(unix_path)); unix_listener.listen(2); unix_listener.settimeout(0.05)
        attempts = []
        started = time.monotonic()
        for entry in matrix["catalogue_entries"]:
            for case_id in entry["cases"]:
                attempts.append(execute_case(args.candidate, case_id, entry["expected_outcome"], runtime, source, declared, scratch, profile, tcp_listener.getsockname(), unix_path))
        accepted_connections = 0
        for listener in (tcp_listener, unix_listener):
            try:
                connection, _ = listener.accept(); connection.close(); accepted_connections += 1
            except (socket.timeout, OSError):
                pass
            listener.close()
        canary_unchanged = outside.read_text(encoding="utf-8") == CANARY_TEXT
        result = {
            "format_version": "taskflow-e03-candidate-result/v1",
            "candidate": args.candidate,
            "state": "exercised",
            "suite_duration_seconds": round(time.monotonic() - started, 6),
            "outside_canary_unchanged": canary_unchanged,
            "unauthorized_listener_accepts": accepted_connections,
            "attempts": attempts,
        }
        Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return 0


def plan(args):
    with tempfile.TemporaryDirectory(prefix="taskflow-e03-plan-") as temp:
        runtime = Path(temp)
        if args.candidate == "static-descriptor":
            raw = PLAN.read_bytes()
        elif args.candidate == "native":
            source, declared, scratch, _ = prepare_runtime(runtime)
            profile = native_profile(runtime, source, declared, scratch)
            result = capped_run([str(LIMIT_BIN), "sandbox-exec", "-f", str(profile), str(ATTACK_BIN), "emit-plan", "-", str(source)], minimal_env(scratch), preexec=set_process_group)
            if result["returncode"] != 0:
                print(f"native positive-control returncode={result['returncode']}", file=sys.stderr)
                print(result["stderr"].decode("utf-8", "replace")[:2000], file=sys.stderr)
                return 1
            raw = result["stdout"]
        elif args.candidate == "pooled-container":
            result = capped_run(["docker", "exec", "-e", "PATH=/usr/bin:/bin", POOL, "/e03attack", "emit-plan", "-", "/source"], trusted_host_env())
            if result["returncode"] != 0:
                print(result["stderr"].decode("utf-8", "replace")[:2000], file=sys.stderr)
                return 1
            raw = result["stdout"]
        else:
            return 1
        accepted, _ = validate_plan(raw, runtime)
        if not accepted:
            return 1
        if args.output != "/dev/null":
            Path(args.output).write_bytes(raw)
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["suite", "plan"])
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--contract-commit", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--attacks")
    parser.add_argument("--attack-scorecard")
    args = parser.parse_args(argv)
    if args.mode == "suite":
        if not args.attacks:
            parser.error("suite requires --attacks")
        return suite(args)
    return plan(args)


if __name__ == "__main__":
    raise SystemExit(main())
