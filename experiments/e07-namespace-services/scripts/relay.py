#!/usr/bin/env python3
"""Fake-macOS provider route that validates a route capability and proxies HTTP."""

from __future__ import annotations

import argparse
import http.client
import http.server
import json
import os
from typing import Any, Optional


def emit(handler: http.server.BaseHTTPRequestHandler, status: int, payload: bytes, content_type: str = "application/json") -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-port", type=int, required=True)
    parser.add_argument("--consumer", required=True)
    args = parser.parse_args()
    route_token = os.environ.pop("TASKFLOW_E07_ROUTE_TOKEN", "")
    backend_token = os.environ.pop("TASKFLOW_E07_BACKEND_TOKEN", "")
    if not route_token or not backend_token:
        return 24

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "taskflow-e07-fake-macos-relay"

        def log_message(self, *_: Any) -> None:
            return

        def do_GET(self) -> None:
            self.proxy(None)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            self.proxy(self.rfile.read(length))

        def proxy(self, body: Optional[bytes]) -> None:
            if self.headers.get("Authorization", "") != f"Bearer {route_token}" or self.headers.get("X-Taskflow-Consumer", "") != args.consumer:
                emit(self, 403, json.dumps({"code": "route_not_authorized"}).encode("utf-8"))
                return
            headers = {
                "Authorization": f"Bearer {backend_token}",
                "X-Taskflow-Consumer": args.consumer,
                "Content-Type": self.headers.get("Content-Type", "application/json"),
            }
            connection = http.client.HTTPConnection("127.0.0.1", args.backend_port, timeout=1.0)
            try:
                connection.request(self.command, self.path, body=body, headers=headers)
                upstream = connection.getresponse()
                payload = upstream.read()
                emit(self, upstream.status, payload, upstream.getheader("Content-Type", "application/json"))
            except OSError:
                emit(self, 502, json.dumps({"code": "backend_unavailable"}).encode("utf-8"))
            finally:
                connection.close()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(json.dumps({"port": server.server_address[1]}), flush=True)
    try:
        server.serve_forever(poll_interval=0.05)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
