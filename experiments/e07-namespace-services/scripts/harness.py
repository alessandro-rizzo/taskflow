#!/usr/bin/env python3
"""Client helpers for the bounded E07 local-process experiment."""

from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional, Tuple


SCRIPTS = Path(__file__).resolve().parent


def rpc(socket_path: Path, payload: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(str(socket_path))
        client.sendall((json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"))
        chunks = bytearray()
        while not chunks.endswith(b"\n"):
            part = client.recv(65536)
            if not part:
                break
            chunks.extend(part)
        return json.loads(bytes(chunks))
    finally:
        client.close()


def http_call(connection: dict[str, Any], method: str, path: str, value: Optional[str] = None, override_credential: Optional[str] = None, override_consumer: Optional[str] = None) -> Tuple[int, dict[str, Any]]:
    body: Optional[bytes] = None
    headers = {
        "Authorization": f"Bearer {override_credential if override_credential is not None else connection['credential']}",
        "X-Taskflow-Consumer": override_consumer if override_consumer is not None else connection["consumer_id"],
        "Content-Type": "application/json",
    }
    if value is not None:
        body = json.dumps({"value": value}).encode("utf-8")
    client = http.client.HTTPConnection(connection["host"], int(connection["port"]), timeout=2.0)
    try:
        client.request(method, path, body=body, headers=headers)
        result = client.getresponse()
        data = result.read()
        return result.status, json.loads(data) if data else {}
    finally:
        client.close()


def port_closed(port: int) -> bool:
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(0.1)
    try:
        return client.connect_ex(("127.0.0.1", port)) != 0
    finally:
        client.close()


class ControllerProcess:
    def __init__(self, state_root: Path):
        self.state_root = state_root
        self.socket_path = state_root / "controller.sock"
        self.process: Optional[subprocess.Popen[Any]] = None

    def start(self) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        self.process = subprocess.Popen(
            [sys.executable, str(SCRIPTS / "controller.py"), "serve", "--state-root", str(self.state_root), "--socket", str(self.socket_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        waiter = threading.Event()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"controller exited with {self.process.returncode}")
            if self.socket_path.exists():
                try:
                    result = rpc(self.socket_path, {"command": "events"}, timeout=0.2)
                    if result.get("ok"):
                        return
                except (OSError, ValueError):
                    pass
            waiter.wait(0.01)
        raise RuntimeError("controller did not become ready")

    def request(self, payload: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
        return rpc(self.socket_path, payload, timeout=timeout)

    def wait_for_exit(self, timeout: float = 3.0) -> int:
        if self.process is None:
            raise RuntimeError("controller not started")
        return self.process.wait(timeout=timeout)

    def stop(self, cleanup: bool = True) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        if cleanup:
            try:
                self.request({"command": "shutdown"}, timeout=5.0)
            except OSError:
                pass
        try:
            self.process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.process.pid, 15)
                self.process.wait(timeout=1.0)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.process.pid, 9)
                except ProcessLookupError:
                    pass


def start_request(namespace_id: str, consumer_id: Optional[str] = None, health_mode: str = "ready", readiness_timeout_seconds: float = 2.0) -> dict[str, Any]:
    return {
        "command": "start",
        "namespace_id": namespace_id,
        "consumer_id": consumer_id or f"{namespace_id}-ios-e2e",
        "run_id": f"run-{namespace_id}",
        "lease_ttl_seconds": 1.0,
        "health_mode": health_mode,
        "readiness_timeout_seconds": readiness_timeout_seconds,
    }
