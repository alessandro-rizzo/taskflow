from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import durability  # noqa: E402
import simulator  # noqa: E402


class SimulatorTests(unittest.TestCase):
    def test_trace_is_deterministic(self):
        first = simulator.simulate("shared-weighted-aging", 4, 7)
        second = simulator.simulate("shared-weighted-aging", 4, 7)
        self.assertEqual(first, second)

    def test_guarded_candidates_never_oversubscribe(self):
        for candidate in simulator.read("policies.json")["candidates"]:
            if candidate["negative_control"]:
                continue
            _events, metrics = simulator.simulate(candidate["id"], 20, 3)
            self.assertEqual(metrics["capacity_violation_count"], 0, candidate["id"])
            self.assertEqual(metrics["active_lease_count_at_drain"], 0, candidate["id"])
            self.assertEqual(metrics["non_cancelled_terminal_ratio"], 1, candidate["id"])

    def test_negative_control_demonstrates_risk(self):
        _events, metrics = simulator.simulate("independent-unguarded-negative-control", 20, 1)
        self.assertGreater(metrics["capacity_violation_count"], 0)

    def test_attachment_and_concurrency_cases(self):
        result = simulator.lifecycle_cases()
        self.assertEqual(result["false_attachment_count"], 0)
        self.assertGreaterEqual(result["duplicate_active_run_avoided_count"], 1)
        self.assertTrue(all(case["release_before_replacement"] for case in result["concurrency_groups"]))
        self.assertEqual(result["disconnect"]["ticks_after_expiry"], 1)


class SQLiteTests(unittest.TestCase):
    def test_before_and_after_commit_visibility(self):
        with tempfile.TemporaryDirectory() as temporary:
            for timing in durability.TIMINGS:
                database = Path(temporary) / f"{timing}.sqlite3"
                durability.initialize(database, "admission")
                result = subprocess.run([sys.executable, str(SCRIPTS / "durability.py"), "--child",
                                         str(database), "admission", timing])
                self.assertEqual(result.returncode, 73)
                checked = durability.inspect(database, "admission", timing)
                self.assertTrue(checked["state_matches"])
                self.assertTrue(checked["event_count_matches"])
                self.assertEqual(checked["integrity"], "ok")

    def test_incompatible_schema_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "state.sqlite3"
            durability.initialize(database, "admission")
            with durability.connect(database) as db:
                db.execute("UPDATE metadata SET value='incompatible' WHERE key='schema_version'")
            with self.assertRaisesRegex(RuntimeError, "incompatible schema"):
                durability.reopen(database)


if __name__ == "__main__":
    unittest.main()
