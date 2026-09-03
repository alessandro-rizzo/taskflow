#!/usr/bin/env python3
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve()
TRIALS = SCRIPT.parents[1]


def main() -> None:
    roots = [TRIALS / "results", TRIALS / "setup-failures"]
    count = 0
    for root in roots:
        for transcript in sorted(root.rglob("transcript.jsonl")):
            raw = transcript.read_text()
            raw_path = transcript.with_name("transcript.raw.log")
            if not raw_path.exists():
                raw_path.write_text(raw)
            events = []
            for line in raw.splitlines():
                if not line.startswith("{"):
                    continue
                json.loads(line)
                events.append(line)
            if not events:
                raise SystemExit(f"no JSON events in {transcript}")
            transcript.write_text("\n".join(events) + "\n")
            count += 1
    print(f"normalize-transcripts: PASS {count}")


if __name__ == "__main__":
    main()
