#!/usr/bin/env bash
# T1 W3 fixture validator (TF-002.03). Dependency-free (uses python3's json
# module, no third-party tools). Checks every example under fixtures/w3/examples/
# is well-formed JSON and carries the fields spec.md declares required for its
# kind (namespace record vs. fault-scenario record). This is specification
# validation, not execution against real infrastructure - none exists yet.
set -euo pipefail

cd "$(dirname "$0")/examples"

fail=0

check_common() {
  python3 - "$1" <<'PY'
import json, sys
path = sys.argv[1]
with open(path) as f:
    doc = json.load(f)
for field in ("fixture_version", "status"):
    if field not in doc:
        print(f"{path}: missing required field '{field}'")
        sys.exit(1)
if doc["fixture_version"] != "t1-w3-fixture-v0-experimental":
    print(f"{path}: unexpected fixture_version {doc['fixture_version']!r}")
    sys.exit(1)
if doc["status"] != "specification-only":
    print(f"{path}: unexpected status {doc['status']!r}")
    sys.exit(1)
PY
}

check_namespace() {
  python3 - "$1" <<'PY'
import json, sys
path = sys.argv[1]
with open(path) as f:
    doc = json.load(f)
for field in ("namespace_id", "writable_root", "linux_api_service", "endpoint",
              "macos_artifact", "simulator_session", "mobile_e2e_report"):
    if field not in doc:
        print(f"{path}: missing required namespace field '{field}'")
        sys.exit(1)
PY
}

check_scenario() {
  python3 - "$1" <<'PY'
import json, sys
path = sys.argv[1]
with open(path) as f:
    doc = json.load(f)
for field in ("scenario", "description", "given", "expected_events", "expected_outcome"):
    if field not in doc:
        print(f"{path}: missing required scenario field '{field}'")
        sys.exit(1)
if not isinstance(doc["expected_events"], list) or not doc["expected_events"]:
    print(f"{path}: expected_events must be a non-empty list")
    sys.exit(1)
for event in doc["expected_events"]:
    if "event" not in event:
        print(f"{path}: expected_events entry missing 'event' field: {event!r}")
        sys.exit(1)
PY
}

for f in namespace-*.json; do
  echo "checking $f"
  check_common "$f" || fail=1
  check_namespace "$f" || fail=1
done

for f in scenario-*.json; do
  echo "checking $f"
  check_common "$f" || fail=1
  check_scenario "$f" || fail=1
done

if [ "$fail" -ne 0 ]; then
  echo "FAIL: one or more fixture examples failed validation"
  exit 1
fi

echo "PASS: all fixtures/w3/examples/*.json are well-formed and complete"
