#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
import shutil
import subprocess


TEMP_ROOT = Path("/tmp/taskflow-e01-tf00307")


def candidate_root(candidate: str) -> Path:
    if candidate not in {"A", "B", "C", "D"}:
        raise SystemExit(f"unsupported candidate {candidate!r}")
    root = TEMP_ROOT / candidate
    root.mkdir(parents=True, exist_ok=True)
    return root


def reset_dir(target: Path) -> None:
    target = target.resolve()
    allowed = TEMP_ROOT.resolve()
    if target == allowed or allowed not in target.parents:
        raise SystemExit(f"refusing to reset path outside {allowed}: {target}")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)


def remove_file(target: Path) -> None:
    target = target.resolve()
    allowed = TEMP_ROOT.resolve()
    if allowed not in target.parents:
        raise SystemExit(f"refusing to remove path outside {allowed}: {target}")
    if target.exists():
        if not target.is_file():
            raise SystemExit(f"expected file: {target}")
        target.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("go-cold-build", "go-warm-build", "bun-cold-discovery", "typescript-cold-check", "typescript-warm-check"))
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--entrypoint")
    args = parser.parse_args()
    root = candidate_root(args.candidate)

    if args.mode == "go-cold-build":
        reset_dir(root / "go-cold-build-cache")
        remove_file(root / "cold-build-driver")
        return
    if args.mode == "go-warm-build":
        if not args.entrypoint:
            raise SystemExit("--entrypoint is required for go-warm-build")
        cache = root / "go-warm-build-cache"
        cache.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["GOCACHE"] = str(cache)
        subprocess.run(["go", "build", "-o", str(root / "warm-prep-driver"), args.entrypoint], check=True, env=env)
        remove_file(root / "warm-build-driver")
        return
    if args.mode == "bun-cold-discovery":
        reset_dir(root / "bun-cold-transpiler-cache")
        return
    if args.mode == "typescript-cold-check":
        if any(Path.cwd().glob("*.tsbuildinfo")):
            raise SystemExit("unexpected persistent TypeScript build info in non-incremental candidate")
        subprocess.run(["bun", "install", "--frozen-lockfile"], check=True, stdout=subprocess.DEVNULL)
        return
    if args.mode == "typescript-warm-check":
        env = dict(os.environ)
        env["BUN_RUNTIME_TRANSPILER_CACHE_PATH"] = "0"
        subprocess.run(["bun", "run", "typecheck"], check=True, stdout=subprocess.DEVNULL, env=env)


if __name__ == "__main__":
    main()
