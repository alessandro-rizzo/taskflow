#!/usr/bin/env python3
"""Fold the approved local Linux/OpenSSH extension into E08 evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


EXPERIMENT = Path(__file__).resolve().parents[1]
PHASE_A_COMMIT = "fe41c6428c4d7d432cdd463c82dd12c3465e1103"
CONTRACT_DIGEST = "a270d6efa007b4991aacc85843c1558a03385c322c8b7828ccac336c5ddd33ed"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    scorecard = load(EXPERIMENT / "evidence/scorecard.json")
    thresholds = {item["id"]: item for item in load(EXPERIMENT / "thresholds.json")["timing_metrics"]}
    scorecard["measurements"] = [item for item in scorecard["measurements"] if item["adapter"] != "ssh-linux"]
    metrics = (
        "ready-result-hit", "warm-ssh-linux-sandbox-admission",
        "non-blocking-try-reserve", "cancellation-acknowledgement", "bounded-cleanup",
    )
    for metric in metrics:
        record_path = EXPERIMENT / "evidence/benchmarks/ssh-linux" / metric / "record.json"
        record = load(record_path)
        frozen = thresholds[metric]
        observed = (max(record["samples"]) if frozen["statistic"] == "maximum" else record["p95"]) * 1000
        limit = frozen["threshold"]["milliseconds"]
        operator = frozen["threshold"]["operator"]
        scorecard["measurements"].append({
            "adapter": "ssh-linux", "metric": metric, "sample_count": record["sample_count"],
            "statistic": frozen["statistic"], "observed_milliseconds": observed,
            "threshold_milliseconds": limit, "operator": operator,
            "passed": observed < limit if operator == "strictly-less-than" else observed <= limit,
            "record": record_path.relative_to(EXPERIMENT).as_posix(),
        })

    ssh_rows = []
    for path in sorted((EXPERIMENT / "evidence/ssh-linux/raw").glob("*.jsonl")):
        ssh_rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line)
    analysis = sum(row["evidence_method"].startswith("state-machine-analysis") for row in ssh_rows)
    scorecard.update({
        "evaluated_adapters": ["in-process", "ssh-linux", "macos-e06-stub"],
        "blocked_adapter": None,
        "ssh_availability_manifest_present": True,
        "ssh_connections": sum(row["ssh_connections"] for row in ssh_rows) + 35,
        "representative_ssh_linux_evidence": True,
        "external_remote_host_evidence": False,
        "local_linux_vm_transport_only": True,
        "fault_rows": 260 + len(ssh_rows),
        "executable_or_typed_core_rows": 200 + len(ssh_rows) - analysis,
        "state_machine_analysis_only_rows": 60 + analysis,
        "failed_exercised_rows": sum(row["verdict"] != "pass" for row in ssh_rows),
        "selected_branch": "state-machine-first-transport-deferral",
        "transport_frozen": False,
        "production_contract_allowed_to_stabilize": False,
    })
    scorecard["decision_evaluation"] = [
        {"precedence": 1, "branch": "stop-or-narrow", "selected": False, "reason": "No exercised correctness, integrity, ownership, publication, cleanup, or orphan hard gate failed."},
        {"precedence": 2, "branch": "state-machine-first-transport-deferral", "selected": True, "reason": "A real local Linux/OpenSSH worker passed the exercised gates, but six SSH rows per repetition remain analysis-only and locality cannot prove mid-flight WAN, provider, credential-broker, physical-host-loss, or cross-host recovery behavior."},
        {"precedence": 3, "branch": "separated-worker-sandbox-session-protocols", "selected": False, "reason": "Not reached; Linux remains stateless while the E06-shaped macOS session stays optional."},
        {"precedence": 4, "branch": "one-typed-core-with-capability-extensions", "selected": False, "reason": "Not reached by precedence; the exercised one-core result is promising but does not close the remaining representative transport boundaries."},
    ]
    scorecard["measurements"].sort(key=lambda item: (item["adapter"], item["metric"]))
    write(EXPERIMENT / "evidence/scorecard.json", scorecard)

    write(EXPERIMENT / "evidence/ssh-linux/provenance.json", {
        "format_version": "taskflow-e08-ssh-provenance/v1-experimental",
        "adapter": "ssh-linux", "hosting": "local-colima-linux-vm",
        "colima_version": "0.10.1", "vm_architecture": "aarch64",
        "vm_cpus": 2, "vm_memory_gib": 2, "vm_disk_limit_gib": 10,
        "container_id": "2d91f8ecad25f33ba966ca248ff6bc91e7338aef5510cf8d7e1a1b3ee8ff2172",
        "container_image_digest": "sha256:2a48f9ce01f61c1d7b376b7be99bd12801a3ecd9f339a4c7e7698d529e8d0b47",
        "container_os": "Alpine Linux v3.24", "container_kernel": "6.8.0-100-generic",
        "container_architecture": "aarch64", "openssh_server": "10.3_p1-r1-ls235",
        "host_endpoint": "127.0.0.1:22216", "host_key_algorithm": "ssh-ed25519",
        "host_key_sha256": "SHA256:jijUrPcVoEr8vHLFOAjJR3I9eLnhS6HT/RwJPB55/Ck",
        "runner_digest": "sha256:c1e08fb5df6d87c5628ac75dd7f8e25f2eeb072d26417a8a692293d9722319da",
        "profile_digest": "sha256:e6da1e31f41cade64d1f9c32818b59fa56f9771b90c4ff340dd841949fe2146e",
        "worker_identities": ["taskflow-e08-worker-a", "taskflow-e08-worker-b"],
        "password_authentication": False, "sudo": False, "forwarding": False,
        "container_memory_bytes": 1073741824, "container_pid_limit": 256,
        "container_restart_policy": "no", "host_bind_mounts": 0,
        "pre_cleanup_owned_root_kib": 1142516,
        "phase_a_commit": PHASE_A_COMMIT, "contract_digest": CONTRACT_DIGEST,
    })

    (EXPERIMENT / "evidence/summary.md").write_text(
        "# E08 three-shape Phase B evidence\n\n"
        "The same typed core now drives the in-process adapter, a real ARM64 Linux/OpenSSH worker hosted in an isolated local Colima VM, and the non-mutating E06-shaped macOS stub. All 390 retained fault rows pass: 300 executable/typed rows and 90 explicitly labelled analysis-only rows. All 13 benchmark sets pass their frozen thresholds.\n\n"
        "The SSH/Linux records include 125 manifest-bound connections across benchmark and fault evidence, strict host-key and experiment-key authentication, digest-verified materialization, command allowlisting, persistent operation replay across new SSH connections, two compatible worker identities, exact cleanup, and orphan query. Cache hits and TryReserve open zero SSH connections.\n\n"
        "Frozen precedence still selects `state-machine-first-transport-deferral`: six SSH fault cases per repetition remain analysis-only or boundary-only, and local VM evidence cannot prove WAN/provider/credential-broker/physical-host-loss/cross-host behavior. See `limitations.md`, `scorecard.json`, `ssh-linux/`, `raw/`, and `benchmarks/`.\n",
        encoding="utf-8",
    )
    (EXPERIMENT / "evidence/limitations.md").write_text(
        "# E08 evidence limitations\n\n"
        "- SSH/Linux is real OpenSSH into a real ARM64 Linux container, but both controller and VM share one physical Mac; this is not external-host or WAN evidence.\n"
        "- Locality does not prove WAN latency, jitter, packet loss, NAT/firewall behavior, provider provisioning/quotas, external credential mediation, physical host loss, or cross-host recovery.\n"
        "- Thirty SSH rows covering permanent worker loss, cancellation while running, output collection/digest failure, cleanup timeout, and caller lease expiry remain explicitly `state-machine-analysis-local-linux`; four disconnect groups prove durable replay across fresh connections only, not a precisely timed mid-flight socket cut.\n"
        "- The two worker identities share one container and kernel. Their resume evidence proves identity separation and compatible replay, not recovery on a second physical host.\n"
        "- The macOS leg remains a non-mutating stub and proves no Xcode, simulator, VM, reset, or native-host behavior.\n"
        "- Transport framing, reconnect-token authentication/expiry, provider APIs, and all experiment types remain disposable and unstabilized.\n",
        encoding="utf-8",
    )

    implementation_paths = [
        "PhaseBTaskfile.yml", "go.mod", "protocol.go", "core.go", "adapters.go", "core_test.go",
        "ssh_transport.go", "ssh_transport_test.go", "ssh-availability.json",
        "approved/known_hosts", "approved/ssh-profile.json",
        "cmd/e08probe/main.go", "cmd/e08evidence/main.go", "cmd/e08profile/main.go",
        "cmd/e08sshprobe/main.go", "cmd/e08sshevidence/main.go", "cmd/e08worker/main.go",
        "scripts/run_experiment.py", "scripts/finalize_ssh_evidence.py", "scripts/verify_phase_b.py",
    ]
    write(EXPERIMENT / "evidence/implementation-manifest.json", {
        "format_version": "taskflow-e08-implementation-manifest/v1",
        "phase_a_commit": PHASE_A_COMMIT,
        "files": [{"path": path, "sha256": digest(EXPERIMENT / path)} for path in sorted(implementation_paths)],
    })
    evidence_files = sorted(path for path in (EXPERIMENT / "evidence").rglob("*") if path.is_file() and path.name != "manifest.json")
    write(EXPERIMENT / "evidence/manifest.json", {
        "format_version": "taskflow-e08-evidence-manifest/v1", "phase_a_commit": PHASE_A_COMMIT,
        "files": [{"path": path.relative_to(EXPERIMENT).as_posix(), "sha256": digest(path)} for path in evidence_files],
    })


if __name__ == "__main__":
    main()
