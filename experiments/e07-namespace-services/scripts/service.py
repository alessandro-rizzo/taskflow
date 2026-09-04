#!/usr/bin/env python3
"""Tiny experiment-local HTTP API with namespace-private SQLite state."""

from __future__ import annotations

import argparse
import http.server
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any


def response(handler: http.server.BaseHTTPRequestHandler, status: int, value: dict[str, Any]) -> None:
    data = json.dumps(value, sort_keys=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--consumer", required=True)
    parser.add_argument("--health-mode", choices=("ready", "slow", "unhealthy", "exit"), default="ready")
    parser.add_argument("--slow-seconds", type=float, default=3.0)
    args = parser.parse_args()

    if args.health_mode == "exit":
        return 23

    token = os.environ.pop("TASKFLOW_E07_SERVICE_TOKEN", "")
    if not token:
        return 24

    database = Path(args.database)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database))
    connection.execute("CREATE TABLE IF NOT EXISTS values_store (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.commit()
    connection.close()
    ready_at = time.monotonic() + (args.slow_seconds if args.health_mode == "slow" else 0.0)

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "taskflow-e07-api"

        def log_message(self, *_: Any) -> None:
            return

        def do_GET(self) -> None:
            if self.path == "/health":
                if args.health_mode == "unhealthy" or time.monotonic() < ready_at:
                    response(self, 503, {"status": "not-ready"})
                else:
                    response(self, 200, {"status": "ready", "namespace_id": args.namespace})
                return
            if not self.authorized():
                return
            if not self.path.startswith("/value/"):
                response(self, 404, {"code": "not_found"})
                return
            key = self.path[len("/value/"):]
            with sqlite3.connect(str(database)) as db:
                row = db.execute("SELECT value FROM values_store WHERE key = ?", (key,)).fetchone()
            if row is None:
                response(self, 404, {"code": "value_not_found"})
            else:
                response(self, 200, {"key": key, "value": row[0], "namespace_id": args.namespace})

        def do_POST(self) -> None:
            if not self.authorized():
                return
            if not self.path.startswith("/value/"):
                response(self, 404, {"code": "not_found"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            try:
                body = json.loads(self.rfile.read(length))
                value = body["value"]
                if not isinstance(value, str):
                    raise ValueError("value")
            except (json.JSONDecodeError, KeyError, ValueError):
                response(self, 400, {"code": "invalid_value"})
                return
            key = self.path[len("/value/"):]
            with sqlite3.connect(str(database)) as db:
                db.execute("INSERT OR REPLACE INTO values_store(key, value) VALUES (?, ?)", (key, value))
                db.commit()
            response(self, 200, {"key": key, "stored": True, "namespace_id": args.namespace})

        def authorized(self) -> bool:
            supplied = self.headers.get("Authorization", "")
            consumer = self.headers.get("X-Taskflow-Consumer", "")
            if supplied != f"Bearer {token}" or consumer != args.consumer:
                response(self, 403, {"code": "endpoint_not_authorized"})
                return False
            return True

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(json.dumps({"port": server.server_address[1]}), flush=True)
    try:
        server.serve_forever(poll_interval=0.05)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
