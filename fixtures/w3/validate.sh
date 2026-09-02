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
for field in ("fixture_id", "version", "status"):
    if field not in doc:
        print(f"{path}: missing required field '{field}'")
        sys.exit(1)
if doc["fixture_id"] != "w3-isolated-native-mobile-stack":
    print(f"{path}: unexpected fixture_id {doc['fixture_id']!r}")
    sys.exit(1)
if doc["version"] != "t1-w3-fixture-v0-experimental":
    print(f"{path}: unexpected version {doc['version']!r}")
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
for field in ("namespace_id", "writable_root", "source", "linux_api_service", "endpoint",
              "macos_artifact", "simulator_session", "mobile_e2e_report"):
    if field not in doc:
        print(f"{path}: missing required namespace field '{field}'")
        sys.exit(1)

# Referential integrity: the source->build edges (AC #1) must actually point
# at this namespace's own source record, not a dangling or foreign id.
source_id = doc["source"]["id"]
for producer_field in ("linux_api_service", "macos_artifact"):
    produced_by = doc[producer_field].get("produced_by")
    if not produced_by or "node" not in produced_by or "consumes" not in produced_by:
        print(f"{path}: {producer_field}.produced_by must declare 'node' and 'consumes'")
        sys.exit(1)
    if produced_by["consumes"] != source_id:
        print(f"{path}: {producer_field}.produced_by.consumes {produced_by['consumes']!r} "
              f"does not match this namespace's source id {source_id!r}")
        sys.exit(1)

# mobile_e2e_report.consumes must reference ids that actually exist in this
# same namespace record (endpoint/artifact/simulator), not arbitrary strings.
known_ids = {
    doc["endpoint"]["id"],
    doc["macos_artifact"]["id"],
    doc["simulator_session"]["id"],
}
for consumed in doc["mobile_e2e_report"]["consumes"]:
    if consumed not in known_ids:
        print(f"{path}: mobile_e2e_report.consumes references unknown id {consumed!r}")
        sys.exit(1)
PY
}

check_cross_namespace_uniqueness() {
  python3 - "$@" <<'PY'
import json, sys
paths = sys.argv[1:]
docs = [json.load(open(p)) for p in paths]
if len(docs) < 2:
    sys.exit(0)

def collect_ids(doc):
    return {
        "writable_root": doc["writable_root"],
        "linux_api_service.port": doc["linux_api_service"]["port"],
        "linux_api_service.database_path": doc["linux_api_service"]["database_path"],
        "endpoint.id": doc["endpoint"]["id"],
        "macos_artifact.id": doc["macos_artifact"]["id"],
        "simulator_session.id": doc["simulator_session"]["id"],
        "simulator_session.lease.id": doc["simulator_session"]["lease"]["id"],
        "source.id": doc["source"]["id"],
    }

per_doc = [collect_ids(d) for d in docs]
fail = False
for key in per_doc[0]:
    values = [ids[key] for ids in per_doc]
    if len(set(values)) != len(values):
        print(f"cross-namespace collision on {key!r}: {values}")
        fail = True
if fail:
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

echo "checking cross-namespace uniqueness (AC #2)"
check_cross_namespace_uniqueness namespace-*.json || fail=1

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
