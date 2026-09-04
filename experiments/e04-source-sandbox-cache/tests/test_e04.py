from __future__ import annotations

import copy
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


EXPERIMENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT))

import e04  # noqa: E402


class SourceTests(unittest.TestCase):
    def test_capture_materializes_original_bytes_after_live_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="taskflow-e04-test-") as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "main.go").write_text("package original\n", encoding="utf-8")
            cas = e04.CAS(root / "cas")
            manifest = cas.capture(source)

            (source / "main.go").write_text("package mutated\n", encoding="utf-8")
            (source / "extra.go").write_text("package mutated\n", encoding="utf-8")
            target = root / "materialized"
            cas.materialize(manifest, target)

            self.assertEqual((target / "main.go").read_text(encoding="utf-8"), "package original\n")
            self.assertFalse((target / "extra.go").exists())
            self.assertEqual(e04.tree_digest(target), manifest.digest)

    def test_capture_rejects_symlink_without_reading_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="taskflow-e04-test-") as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            secret = root / "secret"
            secret.write_text("must-not-leak", encoding="utf-8")
            (source / "link").symlink_to(secret)
            with self.assertRaisesRegex(ValueError, "symbolic link") as raised:
                e04.CAS(root / "cas").capture(source)
            self.assertNotIn("must-not-leak", str(raised.exception))

    def test_materialize_rejects_corrupt_blob(self) -> None:
        with tempfile.TemporaryDirectory(prefix="taskflow-e04-test-") as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "file").write_text("valid", encoding="utf-8")
            cas = e04.CAS(root / "cas")
            manifest = cas.capture(source)
            blob = cas.blobs / manifest.files[0]["digest"]
            blob.chmod(0o600)
            blob.write_text("bad", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "verification failed"):
                cas.materialize(manifest, root / "target")


class SandboxTests(unittest.TestCase):
    def test_copy_and_apfs_clone_create_private_writable_roots(self) -> None:
        with tempfile.TemporaryDirectory(prefix="taskflow-e04-test-") as temporary:
            root = Path(temporary)
            base = root / "base"
            base.mkdir()
            (base / "source.txt").write_text("immutable", encoding="utf-8")
            base.chmod(0o555)
            (base / "source.txt").chmod(0o444)
            for method in ("copy", "apfs-clone"):
                target = root / method
                e04.create_sandbox(base, target, method)
                (target / "source.txt").write_text(method, encoding="utf-8")
                self.assertEqual((target / "source.txt").read_text(encoding="utf-8"), method)
                self.assertEqual((base / "source.txt").read_text(encoding="utf-8"), "immutable")

    @unittest.skipUnless(shutil.which("sandbox-exec"), "sandbox-exec unavailable")
    def test_profile_denies_named_peer_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="taskflow-e04-test-") as temporary:
            root = Path(temporary)
            own = root / "own"
            own.mkdir()
            peer = root / "peer.txt"
            peer.write_text("peer-secret", encoding="utf-8")
            completed = e04.run_with_profile(
                [sys.executable, "-c", "from pathlib import Path; import sys; Path(sys.argv[1]).read_bytes()", str(peer)],
                own,
                {"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                [peer],
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertNotIn("peer-secret", completed.stderr)


class CacheIdentityTests(unittest.TestCase):
    def test_every_component_is_required_and_identity_sensitive(self) -> None:
        base = e04.example_identity()
        original = e04.cache_key(base)
        for name in e04.REQUIRED_IDENTITY_COMPONENTS:
            missing = copy.deepcopy(base)
            missing[name] = None
            with self.assertRaisesRegex(ValueError, name):
                e04.cache_key(missing)

            changed = copy.deepcopy(base)
            if isinstance(changed[name], list):
                changed[name][0]["digest"] += "-changed"
            elif name == "resolved_process_and_arguments":
                changed[name]["argv"].append("-count=1")
            else:
                changed[name]["digest"] += "-changed"
            self.assertNotEqual(e04.cache_key(changed), original, name)

    def test_unordered_manifest_and_environment_declarations_normalize(self) -> None:
        first = e04.example_identity()
        first["typed_input_manifests"].append({"id": "input-b", "digest": "b"})
        first["dependency_manifests"].append({"id": "z", "digest": "z"})
        second = copy.deepcopy(first)
        second["typed_input_manifests"].reverse()
        second["dependency_manifests"].reverse()
        second["sandbox_policy"]["environment"].reverse()
        self.assertEqual(e04.cache_key(first), e04.cache_key(second))

    def test_ready_hit_returns_before_reservation(self) -> None:
        components, cache, identity = e04.ready_cache()
        result = e04.execute_cached(components, cache, components["execution_profile"]["digest"])
        self.assertEqual(result.status, "cache-hit")
        self.assertEqual(result.identity, identity)
        self.assertTrue(all(value == 0 for value in result.counters.values()))
        kinds = [event["kind"] for event in result.events]
        self.assertEqual(kinds[-1], "return-artifact-handle")
        self.assertNotIn("reserve-worker", kinds)
        self.assertNotIn("create-sandbox", kinds)

    def test_persistent_ready_hit_is_prepared_before_lookup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="taskflow-e04-test-") as temporary:
            root = Path(temporary) / "taskflow-e04-cache"
            components, memory_cache, identity = e04.ready_cache()
            entry = memory_cache.lookup(identity)
            self.assertIsNotNone(entry)
            persistent = e04.PersistentResultCache(root)
            persistent.put(entry)

            result = e04.execute_cached(components, persistent, components["execution_profile"]["digest"])
            self.assertEqual(result.status, "cache-hit")
            self.assertTrue(all(value == 0 for value in result.counters.values()))

    def test_attestation_mismatch_fails_closed_without_rekey(self) -> None:
        components = e04.example_identity()
        expected_identity = e04.cache_key(components)
        result = e04.execute_cached(components, e04.ResultCache(), "profile-unexpected")
        self.assertEqual(result.status, "attestation-mismatch")
        self.assertEqual(result.identity, expected_identity)
        self.assertEqual(result.counters["reservations"], 1)
        self.assertEqual(result.counters["sandboxes"], 0)
        self.assertEqual(result.counters["executions"], 0)
        self.assertEqual(result.counters["publications"], 0)
        kinds = [event["kind"] for event in result.events]
        self.assertEqual(kinds[-1], "reject-attestation")

    def test_performance_caches_cannot_authorize_result_hit(self) -> None:
        components = e04.example_identity()
        tool = e04.ToolCache({"poison": b"success"})
        workers = e04.WarmWorkerState(ready_workers=10)
        result = e04.execute_cached(components, e04.ResultCache(), components["execution_profile"]["digest"])
        self.assertEqual(result.status, "executed")
        self.assertEqual(tool.values["poison"], b"success")
        self.assertEqual(workers.ready_workers, 10)
        self.assertEqual(result.counters["reservations"], 1)


if __name__ == "__main__":
    unittest.main()
