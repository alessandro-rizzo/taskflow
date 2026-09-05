#!/usr/bin/env python3
"""Narrow experiment-local namespace, endpoint, lease, and cleanup owner."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import secrets
import select
import shutil
import signal
import socketserver
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional


FORMAT = "taskflow-e07-event-evidence/v1-experimental"
CLEANUP_STAGES = ["route.revoked", "service.stopped", "namespace.mutable_state.removed", "lease.finalized"]
DIAGNOSTICS = {
    "wrong-endpoint-type": "E07_ENDPOINT_TYPE_MISMATCH",
    "foreign-consumer": "E07_CONSUMER_NOT_AUTHORIZED",
    "forged-handle": "E07_ENDPOINT_HANDLE_INVALID",
    "missing-capability": "E07_ROUTE_CAPABILITY_MISSING",
    "stale-handle": "E07_ENDPOINT_HANDLE_STALE",
    "provider-mismatch": "E07_PROVIDER_MISMATCH",
}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def process_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        waited, _ = os.waitpid(pid, os.WNOHANG)
        if waited == pid:
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def stop_process(pid: Optional[int]) -> None:
    if not pid or not process_alive(pid):
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 0.75
    waiter = threading.Event()
    while process_alive(pid) and time.monotonic() < deadline:
        waiter.wait(0.01)
    if process_alive(pid):
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class Controller:
    def __init__(self, state_root: Path):
        self.state_root = state_root.resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.mutable_root = self.state_root / "mutable"
        self.mutable_root.mkdir(exist_ok=True)
        self.database = self.state_root / "controller.sqlite3"
        self.scripts = Path(__file__).resolve().parent
        self.shutdown_requested = threading.Event()
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS namespaces (
                    namespace_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    service_name TEXT NOT NULL UNIQUE,
                    mutable_root TEXT NOT NULL UNIQUE,
                    database_path TEXT NOT NULL UNIQUE,
                    service_pid INTEGER,
                    service_port INTEGER NOT NULL UNIQUE,
                    service_token TEXT NOT NULL,
                    endpoint_id TEXT NOT NULL UNIQUE,
                    handle_token TEXT NOT NULL UNIQUE,
                    consumer_id TEXT NOT NULL,
                    lease_id TEXT NOT NULL UNIQUE,
                    lease_ttl_seconds REAL NOT NULL,
                    deadline_monotonic REAL NOT NULL,
                    active INTEGER NOT NULL,
                    ready INTEGER NOT NULL,
                    cleanup_stage INTEGER NOT NULL,
                    fault_stage TEXT,
                    fault_timing TEXT,
                    fault_armed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS routes (
                    route_id TEXT PRIMARY KEY,
                    namespace_id TEXT NOT NULL,
                    consumer_id TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    pid INTEGER,
                    port INTEGER NOT NULL,
                    route_token TEXT NOT NULL UNIQUE,
                    active INTEGER NOT NULL,
                    FOREIGN KEY(namespace_id) REFERENCES namespaces(namespace_id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    namespace_id TEXT NOT NULL,
                    monotonic_seconds REAL NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )

    def emit(self, db: sqlite3.Connection, event: str, row: sqlite3.Row | dict[str, Any], **payload: Any) -> None:
        run_id = row["run_id"]
        namespace_id = row["namespace_id"]
        db.execute(
            "INSERT INTO events(event, run_id, namespace_id, monotonic_seconds, payload_json) VALUES (?, ?, ?, ?, ?)",
            (event, run_id, namespace_id, time.monotonic(), json.dumps(payload, sort_keys=True, separators=(",", ":"))),
        )

    def start_service(self, request: dict[str, Any]) -> dict[str, Any]:
        namespace_id = str(request["namespace_id"])
        consumer_id = str(request["consumer_id"])
        run_id = str(request.get("run_id", f"run-{namespace_id}"))
        ttl = float(request.get("lease_ttl_seconds", 1.0))
        health_mode = str(request.get("health_mode", "ready"))
        readiness_timeout = float(request.get("readiness_timeout_seconds", 2.0))
        unique = uuid.uuid4().hex[:12]
        mutable = (self.mutable_root / f"{namespace_id}-{unique}").resolve()
        if self.mutable_root not in mutable.parents:
            raise ValueError("mutable path escaped state root")
        mutable.mkdir(mode=0o700, parents=True)
        database_path = mutable / "service.sqlite3"
        service_name = f"taskflow-e07-{namespace_id}-{unique}"
        endpoint_id = f"endpoint-{namespace_id}-{unique}"
        lease_id = f"lease-{namespace_id}-{unique}"
        service_token = secrets.token_urlsafe(32)
        handle_token = secrets.token_urlsafe(32)
        started = time.monotonic()
        environment = dict(os.environ)
        environment["TASKFLOW_E07_SERVICE_TOKEN"] = service_token
        command = [
            sys.executable,
            str(self.scripts / "service.py"),
            "--database", str(database_path),
            "--namespace", namespace_id,
            "--consumer", consumer_id,
            "--health-mode", health_mode,
        ]
        process = subprocess.Popen(
            command,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
        port: Optional[int] = None
        if process.stdout is not None:
            ready, _, _ = select.select([process.stdout], [], [], min(readiness_timeout, 2.0))
            if ready:
                line = process.stdout.readline()
                if line:
                    port = int(json.loads(line)["port"])
        if port is None:
            stop_process(process.pid)
            shutil.rmtree(mutable, ignore_errors=True)
            return {"ok": False, "code": "E07_SERVICE_START_FAILED", "namespace_id": namespace_id}

        row = {
            "namespace_id": namespace_id,
            "run_id": run_id,
        }
        with self.connect() as db:
            db.execute(
                """INSERT INTO namespaces(
                    namespace_id, run_id, service_name, mutable_root, database_path,
                    service_pid, service_port, service_token, endpoint_id, handle_token,
                    consumer_id, lease_id, lease_ttl_seconds, deadline_monotonic,
                    active, ready, cleanup_stage
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, 0)""",
                (
                    namespace_id, run_id, service_name, str(mutable), str(database_path),
                    process.pid, port, service_token, endpoint_id, handle_token,
                    consumer_id, lease_id, ttl, time.monotonic() + ttl,
                ),
            )
            self.emit(db, "service.process.started", row, service_id=service_name, resource_id=service_name)

        deadline = started + readiness_timeout
        waiter = threading.Event()
        ready = False
        probes = 0
        while time.monotonic() < deadline and process_alive(process.pid):
            probes += 1
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
            try:
                connection.request("GET", "/health")
                health = connection.getresponse()
                health.read()
                if health.status == 200:
                    ready = True
                    break
            except OSError:
                pass
            finally:
                connection.close()
            waiter.wait(0.01)

        if not ready:
            with self.connect() as db:
                current = db.execute("SELECT * FROM namespaces WHERE namespace_id = ?", (namespace_id,)).fetchone()
                assert current is not None
                self.emit(db, "service.readiness.failed", current, service_id=service_name, resource_id=service_name, health_transition="not-ready", probe_count=probes)
            self.cleanup(namespace_id, "readiness-failed")
            return {
                "ok": False,
                "code": "E07_SERVICE_NOT_READY",
                "namespace_id": namespace_id,
                "drain_seconds": time.monotonic() - deadline if time.monotonic() > deadline else 0.0,
            }

        ready_at = time.monotonic()
        with self.connect() as db:
            current = db.execute("SELECT * FROM namespaces WHERE namespace_id = ?", (namespace_id,)).fetchone()
            assert current is not None
            db.execute("UPDATE namespaces SET ready = 1 WHERE namespace_id = ?", (namespace_id,))
            self.emit(db, "service.ready", current, service_id=service_name, resource_id=service_name, health_transition="ready", probe_count=probes, readiness_seconds=ready_at - started)

        return {
            "ok": True,
            "handle": {
                "format_version": "taskflow-e07-endpoint-handle/v1-experimental",
                "endpoint_type": "Endpoint[API]",
                "endpoint_id": endpoint_id,
                "namespace_id": namespace_id,
                "lease_id": lease_id,
                "handle_token": handle_token,
            },
            "readiness_seconds": ready_at - started,
        }

    def deny(self, code: str, endpoint_id: str, consumer_id: str, namespace_id: str, policy_id: str = "e07-endpoint-policy-v1") -> dict[str, Any]:
        return {
            "ok": False,
            "diagnostic": {
                "code": code,
                "endpoint_id": endpoint_id,
                "consumer_id": consumer_id,
                "namespace_id": namespace_id,
                "policy_id": policy_id,
            },
        }

    def resolve_route(self, request: dict[str, Any]) -> dict[str, Any]:
        handle = request.get("handle") or {}
        endpoint_id = str(handle.get("endpoint_id", ""))
        namespace_id = str(handle.get("namespace_id", ""))
        consumer_id = str(request.get("consumer_id", ""))
        provider_id = str(request.get("provider_id", ""))
        if handle.get("endpoint_type") != "Endpoint[API]":
            return self.deny(DIAGNOSTICS["wrong-endpoint-type"], endpoint_id, consumer_id, namespace_id)
        if not handle.get("handle_token"):
            return self.deny(DIAGNOSTICS["missing-capability"], endpoint_id, consumer_id, namespace_id)
        with self.connect() as db:
            row = db.execute("SELECT * FROM namespaces WHERE endpoint_id = ?", (endpoint_id,)).fetchone()
            if row is None or handle.get("handle_token") != row["handle_token"] or namespace_id != row["namespace_id"]:
                return self.deny(DIAGNOSTICS["forged-handle"], endpoint_id, consumer_id, namespace_id)
            if not row["active"] or not row["ready"]:
                return self.deny(DIAGNOSTICS["stale-handle"], endpoint_id, consumer_id, namespace_id)
            if consumer_id != row["consumer_id"]:
                self.emit(db, "endpoint.route.denied", row, endpoint_id=endpoint_id, consumer_id=consumer_id, provider_id=provider_id, route_decision="denied", diagnostic_code=DIAGNOSTICS["foreign-consumer"], policy_id="e07-endpoint-policy-v1")
                return self.deny(DIAGNOSTICS["foreign-consumer"], endpoint_id, consumer_id, namespace_id)
            if provider_id not in {"fake-macos", "direct-loopback-control"}:
                self.emit(db, "endpoint.route.denied", row, endpoint_id=endpoint_id, consumer_id=consumer_id, provider_id=provider_id, route_decision="denied", diagnostic_code=DIAGNOSTICS["provider-mismatch"], policy_id="e07-endpoint-policy-v1")
                return self.deny(DIAGNOSTICS["provider-mismatch"], endpoint_id, consumer_id, namespace_id)
            existing = db.execute(
                "SELECT * FROM routes WHERE namespace_id = ? AND consumer_id = ? AND provider_id = ? AND active = 1 ORDER BY rowid LIMIT 1",
                (namespace_id, consumer_id, provider_id),
            ).fetchone()
            if existing is not None:
                returned_token = str(existing["route_token"])
                self.emit(
                    db,
                    "endpoint.route.authorized",
                    row,
                    endpoint_id=endpoint_id,
                    consumer_id=consumer_id,
                    provider_id=provider_id,
                    route_decision="authorized",
                    capability_digest=digest(returned_token),
                    route_id=existing["route_id"],
                    reused=True,
                )
                return {
                    "ok": True,
                    "connection": {
                        "host": "127.0.0.1",
                        "port": existing["port"],
                        "credential": returned_token,
                        "consumer_id": consumer_id,
                        "route_id": existing["route_id"],
                        "provider_id": provider_id,
                    },
                }
            route_id = f"route-{namespace_id}-{uuid.uuid4().hex[:12]}"
            route_token = secrets.token_urlsafe(32)
            route_pid: Optional[int] = None
            route_port = int(row["service_port"])
            returned_token = str(row["service_token"])
            if provider_id == "fake-macos":
                environment = dict(os.environ)
                environment["TASKFLOW_E07_ROUTE_TOKEN"] = route_token
                environment["TASKFLOW_E07_BACKEND_TOKEN"] = str(row["service_token"])
                relay = subprocess.Popen(
                    [sys.executable, str(self.scripts / "relay.py"), "--backend-port", str(row["service_port"]), "--consumer", consumer_id],
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    start_new_session=True,
                )
                route_pid = relay.pid
                if relay.stdout is None:
                    stop_process(relay.pid)
                    return self.deny(DIAGNOSTICS["provider-mismatch"], endpoint_id, consumer_id, namespace_id)
                ready, _, _ = select.select([relay.stdout], [], [], 1.0)
                if not ready:
                    stop_process(relay.pid)
                    return self.deny(DIAGNOSTICS["provider-mismatch"], endpoint_id, consumer_id, namespace_id)
                route_port = int(json.loads(relay.stdout.readline())["port"])
                returned_token = route_token
            else:
                route_token = returned_token
            db.execute(
                "INSERT INTO routes(route_id, namespace_id, consumer_id, provider_id, pid, port, route_token, active) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (route_id, namespace_id, consumer_id, provider_id, route_pid, route_port, route_token),
            )
            self.emit(db, "endpoint.route.authorized", row, endpoint_id=endpoint_id, consumer_id=consumer_id, provider_id=provider_id, route_decision="authorized", capability_digest=digest(returned_token), route_id=route_id)
        return {
            "ok": True,
            "connection": {
                "host": "127.0.0.1",
                "port": route_port,
                "credential": returned_token,
                "consumer_id": consumer_id,
                "route_id": route_id,
                "provider_id": provider_id,
            },
        }

    def heartbeat(self, namespace_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM namespaces WHERE namespace_id = ?", (namespace_id,)).fetchone()
            if row is None or not row["active"]:
                return {"ok": False, "code": "E07_LEASE_INACTIVE"}
            db.execute("UPDATE namespaces SET deadline_monotonic = ? WHERE namespace_id = ?", (time.monotonic() + float(row["lease_ttl_seconds"]), namespace_id))
            self.emit(db, "lease.renewed", row, lease_id=row["lease_id"], resource_id=row["service_name"])
        return {"ok": True}

    def arm_fault(self, namespace_id: str, stage: str, timing: str) -> dict[str, Any]:
        if stage not in CLEANUP_STAGES or timing not in {"before-commit", "after-commit"}:
            return {"ok": False, "code": "E07_INVALID_FAULT"}
        with self.connect() as db:
            db.execute("UPDATE namespaces SET fault_stage = ?, fault_timing = ?, fault_armed = 1 WHERE namespace_id = ?", (stage, timing, namespace_id))
        return {"ok": True}

    def consume_before_fault(self, db: sqlite3.Connection, row: sqlite3.Row, stage: str) -> None:
        if row["fault_armed"] and row["fault_stage"] == stage and row["fault_timing"] == "before-commit":
            db.execute("UPDATE namespaces SET fault_armed = 0 WHERE namespace_id = ?", (row["namespace_id"],))
            db.commit()
            os._exit(70)

    def after_fault(self, row: sqlite3.Row, stage: str) -> None:
        if row["fault_armed"] and row["fault_stage"] == stage and row["fault_timing"] == "after-commit":
            os._exit(71)

    def cleanup(self, namespace_id: str, reason: str = "explicit") -> dict[str, Any]:
        cleanup_started = time.monotonic()
        while True:
            with self.connect() as db:
                row = db.execute("SELECT * FROM namespaces WHERE namespace_id = ?", (namespace_id,)).fetchone()
                if row is None:
                    return {"ok": True, "absent": True}
                stage_index = int(row["cleanup_stage"])
                if stage_index >= len(CLEANUP_STAGES):
                    return {"ok": True, "cleanup_seconds": time.monotonic() - cleanup_started}
                stage = CLEANUP_STAGES[stage_index]
                self.consume_before_fault(db, row, stage)
                if stage == "route.revoked":
                    routes = db.execute("SELECT * FROM routes WHERE namespace_id = ? AND active = 1", (namespace_id,)).fetchall()
                    for route in routes:
                        stop_process(route["pid"])
                    db.execute("UPDATE routes SET active = 0 WHERE namespace_id = ?", (namespace_id,))
                elif stage == "service.stopped":
                    stop_process(row["service_pid"])
                elif stage == "namespace.mutable_state.removed":
                    mutable = Path(row["mutable_root"]).resolve()
                    if self.mutable_root in mutable.parents:
                        shutil.rmtree(mutable, ignore_errors=True)
                elif stage == "lease.finalized":
                    db.execute("UPDATE namespaces SET active = 0 WHERE namespace_id = ?", (namespace_id,))
                db.execute("UPDATE namespaces SET cleanup_stage = ?, fault_armed = CASE WHEN fault_stage = ? AND fault_timing = 'after-commit' THEN 0 ELSE fault_armed END WHERE namespace_id = ?", (stage_index + 1, stage, namespace_id))
                self.emit(db, stage, row, lease_id=row["lease_id"], resource_id=row["service_name"], cleanup_stage=stage, cleanup_reason=reason, cleanup_latency_seconds=time.monotonic() - cleanup_started)
                db.commit()
                self.after_fault(row, stage)

    def inspect(self, namespace_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM namespaces WHERE namespace_id = ?", (namespace_id,)).fetchone()
            if row is None:
                return {"ok": False, "code": "E07_NAMESPACE_ABSENT"}
            active_routes = db.execute("SELECT COUNT(*) FROM routes WHERE namespace_id = ? AND active = 1", (namespace_id,)).fetchone()[0]
            return {
                "ok": True,
                "namespace": {
                    "namespace_id": namespace_id,
                    "service_name": row["service_name"],
                    "mutable_root": row["mutable_root"],
                    "database_path": row["database_path"],
                    "service_pid": row["service_pid"],
                    "service_port": row["service_port"],
                    "endpoint_id": row["endpoint_id"],
                    "lease_id": row["lease_id"],
                    "active": bool(row["active"]),
                    "ready": bool(row["ready"]),
                    "cleanup_stage": int(row["cleanup_stage"]),
                    "deadline_monotonic": float(row["deadline_monotonic"]),
                    "active_route_count": int(active_routes),
                    "service_process_alive": process_alive(row["service_pid"]),
                    "mutable_root_exists": Path(row["mutable_root"]).exists(),
                },
            }

    def events(self, namespace_id: Optional[str] = None) -> dict[str, Any]:
        with self.connect() as db:
            if namespace_id:
                rows = db.execute("SELECT * FROM events WHERE namespace_id = ? ORDER BY sequence", (namespace_id,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM events ORDER BY sequence").fetchall()
        events = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            events.append({
                "format_version": FORMAT,
                "sequence": row["sequence"],
                "event": row["event"],
                "run_id": row["run_id"],
                "namespace_id": row["namespace_id"],
                "monotonic_seconds": row["monotonic_seconds"],
                **payload,
            })
        return {"ok": True, "events": events}

    def reaper_once(self) -> None:
        now = time.monotonic()
        with self.connect() as db:
            rows = db.execute("SELECT * FROM namespaces WHERE active = 1 AND deadline_monotonic <= ? ORDER BY namespace_id", (now,)).fetchall()
            for row in rows:
                already = db.execute("SELECT COUNT(*) FROM events WHERE namespace_id = ? AND event = 'lease.expired'", (row["namespace_id"],)).fetchone()[0]
                if not already:
                    self.emit(db, "lease.heartbeat.missed", row, lease_id=row["lease_id"], resource_id=row["service_name"])
                    self.emit(db, "lease.expired", row, lease_id=row["lease_id"], resource_id=row["service_name"], expiry_lateness_seconds=max(0.0, now - float(row["deadline_monotonic"])))
        for row in rows:
            self.cleanup(row["namespace_id"], "ttl-expired")

    def cleanup_all(self) -> None:
        with self.connect() as db:
            ids = [row[0] for row in db.execute("SELECT namespace_id FROM namespaces WHERE active = 1 ORDER BY namespace_id")]
        for namespace_id in ids:
            self.cleanup(namespace_id, "controller-shutdown")

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        command = request.get("command")
        if command == "start":
            return self.start_service(request)
        if command == "route":
            return self.resolve_route(request)
        if command == "heartbeat":
            return self.heartbeat(str(request["namespace_id"]))
        if command == "cleanup":
            return self.cleanup(str(request["namespace_id"]), str(request.get("reason", "explicit")))
        if command == "arm_fault":
            return self.arm_fault(str(request["namespace_id"]), str(request["stage"]), str(request["timing"]))
        if command == "inspect":
            return self.inspect(str(request["namespace_id"]))
        if command == "events":
            return self.events(request.get("namespace_id"))
        if command == "shutdown":
            self.cleanup_all()
            self.shutdown_requested.set()
            return {"ok": True}
        return {"ok": False, "code": "E07_UNKNOWN_COMMAND"}


class UnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def serve(state_root: Path, socket_path: Path) -> int:
    controller = Controller(state_root)
    try:
        socket_path.unlink()
    except FileNotFoundError:
        pass

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            try:
                request = json.loads(self.rfile.readline())
                result = controller.dispatch(request)
            except Exception as error:  # trusted harness diagnostic boundary
                result = {"ok": False, "code": "E07_CONTROLLER_ERROR", "detail": str(error)}
            self.wfile.write((json.dumps(result, sort_keys=True) + "\n").encode("utf-8"))

    server = UnixServer(str(socket_path), Handler)
    server.timeout = 0.1

    def reaper() -> None:
        while not controller.shutdown_requested.wait(0.1):
            controller.reaper_once()

    thread = threading.Thread(target=reaper, name="e07-reaper", daemon=True)
    thread.start()
    while not controller.shutdown_requested.is_set():
        server.handle_request()
    server.server_close()
    try:
        socket_path.unlink()
    except FileNotFoundError:
        pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("serve", nargs="?")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--socket", required=True)
    args = parser.parse_args()
    return serve(Path(args.state_root), Path(args.socket))


if __name__ == "__main__":
    raise SystemExit(main())
