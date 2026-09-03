# W3 isolated native-mobile stack fixture

Roadmap tranche: T1. Workflow: W3. Tasks: TF-002.03, TF-003.05.

Fixture id: `w3-isolated-native-mobile-stack`. Version: `t1-w3-fixture-v1-experimental`
(roadmap section 3 rule 3a: this fixture is frozen and reusable, not
disposable, and declares an explicit experimental version; it must be
treated as pre-Gate-1 and may change incompatibly). Every example under
`examples/` carries these same `fixture_id`/`version` keys, matching the
convention `fixtures/w1/manifest.yaml` and `fixtures/w2/graph.json` use.

## Status: specification only

**No W3 infrastructure exists in this repository.** There is no macOS
provider, no Xcode/simulator integration, no namespace/service runtime, and
no endpoint-routing implementation anywhere in `prototype/bootstrap` or
elsewhere (verified by grep across the prototype module; the prototype
demonstrates none of W3). This fixture is therefore a **golden specification
for what E06 (macOS/Xcode/simulator feasibility) and E07
(namespace-private services and cross-target endpoints) must eventually
produce**, not a fixture that runs today. Every field below is modeled and
aspirational unless explicitly marked otherwise. Nothing here implies E06 has
passed or that any macOS feasibility branch has been chosen — those decisions
are still open (roadmap section 9, section 10 Gate 1).

Do not build against this fixture as if it were a stable contract. It exists
so E06/E07 have a concrete, versioned target to validate against and diverge
from with evidence, per roadmap section 2.3 ("Keep experiments disposable")
and 2.6 ("Defer compatibility until the model earns it").

## W3 shape (roadmap section 4)

```text
source -> Linux database/API stack -> Endpoint[API]
source -> macOS Xcode build ---------> Artifact[IOSApp]
Endpoint + IOSApp + simulator -------> Report[MobileE2E]
```

This fixture models the source input and every node/edge of that shape as
records, one instance per namespace - including the two `source ->` build
edges, not only their output artifacts:

| Node/edge | Record field | Example file |
| --- | --- | --- |
| `source` (immutable source tree) | `source` | `examples/namespace-{a,b}.json` |
| source -> Linux database/API stack (build edge) | `linux_api_service.produced_by` (`node: "linux-api-build"`, `consumes: <source id>`) | `examples/namespace-{a,b}.json` |
| Linux database/API stack -> Endpoint[API] | `endpoint` | `examples/namespace-{a,b}.json` |
| source -> macOS Xcode build (build edge) | `macos_artifact.produced_by` (`node: "macos-xcode-build"`, `consumes: <source id>`) | `examples/namespace-{a,b}.json` |
| macOS Xcode build -> Artifact[IOSApp] | `macos_artifact` | `examples/namespace-{a,b}.json` |
| simulator | `simulator_session` | `examples/namespace-{a,b}.json` |
| Endpoint + IOSApp + simulator -> Report[MobileE2E] | `mobile_e2e_report`, declaring the consuming operation identity and referencing the endpoint/artifact/simulator ids it consumes | `examples/namespace-{a,b}.json` |

`validate.sh` enforces every declared edge referentially. Each namespace's
`linux_api_service.produced_by.consumes` and
`macos_artifact.produced_by.consumes` must equal that namespace's own
`source.id`; `linux_api_service.endpoint_id` must equal its local
`endpoint.id`; and `mobile_e2e_report.consumes` must contain exactly once each
of the local endpoint, artifact, and simulator ids. Endpoint target namespace
and simulator lease holder must equal the record's owning `namespace_id`.

## Two-namespace concurrency (AC #2)

`examples/namespace-a.json` and `examples/namespace-b.json` model two
concurrent worktree/agent namespaces running W3 at once. Every identifier
that must not collide between them is deliberately distinct in the two
examples:

- `namespace_id`
- `source.id`
- `writable_root` (`/var/lib/taskflow/namespaces/ns-a` vs `ns-b`)
- `linux_api_service.name`
- `linux_api_service.port` (`41001` vs `41002`)
- `linux_api_service.database_path`
- `endpoint.id`
- `macos_artifact.id`
- `simulator_session.id` and `simulator_session.lease.id`
- `mobile_e2e_report.id` and `mobile_e2e_report.consumer_id`

`validate.sh` checks this list is actually distinct across all namespace
examples, not merely asserted in prose. Identifier values are also unique
across identifier kinds: an artifact id cannot silently reuse an endpoint id,
for example. Every database path is a normalized absolute descendant of its
own writable root, and no writable root or database path may equal, contain,
or be contained by a path belonging to another namespace.

`endpoint.authorized_consumers` in each namespace lists only that namespace's
own consumer (`ns-a-ios-e2e` / `ns-b-ios-e2e`), now declared explicitly as
`mobile_e2e_report.consumer_id`. The validator requires the authorization list
to resolve exactly once to that local identity and requires `endpoint.route`
to remain `namespace-private`. This is the explicit authorization relationship
required by roadmap section 4; it is not a runtime authorization mechanism.

`macos_artifact.profile_attestation` is required to be an object, but its
contents are deliberately opaque. The current illustrative fields are marked
`"modeled-not-attested"`; E06 still owns the provider and attestation contract.

