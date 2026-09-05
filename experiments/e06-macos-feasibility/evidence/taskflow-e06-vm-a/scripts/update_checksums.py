#!/usr/bin/env python3
"""Regenerate the deterministic E06 retained-evidence checksum manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "checksums.json"


def main() -> None:
    entries = []
    for path in sorted(item for item in ROOT.rglob("*") if item.is_file()):
        relative = path.relative_to(ROOT).as_posix()
        if relative == "checksums.json" or relative.startswith("scripts/") or relative.startswith("tests/"):
            continue
        entries.append({"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    MANIFEST.write_text(
        json.dumps({"format_version": "taskflow-e06-vm-evidence-checksums/v1", "entries": entries}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
