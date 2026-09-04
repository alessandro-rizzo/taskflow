#!/usr/bin/env python3
"""Fresh-process SQLite crash/restart matrix for E05."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCHEMA_VERSION = "e05-sqlite-v1-experimental"
PHASES = ("admission", "execution", "cleanup")
TIMINGS = ("before-commit", "after-commit")


def connect(path):
    connection = sqlite3.connect(str(path), timeout=5)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    return connection


def initialize(path, phase):
    with connect(path) as db:
        db.executescript("""
          CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE run_state(id TEXT PRIMARY KEY, state TEXT NOT NULL);
          CREATE TABLE events(sequence INTEGER PRIMARY KEY, phase TEXT NOT NULL, transition TEXT NOT NULL);
          CREATE TABLE resources(provider TEXT PRIMARY KEY, used INTEGER NOT NULL CHECK(used >= 0 AND used <= 1));
          CREATE TABLE cleanup(run_id TEXT PRIMARY KEY, pending INTEGER NOT NULL CHECK(pending IN (0,1)));
        """)
        db.execute("INSERT INTO metadata VALUES('schema_version', ?)", (SCHEMA_VERSION,))
        initial = {"admission": ("submitted", 0, 0), "execution": ("admitted", 1, 0),
                   "cleanup": ("completed", 1, 1)}[phase]
        db.execute("INSERT INTO run_state VALUES('run-1', ?)", (initial[0],))
        db.execute("INSERT INTO resources VALUES('device', ?)", (initial[1],))
        db.execute("INSERT INTO cleanup VALUES('run-1', ?)", (initial[2],))


def transition(db, phase):
    state, used, pending = {"admission": ("admitted", 1, 0), "execution": ("completed", 1, 0),
                            "cleanup": ("cleaned", 0, 0)}[phase]
    db.execute("UPDATE run_state SET state=? WHERE id='run-1'", (state,))
    db.execute("UPDATE resources SET used=? WHERE provider='device'", (used,))
    db.execute("UPDATE cleanup SET pending=? WHERE run_id='run-1'", (pending,))
    db.execute("INSERT INTO events VALUES(1, ?, ?)", (phase, state))


def child(path, phase, timing):
    db = connect(path)
    db.execute("BEGIN IMMEDIATE")
    transition(db, phase)
    if timing == "after-commit":
        db.commit()
    os._exit(73)  # deliberate abrupt process death; no Python cleanup


def inspect(path, phase, timing):
    expected_initial = {"admission": ("submitted", 0, 0), "execution": ("admitted", 1, 0),
                        "cleanup": ("completed", 1, 1)}[phase]
    expected_final = {"admission": ("admitted", 1, 0), "execution": ("completed", 1, 0),
                      "cleanup": ("cleaned", 0, 0)}[phase]
    with connect(path) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        actual = (db.execute("SELECT state FROM run_state WHERE id='run-1'").fetchone()[0],
                  db.execute("SELECT used FROM resources WHERE provider='device'").fetchone()[0],
                  db.execute("SELECT pending FROM cleanup WHERE run_id='run-1'").fetchone()[0])
        events = db.execute("SELECT sequence, phase, transition FROM events ORDER BY sequence").fetchall()
        schema = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]
    want = expected_final if timing == "after-commit" else expected_initial
    return {"integrity": integrity, "schema_version": schema, "actual": list(actual), "expected": list(want),
            "events": [list(row) for row in events], "state_matches": actual == want,
            "event_count_matches": len(events) == (1 if timing == "after-commit" else 0)}


def run_matrix(output):
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for phase in PHASES:
        for timing in TIMINGS:
            for seed in range(1, 11):
                case = f"{phase}-{timing}-{seed:02d}"
                database = output / f"{case}.sqlite3"
                initialize(database, phase)
                result = subprocess.run([sys.executable, __file__, "--child", str(database), phase, timing],
                                        capture_output=True, text=True)
                checked = inspect(database, phase, timing)
                rows.append({"format_version": "e05-crash-case-v1-experimental", "case": case,
                             "phase": phase, "timing": timing, "seed": seed,
                             "child_exit_code": result.returncode, **checked})
                for suffix in ("", "-wal", "-shm"):
                    candidate = Path(str(database) + suffix)
                    if candidate.exists():
                        candidate.unlink()
    raw = output / "crash-cases.jsonl"
    raw.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows))
    summary = {
        "format_version": "e05-durability-v1-experimental", "fresh_process_case_count": len(rows),
        "committed_event_loss_count": sum(r["timing"] == "after-commit" and not r["event_count_matches"] for r in rows),
        "committed_event_duplicate_count": sum(r["timing"] == "after-commit" and len(r["events"]) > 1 for r in rows),
        "visible_uncommitted_transition_count": sum(r["timing"] == "before-commit" and (r["events"] or not r["state_matches"]) for r in rows),
        "event_sequence_gap_or_reorder_count": sum([e[0] for e in r["events"]] not in ([], [1]) for r in rows),
        "sqlite_integrity_failure_count": sum(r["integrity"] != "ok" for r in rows),
        "post_recovery_capacity_violation_count": sum(r["actual"][1] > 1 for r in rows),
        "deliberate_child_exit_code": 73,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def reopen(path):
    with connect(path) as db:
        version = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]
        if version != SCHEMA_VERSION:
            raise RuntimeError(f"incompatible schema: expected {SCHEMA_VERSION}, got {version}")
        db.execute("SELECT COUNT(*) FROM events").fetchone()


def operations(output):
    output.mkdir(parents=True, exist_ok=True)
    database = output / "operations.sqlite3"
    backup = output / "operations.backup.sqlite3"
    for base in (database, backup):
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(base) + suffix)
            if candidate.exists():
                candidate.unlink()
    initialize(database, "admission")
    samples = []
    for _ in range(30):
        started = time.perf_counter()
        reopen(database)
        samples.append(time.perf_counter() - started)
    with connect(database) as source, sqlite3.connect(str(backup)) as target:
        source.backup(target)
    reopen(backup)
    with connect(database) as db:
        db.execute("UPDATE metadata SET value='e05-incompatible-v999' WHERE key='schema_version'")
    diagnostic = ""
    try:
        reopen(database)
    except RuntimeError as error:
        diagnostic = str(error)
    with sqlite3.connect(str(backup)) as source, sqlite3.connect(str(database)) as target:
        source.backup(target)
    reopen(database)
    result = {"format_version": "e05-operations-v1-experimental", "startup_reopen_samples_seconds": samples,
              "startup_reopen_p95_seconds": sorted(samples)[round(.95 * 29)],
              "incompatible_schema_failed_closed": diagnostic.startswith("incompatible schema:"),
              "incompatible_schema_diagnostic": diagnostic, "backup_restore_rehearsal_passed": True}
    (output / "sqlite-operations.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--child", nargs=3, metavar=("DB", "PHASE", "TIMING"))
    parser.add_argument("--reopen", type=Path)
    args = parser.parse_args()
    if args.child:
        child(Path(args.child[0]), args.child[1], args.child[2])
    elif args.reopen:
        reopen(args.reopen)
    else:
        print(json.dumps({"durability": run_matrix(args.output / "raw/durability"),
                          "operations": operations(args.output / "measurements")}, sort_keys=True))


if __name__ == "__main__":
    main()