## Typed fixture envelope and diagnostics

Namespace records require typed, non-empty values for the fields and nested
objects shown by the W3 shape. Ports and lease TTLs are positive integers
(JSON booleans are rejected), identifier collections contain non-empty
strings, and malformed nesting produces validation diagnostics rather than
Python exceptions.

Diagnostics have the stable form:

```text
<file>: <semantic field>: [<invariant code>] namespace=<owner> <detail>
```

Collision diagnostics additionally identify the conflicting semantic field,
file, and namespace. Diagnostics are sorted, so the same invalid fixture tree
produces the same output regardless of filesystem iteration order.

## Fault and test scenarios (AC #3)

Each scenario in `examples/scenario-*.json` is a golden record with a
`given` state and an ordered `expected_events` list an eventual
implementation's event stream should satisfy (subsequence match, not
necessarily exact adjacency — later T-tranches decide exact event-stream
semantics).

| Scenario file | Roadmap requirement covered | Expected outcome |
| --- | --- | --- |
| `scenario-port-collision.json` | "two ... namespaces run concurrently without data or port collision" | `rejected` |
| `scenario-unauthorized-routing.json` | "Linux-to-macOS endpoint routing is explicit and authorized" | `denied` |
| `scenario-cancellation.json` | "cleanup survives cancellation and caller loss" (cancellation half) | `cleaned_up_within_deadline` |
| `scenario-caller-loss.json` | "cleanup survives cancellation and caller loss" (caller-loss half) | `reclaimed` |
| `scenario-dirty-warm-infrastructure.json` | "warm infrastructure is reused without sharing semantic state" | `reset_before_reuse` |
| `scenario-simulator-profile-mismatch.json` | "macOS profile and simulator identity are attested" | `rejected` |

## What this fixture deliberately does not do

- It does not implement, launch, or simulate any macOS VM, Xcode build, or
  iOS simulator. There is nothing to execute.
- It does not choose among E06's warm-VM/per-namespace-VM/native-host/remote
  branches (roadmap section 9); the fixture is written to be branch-neutral
  so any E06 outcome can be checked against it.
- It does not define a Go type, wire schema, or plan IR for these concepts.
  Per roadmap section 3 rule 3a and section 24 item 8, no such contract may
  stabilize before Gate 1. The examples are plain JSON specifically to avoid
  implying a typed contract.
- It does not cover W1 or W2 (see the sibling `fixtures/w1/` and
  `fixtures/w2/` fixtures, TF-002.01/TF-002.02).

## Verification

```sh
fixtures/w3/validate.sh
```

Dependency-free (uses only `python3`'s standard-library `json` module).
The command first runs `test_validate.py`, whose table-driven cases copy the
canonical examples to a temporary directory and inject one invalid mutation at
a time. Those mutations cover required/type failures, dangling or foreign
links, unauthorized consumers, ownership violations, incomplete/duplicate
report inputs, route and path confinement, every declared collision category,
and cross-kind identifier reuse. Each case must fail with the expected stable
invariant code and contextual diagnostic. The command then validates the
untouched canonical examples with the same `validate.py` entry point.

Scenario records receive only generic envelope validation: non-empty string
metadata, an object-valued `given`, and a non-empty object list of expected
events with a non-empty string `event`. This validates the specification's
internal consistency; it does not validate against real W3 infrastructure.
Every `examples/*.json` file must be classified by the accepted
`namespace-*.json` or `scenario-*.json` naming contract; an unrecognized JSON
example fails with `W3-FILESET` instead of being silently skipped.

## Limitations and open questions

- Every identifier, path, and port number in the examples is illustrative,
  not a reserved or required literal value. A future implementation is free
  to choose its own naming scheme as long as the *properties* above hold
  (no collision, explicit authorization, bounded cleanup, reset-before-reuse,
  attested identity).
- `expected_events` names (e.g. `service.bind.rejected`,
  `orphan.reclaimed`) are illustrative event-name conventions, not a frozen
  event vocabulary. T4/T8 will define the real lifecycle-event schema
  (roadmap sections 13, 17).
- Scenario-specific `given`, event payload fields, ordering, and outcome values
  remain opaque. Likewise, the validator does not inspect provider-specific
  `profile_attestation` contents. This prevents a T1 fixture validator from
  pre-empting E06/E07, T4, or T8 contract decisions.
- This fixture cannot distinguish "E06 concludes native macOS execution is
  infeasible" (roadmap section 9 E06 branch "No approach isolates concurrent
  agents") from a fixture defect, because there is no running system to
  compare against yet. When E06/E07 produce real evidence, this fixture
  should be revisited and either graduated (kept and referenced by an
  accepted decision, per roadmap section 3 rule 3a) or revised with the new
  evidence.
- Open question for TF-002.09 (T1 exit convergence): whether `fixtures/w1/`,
  `fixtures/w2/`, and `fixtures/w3/` should share a common top-level
  event-vocabulary or record-format convention. This fixture intentionally
  does not presume one, to avoid inventing a shared contract outside its own
  ownership (AGENTS.md: "Coordinate shared contracts through the owning
  ticket").
