#!/usr/bin/env python3
"""Materialize the allowlisted, sanitized E06 VM smoke evidence subset."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


ATTEMPTS = {
    "attempt-001": {
        "source": "smoke-run",
        "source_digest": "c7e89d3417f2cd1be24d72909928a3894244a2282f61d8c00585d74a5f28aa03",
        "source_file_count": 146,
        "source_du_kib": 724,
        "records": {"launch.json": "0037.json"},
    },
    "attempt-002": {
        "source": "smoke-run-002",
        "source_digest": "7911622d78c44e4755597a4009039f42795733ba01b2e78bf09b766b02822f38",
        "source_file_count": 153,
        "source_du_kib": 744,
        "records": {
            "launch-initial.json": "0037.json",
            "launch-persisted.json": "0039.json",
        },
    },
    "attempt-003": {
        "source": "smoke-run-003",
        "source_digest": "882df5a27fa2d6bdfff04c9c2dbad115a900c7741776801b0ea0bd60512f0473",
        "source_file_count": 118,
        "source_du_kib": 652,
        "records": {"signing-inspection.json": "0029.json"},
    },
}

UUID = re.compile(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b")
USER_PATH = re.compile(r"/Users/[^/\\\s]+")
RECEIPTS_DIGEST = "0d2dabb94f8adec914d0c53e1228181f4ed694958d05e130adf02ed271cedadd"


def source_digest(root: Path) -> str:
    payload = b""
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        payload += f"{digest}  {path}\n".encode()
    return hashlib.sha256(payload).hexdigest()


def sanitize(value):
    if isinstance(value, str):
        return USER_PATH.sub("/Users/<redacted>", UUID.sub("<redacted-device-id>", value))
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize(item) for key, item in value.items()}
    return value


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sanitize(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sanitize(value), encoding="utf-8")


def exactly_one(root: Path, pattern: str) -> Path:
    matches = sorted(root.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected one {pattern} beneath {root}, found {len(matches)}")
    return matches[0]


def signing_excerpt(build_log: Path, inspection: Path) -> dict:
    lines = build_log.read_text(encoding="utf-8").splitlines()
    interesting = [
        line.strip()
        for line in lines
        if "application-identifier" in line
        or line.strip().startswith("/usr/bin/codesign --force")
        or line.strip().startswith("ProcessProductPackaging \"")
        or line.strip().startswith("CodeSign ")
    ]
    return {
        "build_exit_code": 0,
        "build_log_excerpt": interesting,
        "interpretation": "Xcode generated an intermediate application identifier, but the logged codesign command did not attach an entitlements file.",
        "signing_inspection": load_json(inspection),
    }


def materialize(source_root: Path, output_root: Path) -> None:
    if output_root.exists():
        raise RuntimeError(f"refusing to overwrite retained evidence: {output_root}")
    output_root.mkdir(parents=True)
    for attempt, spec in ATTEMPTS.items():
        source = source_root / spec["source"]
        files = [path for path in source.rglob("*") if path.is_file()]
        if len(files) != spec["source_file_count"]:
            raise RuntimeError(f"{attempt}: source file count drifted")
        if source_digest(source) != spec["source_digest"]:
            raise RuntimeError(f"{attempt}: source digest drifted")

        target = output_root / attempt
        target.mkdir()
        common = {
            "approval.json": source / "approval.json",
            "failure.json": source / "failure.json",
            "cleanup.json": exactly_one(source, "cleanup-*.json"),
        }
        bases = sorted(source.glob("base-hashes-*.json"), key=lambda path: int(path.stem.rsplit("-", 1)[1]))
        if len(bases) != 2:
            raise RuntimeError(f"{attempt}: expected two base hash records")
        common["base-hashes-before.json"] = bases[0]
        common["base-hashes-after.json"] = bases[1]
        for destination, original in {**common, **{name: source / value for name, value in spec["records"].items()}}.items():
            write_json(target / destination, load_json(original))
        if attempt == "attempt-003":
            write_json(target / "build-signing.json", signing_excerpt(source / "0028.stdout", source / "0029.json"))
        write_json(
            target / "source-summary.json",
            {
                "retention": "allowlisted-sanitized-subset",
                "source_digest_algorithm": "sha256 of sorted '<file sha256><two spaces><absolute path><newline>' records",
                "source_directory": str(source),
                "source_du_kib": spec["source_du_kib"],
                "source_file_count": spec["source_file_count"],
                "source_sha256": spec["source_digest"],
            },
        )

    receipts = source_root / "receipts"
    receipt_files = sorted(path for path in receipts.rglob("*") if path.is_file())
    if len(receipt_files) != 23 or source_digest(receipts) != RECEIPTS_DIGEST:
        raise RuntimeError("setup receipt source drifted")
    setup = output_root / "setup"
    setup.mkdir()
    for source in receipt_files:
        destination = setup / source.name
        if source.suffix == ".json":
            write_json(destination, load_json(source))
        else:
            write_text(destination, source.read_text(encoding="utf-8"))
    write_json(
        setup / "source-summary.json",
        {
            "retention": "complete-sanitized-setup-receipts",
            "source_digest_algorithm": "sha256 of sorted '<file sha256><two spaces><absolute path><newline>' records",
            "source_directory": str(receipts),
            "source_du_kib": 136,
            "source_file_count": 23,
            "source_sha256": RECEIPTS_DIGEST,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=Path("/private/tmp/taskflow-e06-vm-a"))
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    materialize(args.source_root, args.output_root)


if __name__ == "__main__":
    main()
