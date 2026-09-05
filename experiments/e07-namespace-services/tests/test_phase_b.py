#!/usr/bin/env python3
"""Bounded integration tests for the experiment-local E07 implementation."""

from __future__ import annotations

import copy
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from controller import CLEANUP_STAGES, DIAGNOSTICS  # noqa: E402
from harness import ControllerProcess, http_call, port_closed, start_request  # noqa: E402


class PhaseBTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="taskflow-e07-test-")
        self.controller = ControllerProcess(Path(self.temp.name) / "state")
        self.controller.start()

    def tearDown(self) -> None:
        self.controller.stop()
        self.temp.cleanup()

    def test_concurrent_namespaces_are_private_and_typed(self) -> None:
        barrier = threading.Barrier(3)
        results = {}

        def start(namespace: str) -> None:
            barrier.wait()
            results[namespace] = self.controller.request(start_request(namespace), timeout=4.0)

        threads = [threading.Thread(target=start, args=(name,)) for name in ("ns-a", "ns-b")]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()
        self.assertTrue(results["ns-a"]["ok"])
        self.assertTrue(results["ns-b"]["ok"])
        self.assertNotEqual(results["ns-a"]["handle"]["endpoint_id"], results["ns-b"]["handle"]["endpoint_id"])
        route_a = self.controller.request({"command": "route", "handle": results["ns-a"]["handle"], "consumer_id": "ns-a-ios-e2e", "provider_id": "fake-macos"})
        route_b = self.controller.request({"command": "route", "handle": results["ns-b"]["handle"], "consumer_id": "ns-b-ios-e2e", "provider_id": "fake-macos"})
        self.assertEqual((200, {"key": "marker", "namespace_id": "ns-a", "stored": True}), http_call(route_a["connection"], "POST", "/value/marker", "alpha"))
        self.assertEqual((200, {"key": "marker", "namespace_id": "ns-b", "stored": True}), http_call(route_b["connection"], "POST", "/value/marker", "beta"))
        status, body = http_call(route_a["connection"], "GET", "/value/marker")
        self.assertEqual((status, body["value"]), (200, "alpha"))
        denied = self.controller.request({"command": "route", "handle": results["ns-a"]["handle"], "consumer_id": "ns-b-ios-e2e", "provider_id": "fake-macos"})
        self.assertEqual(denied["diagnostic"]["code"], DIAGNOSTICS["foreign-consumer"])

    def test_all_denial_classes_are_precise_and_side_effect_free(self) -> None:
        started = self.controller.request(start_request("auth"))
        handle = started["handle"]
        cases = []
        wrong = copy.deepcopy(handle); wrong["endpoint_type"] = "Endpoint[DB]"
        cases.append(("wrong-endpoint-type", wrong, "auth-ios-e2e", "fake-macos"))
        cases.append(("foreign-consumer", handle, "stranger", "fake-macos"))
        forged = copy.deepcopy(handle); forged["handle_token"] = "forged"
        cases.append(("forged-handle", forged, "auth-ios-e2e", "fake-macos"))
        missing = copy.deepcopy(handle); missing.pop("handle_token")
        cases.append(("missing-capability", missing, "auth-ios-e2e", "fake-macos"))
        cases.append(("provider-mismatch", handle, "auth-ios-e2e", "unsupported"))
        for denial_class, candidate, consumer, provider in cases:
            before = self.controller.request({"command": "inspect", "namespace_id": "auth"})["namespace"]["active_route_count"]
            result = self.controller.request({"command": "route", "handle": candidate, "consumer_id": consumer, "provider_id": provider})
            after = self.controller.request({"command": "inspect", "namespace_id": "auth"})["namespace"]["active_route_count"]
            self.assertEqual(result["diagnostic"]["code"], DIAGNOSTICS[denial_class])
            self.assertNotIn("connection", result)
            self.assertEqual(before, after)
        self.controller.request({"command": "cleanup", "namespace_id": "auth"})
        stale = self.controller.request({"command": "route", "handle": handle, "consumer_id": "auth-ios-e2e", "provider_id": "fake-macos"})
        self.assertEqual(stale["diagnostic"]["code"], DIAGNOSTICS["stale-handle"])

    def test_readiness_failure_drains_and_restart_cleanup_is_idempotent(self) -> None:
        before = time.monotonic()
        failed = self.controller.request(start_request("unhealthy", health_mode="unhealthy", readiness_timeout_seconds=0.15))
        self.assertFalse(failed["ok"])
        self.assertLess(time.monotonic() - before, 2.0)
        result = self.controller.request(start_request("restart"))
        route = self.controller.request({"command": "route", "handle": result["handle"], "consumer_id": "restart-ios-e2e", "provider_id": "fake-macos"})
        port = route["connection"]["port"]
        self.controller.request({"command": "arm_fault", "namespace_id": "restart", "stage": CLEANUP_STAGES[0], "timing": "after-commit"})
        with self.assertRaises((OSError, ValueError)):
            self.controller.request({"command": "cleanup", "namespace_id": "restart"}, timeout=1.0)
        self.controller.wait_for_exit()
        self.controller.start()
        self.controller.request({"command": "cleanup", "namespace_id": "restart"})
        inspected = self.controller.request({"command": "inspect", "namespace_id": "restart"})["namespace"]
        self.assertFalse(inspected["active"])
        self.assertTrue(port_closed(port))
        events = self.controller.request({"command": "events", "namespace_id": "restart"})["events"]
        stages = [event["event"] for event in events if event["event"] in CLEANUP_STAGES]
        self.assertEqual(stages, CLEANUP_STAGES)


if __name__ == "__main__":
    unittest.main()
