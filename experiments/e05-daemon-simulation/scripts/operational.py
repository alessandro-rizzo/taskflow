#!/usr/bin/env python3
"""Measure experiment-local cleanup and quiescent controller proxies."""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def child_lease(database):
    db = sqlite3.connect(database)
    db.execute("CREATE TABLE IF NOT EXISTS leases(id TEXT PRIMARY KEY, expires REAL NOT NULL, active INTEGER NOT NULL)")
    db.execute("INSERT OR REPLACE INTO leases VALUES('lease', ?, 1)", (time.time() + 0.02,))
    db.commit()
    os._exit(74)


def cleanup_samples(directory):
    samples = []
    for index in range(30):
        database = directory / f"disconnect-{index:02d}.sqlite3"
        subprocess.run([sys.executable, __file__, "--child-lease", str(database)], check=False)
        started = time.perf_counter()
        while True:
            with sqlite3.connect(str(database)) as db:
                expiry = db.execute("SELECT expires FROM leases WHERE id='lease'").fetchone()[0]
                if time.time() >= expiry:
                    db.execute("UPDATE leases SET active=0 WHERE id='lease'")
                    break
            time.sleep(0.005)
        samples.append(time.perf_counter() - started)
        database.unlink()
    ordered = sorted(samples)
    return {"samples_seconds": samples, "p95_seconds": ordered[round(.95 * 29)],
            "max_seconds": max(samples), "sample_count": len(samples)}


def idle_controller(sample_file):
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    previous_cpu, previous_wall = time.process_time(), time.perf_counter()
    with Path(sample_file).open("w") as stream:
        for _ in range(30):
            if stopping:
                break
            time.sleep(1)
            current_cpu, current_wall = time.process_time(), time.perf_counter()
            raw_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            rss_mib = raw_rss / (1024 * 1024) if platform.system() == "Darwin" else raw_rss / 1024
            row = {"cpu_percent": 100 * (current_cpu - previous_cpu) / (current_wall - previous_wall),
                   "rss_mib": rss_mib}
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            previous_cpu, previous_wall = current_cpu, current_wall
    while not stopping:
        time.sleep(0.05)


def quiescent_sample():
    with tempfile.TemporaryDirectory(prefix="e05-idle-") as temporary:
        sample_file = Path(temporary) / "samples.jsonl"
        process = subprocess.Popen([sys.executable, __file__, "--idle-controller", str(sample_file)])
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            if sample_file.exists() and len(sample_file.read_text().splitlines()) == 30:
                break
            time.sleep(.05)
        rows = [json.loads(line) for line in sample_file.read_text().splitlines()]
        if len(rows) != 30:
            process.kill()
            raise RuntimeError(f"idle controller produced {len(rows)} of 30 samples")
        cpu, rss = [row["cpu_percent"] for row in rows], [row["rss_mib"] for row in rows]
        stop_started = time.perf_counter()
        process.terminate()
        process.wait(timeout=1)
        stop_seconds = time.perf_counter() - stop_started
    return {"sample_seconds": 30, "cpu_percent": cpu, "rss_mib": rss,
            "idle_cpu_p95_percent": sorted(cpu)[round(.95 * 29)],
            "idle_rss_p95_mib": sorted(rss)[round(.95 * 29)], "clean_stop_seconds": stop_seconds,
            "resident_process_count": 1, "state_directory_count": 1,
            "external_service_count": 0, "manual_pre_run_start_count": 0}


def generate(output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="e05-cleanup-") as temporary:
        cleanup = cleanup_samples(Path(temporary))
    quiescent = quiescent_sample()
    result = {"format_version": "e05-operational-proxy-v1-experimental", "cleanup": cleanup,
              "quiescent_controller": quiescent,
              "limitations": "Python/SQLite simulator proxy; not packaging, launch-agent, RPC, migration, or hardware evidence."}
    (output / "operational-proxy.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--child-lease")
    parser.add_argument("--idle-controller")
    args = parser.parse_args()
    if args.child_lease:
        child_lease(args.child_lease)
    elif args.idle_controller:
        idle_controller(args.idle_controller)
    else:
        print(json.dumps(generate(args.output), sort_keys=True))


if __name__ == "__main__":
    main()
