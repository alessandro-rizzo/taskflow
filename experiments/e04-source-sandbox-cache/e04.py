#!/usr/bin/env python3
"""Disposable E04 source, sandbox, and cache-identity experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SOURCE_SCHEMA = "taskflow-e04-source-manifest/v1-experimental"
CACHE_SCHEMA = "taskflow-e04-cache-identity/v1-experimental"
REQUIRED_IDENTITY_COMPONENTS = (
    "source_manifest",
    "typed_input_manifests",
    "resolved_process_and_arguments",
    "execution_profile",
    "sandbox_policy",
    "dependency_manifests",
)


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def safe_relative(value: str) -> PurePosixPath:
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or value in ("", ".") or "\\" in value:
        raise ValueError(f"unsafe relative path: {value!r}")
    return relative


@dataclass(frozen=True)
class SourceManifest:
    digest: str
    files: tuple[dict[str, Any], ...]

    def document(self) -> dict[str, Any]:
        return {"schema_version": SOURCE_SCHEMA, "tree_digest": self.digest, "files": list(self.files)}


class CAS:
    def __init__(self, root: Path):
        self.root = root
        self.blobs = root / "blobs"
        self.manifests = root / "manifests"
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.manifests.mkdir(parents=True, exist_ok=True)

    def capture(self, source: Path) -> SourceManifest:
        if source.is_symlink() or not source.is_dir():
            raise ValueError("source root must be a real directory")
        files: list[dict[str, Any]] = []
        for path in sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix()):
            relative = path.relative_to(source).as_posix()
            if path.is_symlink():
                raise ValueError(f"source path {relative!r} is a symbolic link")
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ValueError(f"source path {relative!r} is not a regular file")
            content = path.read_bytes()
            digest = digest_bytes(content)
            blob = self.blobs / digest
            if blob.exists():
                if digest_bytes(blob.read_bytes()) != digest:
                    raise ValueError(f"existing CAS blob is corrupt: {digest}")
            else:
                temporary = self.blobs / f".{digest}.{os.getpid()}.tmp"
                temporary.write_bytes(content)
                temporary.chmod(0o444)
                temporary.replace(blob)
            files.append({"path": relative, "digest": digest, "size_bytes": len(content), "mode": mode & 0o777})
        identity_files = [{key: item[key] for key in ("path", "digest", "size_bytes")} for item in files]
        identity_document = {"schema_version": SOURCE_SCHEMA, "files": identity_files}
        tree_digest = digest_bytes(canonical_bytes(identity_document))
        manifest = SourceManifest(tree_digest, tuple(files))
        write_json(self.manifests / f"{tree_digest}.json", manifest.document())
        return manifest

    def materialize(self, manifest: SourceManifest, target: Path, read_only: bool = False) -> None:
        if target.exists() or target.is_symlink():
            raise ValueError(f"materialization target already exists: {target}")
        target.mkdir(parents=True, mode=0o700)
        for entry in manifest.files:
            relative = safe_relative(entry["path"])
            blob = self.blobs / entry["digest"]
            content = blob.read_bytes()
            if len(content) != entry["size_bytes"] or digest_bytes(content) != entry["digest"]:
                raise ValueError(f"CAS blob verification failed: {entry['digest']}")
            destination = target.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            destination.chmod(0o444 if read_only else entry["mode"])
        if read_only:
            for directory in sorted((item for item in target.rglob("*") if item.is_dir()), reverse=True):
                directory.chmod(0o555)
            target.chmod(0o555)
        if tree_digest(target) != manifest.digest:
            raise ValueError("materialized source digest does not match manifest")


def tree_digest(root: Path) -> str:
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise ValueError(f"materialized tree contains symlink: {path.relative_to(root)}")
        if path.is_file():
            content = path.read_bytes()
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "digest": digest_bytes(content),
                    "size_bytes": len(content),
                    "mode": path.stat().st_mode & 0o777,
                }
            )
    # Read-only bases deliberately change modes; identity is content/path based.
    normalized = [{key: item[key] for key in ("path", "digest", "size_bytes")} for item in files]
    return digest_bytes(canonical_bytes({"schema_version": SOURCE_SCHEMA, "files": normalized}))


def manifest_content_digest(manifest: SourceManifest) -> str:
    normalized = [{key: item[key] for key in ("path", "digest", "size_bytes")} for item in manifest.files]
    return digest_bytes(canonical_bytes({"schema_version": SOURCE_SCHEMA, "files": normalized}))


def make_writable(root: Path) -> None:
    root.chmod(0o700)
    for path in root.rglob("*"):
        if path.is_dir():
            path.chmod(0o700)
        elif path.is_file():
            path.chmod((path.stat().st_mode & 0o777) | stat.S_IWUSR)


def create_sandbox(base: Path, target: Path, method: str) -> Path:
    if target.exists() or target.is_symlink():
        raise ValueError(f"sandbox target already exists: {target}")
    if method == "apfs-clone":
        completed = subprocess.run(["cp", "-cR", str(base), str(target)], capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(f"cp -cR failed: {completed.stderr.strip()}")
    elif method == "copy":
        shutil.copytree(base, target)
    else:
        raise ValueError(f"unknown sandbox method: {method}")
    make_writable(target)
    for name in ("home", "tmp", "outputs", "tool-cache"):
        (target / name).mkdir(mode=0o700)
    return target


def safe_cleanup(path: Path) -> None:
    resolved_parent = path.parent.resolve()
    temp_root = Path(os.path.realpath(os.getenv("TMPDIR", "/tmp")))
    permitted_parents = {Path("/private/tmp"), Path("/tmp"), temp_root}
    if not path.name.startswith("taskflow-e04-") or not any(
        resolved_parent == parent or parent in resolved_parent.parents for parent in permitted_parents
    ):
        raise ValueError(f"refusing to remove non-E04 temporary path: {path}")
    if path.exists() or path.is_symlink():
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o700)
            for child in path.rglob("*"):
                if not child.is_symlink():
                    child.chmod(0o700 if child.is_dir() else 0o600)
        shutil.rmtree(path)


def sandbox_profile(denied: Iterable[Path]) -> str:
    rules = ["(version 1)", "(allow default)"]
    for path in denied:
        escaped = str(path.resolve(strict=False)).replace("\\", "\\\\").replace('"', '\\"')
        rules.append(f'(deny file-read* file-write* (literal "{escaped}"))')
    return "\n".join(rules)


def sanitized_environment(sandbox: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(sandbox / "home"),
        "TMPDIR": str(sandbox / "tmp"),
        "GOCACHE": str(sandbox / "tool-cache"),
        "GOENV": "off",
        "GOTOOLCHAIN": "local",
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
    }


def run_with_profile(args: list[str], cwd: Path, env: dict[str, str], denied: Iterable[Path]) -> subprocess.CompletedProcess[str]:
    command = ["sandbox-exec", "-p", sandbox_profile(denied), *args]
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)


def run_w1(workspace: Path, peer_marker: Path) -> dict[str, Any]:
    environment = sanitized_environment(workspace)
    results: list[dict[str, Any]] = []
    commands = [["gofmt", "-l", "."], ["go", "test", "./..."], ["go", "vet", "./..."]]
    for command in commands:
        completed = run_with_profile(command, workspace, environment, [peer_marker])
        passed = completed.returncode == 0 and (command[0] != "gofmt" or completed.stdout.strip() == "")
        results.append({"command": command, "returncode": completed.returncode, "passed": passed})
        if not passed:
            raise RuntimeError(f"W1 command failed: {command}: {completed.stderr or completed.stdout}")
    probe = run_with_profile(
        [sys.executable, "-c", "from pathlib import Path; import sys; Path(sys.argv[1]).read_bytes()", str(peer_marker)],
        workspace,
        environment,
        [peer_marker],
    )
    return {"commands": results, "peer_read_denied": probe.returncode != 0, "peer_probe_returncode": probe.returncode}


def cache_key(components: dict[str, Any]) -> str:
    missing = [name for name in REQUIRED_IDENTITY_COMPONENTS if not components.get(name)]
    if missing:
        raise ValueError("missing cache identity components: " + ", ".join(missing))
    normalized = json.loads(json.dumps({name: components[name] for name in REQUIRED_IDENTITY_COMPONENTS}))
    for name in ("typed_input_manifests", "dependency_manifests"):
        normalized[name] = sorted(normalized[name], key=lambda item: canonical_bytes(item))
    environment = normalized["sandbox_policy"].get("environment")
    if isinstance(environment, list):
        normalized["sandbox_policy"]["environment"] = sorted(environment)
    return digest_bytes(canonical_bytes({"schema_version": CACHE_SCHEMA, "components": normalized}))


@dataclass(frozen=True)
class ResultEntry:
    identity: str
    content: bytes
    content_digest: str
    source_digest: str
    profile_digest: str


class ResultCache:
    def __init__(self) -> None:
        self.entries: dict[str, ResultEntry] = {}

    def put(self, entry: ResultEntry) -> None:
        self.entries[entry.identity] = entry

    def lookup(self, identity: str) -> ResultEntry | None:
        entry = self.entries.get(identity)
        if entry is None:
            return None
        if digest_bytes(entry.content) != entry.content_digest:
            raise ValueError("result content digest mismatch")
        return entry


class PersistentResultCache:
    """Tiny file-backed cache used to place benchmark state outside the timer."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, entry: ResultEntry) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        write_json(
            self.root / f"{entry.identity}.json",
            {
                "content_hex": entry.content.hex(),
                "content_digest": entry.content_digest,
                "identity": entry.identity,
                "profile_digest": entry.profile_digest,
                "source_digest": entry.source_digest,
            },
        )

    def lookup(self, identity: str) -> ResultEntry | None:
        path = self.root / f"{identity}.json"
        if not path.is_file():
            return None
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("identity") != identity:
            raise ValueError("persistent result identity mismatch")
        try:
            content = bytes.fromhex(document["content_hex"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("persistent result content is invalid") from error
        entry = ResultEntry(
            identity=identity,
            content=content,
            content_digest=document.get("content_digest", ""),
            source_digest=document.get("source_digest", ""),
            profile_digest=document.get("profile_digest", ""),
        )
        if digest_bytes(entry.content) != entry.content_digest:
            raise ValueError("result content digest mismatch")
        return entry


@dataclass
class ToolCache:
    values: dict[str, bytes] = field(default_factory=dict)


@dataclass
class WarmWorkerState:
    ready_workers: int = 0


@dataclass
class ExecutionResult:
    status: str
    identity: str
    events: list[dict[str, Any]]
    counters: dict[str, int]


def execute_cached(
    components: dict[str, Any],
    result_cache: ResultCache,
    attested_profile: str,
) -> ExecutionResult:
    events: list[dict[str, Any]] = []
    counters = {"reservations": 0, "acquisitions": 0, "sandboxes": 0, "executions": 0, "publications": 0}
    planned_profile = components["execution_profile"]["digest"]
    events.append({"kind": "resolve-profile", "digest": planned_profile})
    identity = cache_key(components)
    events.append({"kind": "compute-cache-key", "digest": identity})
    events.append({"kind": "lookup-result-cache", "identity": identity})
    entry = result_cache.lookup(identity)
    if entry is not None:
        if entry.profile_digest != planned_profile or entry.source_digest != components["source_manifest"]["digest"]:
            raise ValueError("cached result provenance mismatch")
        events.append({"kind": "verify-result", "digest": entry.content_digest})
        events.append({"kind": "return-artifact-handle", "identity": identity})
        return ExecutionResult("cache-hit", identity, events, counters)

    counters["reservations"] += 1
    events.append({"kind": "reserve-worker"})
    counters["acquisitions"] += 1
    events.append({"kind": "acquire-worker"})
    events.append({"kind": "attest-worker-profile", "expected": planned_profile, "actual": attested_profile})
    if attested_profile != planned_profile:
        events.append({"kind": "reject-attestation"})
        return ExecutionResult("attestation-mismatch", identity, events, counters)
    counters["sandboxes"] += 1
    events.append({"kind": "create-sandbox"})
    counters["executions"] += 1
    events.append({"kind": "execute"})
    return ExecutionResult("executed", identity, events, counters)


def example_identity() -> dict[str, Any]:
    return {
        "source_manifest": {"digest": "source-a"},
        "typed_input_manifests": [{"id": "input-a", "digest": "input-a-digest"}],
        "resolved_process_and_arguments": {"runner": "direct/v1", "argv": ["go", "test", "./..."]},
        "execution_profile": {"digest": "profile-a", "os": "darwin", "arch": "arm64"},
        "sandbox_policy": {"digest": "policy-a", "environment": ["LANG", "TZ"], "network": "denied"},
        "dependency_manifests": [{"id": "go-mod", "digest": "dependency-a"}],
    }


def ready_cache() -> tuple[dict[str, Any], ResultCache, str]:
    components = example_identity()
    identity = cache_key(components)
    content = b"verified-result"
    cache = ResultCache()
    cache.put(
        ResultEntry(
            identity=identity,
            content=content,
            content_digest=digest_bytes(content),
            source_digest=components["source_manifest"]["digest"],
            profile_digest=components["execution_profile"]["digest"],
        )
    )
    return components, cache, identity


def command_prepare_base(args: argparse.Namespace) -> None:
    root = Path(args.root)
    safe_cleanup(root)
    root.mkdir(parents=True)
    cas = CAS(root / "cas")
    manifest = cas.capture(Path(args.fixture))
    if manifest_content_digest(manifest) != manifest.digest:
        raise ValueError("manifest identity is inconsistent")
    cas.materialize(manifest, root / "base", read_only=True)
    print(json.dumps({"source_digest": manifest.digest, "base": str(root / "base")}, sort_keys=True))


def command_create_sandbox(args: argparse.Namespace) -> None:
    create_sandbox(Path(args.base), Path(args.target), args.method)


def command_prepare_hit(args: argparse.Namespace) -> None:
    root = Path(args.root)
    safe_cleanup(root)
    components, cache, identity = ready_cache()
    persistent = PersistentResultCache(root)
    entry = cache.lookup(identity)
    if entry is None:
        raise RuntimeError("prepared result cache entry is missing")
    persistent.put(entry)


def command_benchmark_hit(args: argparse.Namespace) -> None:
    components = example_identity()
    cache = PersistentResultCache(Path(args.cache_root))
    result = execute_cached(components, cache, components["execution_profile"]["digest"])
    if result.status != "cache-hit" or any(result.counters.values()):
        raise RuntimeError("ready hit consumed execution resources")
    if args.trace_log:
        trace = {"status": result.status, "identity": result.identity, "events": result.events, "counters": result.counters}
        path = Path(args.trace_log)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(trace, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare-base")
    prepare.add_argument("--fixture", required=True)
    prepare.add_argument("--root", required=True)
    prepare.set_defaults(func=command_prepare_base)

    create = subparsers.add_parser("create-sandbox")
    create.add_argument("--base", required=True)
    create.add_argument("--target", required=True)
    create.add_argument("--method", choices=("apfs-clone", "copy"), required=True)
    create.set_defaults(func=command_create_sandbox)

    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("--path", required=True)
    cleanup.set_defaults(func=lambda arguments: safe_cleanup(Path(arguments.path)))

    prepare_hit = subparsers.add_parser("prepare-cache-hit")
    prepare_hit.add_argument("--root", required=True)
    prepare_hit.set_defaults(func=command_prepare_hit)

    hit = subparsers.add_parser("benchmark-cache-hit")
    hit.add_argument("--cache-root", required=True)
    hit.add_argument("--trace-log")
    hit.set_defaults(func=command_benchmark_hit)

    arguments = parser.parse_args()
    arguments.func(arguments)


if __name__ == "__main__":
    main()
