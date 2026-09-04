#!/usr/bin/env python3
"""Short-lived caller used to prove lease cleanup after caller loss."""

from __future__ import annotations

import argparse
import threading
from pathlib import Path

from harness import rpc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    parser.add_argument("--namespace", required=True)
    args = parser.parse_args()
    waiter = threading.Event()
    while True:
        result = rpc(Path(args.socket), {"command": "heartbeat", "namespace_id": args.namespace})
        if not result.get("ok"):
            return 1
        waiter.wait(0.25)


if __name__ == "__main__":
    raise SystemExit(main())
