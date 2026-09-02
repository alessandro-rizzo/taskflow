# W3 isolated native-mobile stack fixture

Roadmap tranche: T1. Workflow: W3. Task: TF-002.03.

Fixture format version: `t1-w3-fixture-v0-experimental` (roadmap section 3
rule 3a: this fixture is frozen and reusable, not disposable, and declares an
explicit experimental version; it must be treated as pre-Gate-1 and may
change incompatibly).

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

This fixture models the five nodes/edges of that shape as records, one
instance per namespace:

| Node/edge | Record field | Example file |
| --- | --- | --- |
| Linux database/API stack | `linux_api_service` | `examples/namespace-{a,b}.json` |
| Endpoint[API] | `endpoint` | `examples/namespace-{a,b}.json` |
| macOS Xcode build -> Artifact[IOSApp] | `macos_artifact` | `examples/namespace-{a,b}.json` |
| simulator | `simulator_session` | `examples/namespace-{a,b}.json` |
| Report[MobileE2E] | `mobile_e2e_report`, referencing the endpoint/artifact/simulator ids it consumes | `examples/namespace-{a,b}.json` |

## Two-namespace concurrency (AC #2)

`examples/namespace-a.json` and `examples/namespace-b.json` model two
concurrent worktree/agent namespaces running W3 at once. Every identifier
that must not collide between them is deliberately distinct in the two
examples:

- `writable_root` (`/var/lib/taskflow/namespaces/ns-a` vs `ns-b`)
- `linux_api_service.port` (`41001` vs `41002`)
- `linux_api_service.database_path`
- `endpoint.id`
- `macos_artifact.id`
- `simulator_session.id` and `simulator_session.lease.id`

`endpoint.authorized_consumers` in each namespace lists only that namespace's
own consumer (`ns-a-ios-e2e` / `ns-b-ios-e2e`) — this is the explicit
authorization model required by roadmap section 4's "Linux-to-macOS endpoint
routing is explicit and authorized." `macos_artifact.profile_attestation`
fields are marked `"modeled-not-attested"`: this fixture specifies the shape
of an attestation record without asserting E06 has built an attestation
mechanism.

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
Checks every `examples/*.json` file is well-formed and contains the fields
this document declares required for its kind (namespace record vs. scenario
record). This validates the specification's internal consistency; it does
not and cannot validate against real W3 infrastructure, because none exists
yet.

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
