# ADR 0011: E07 typed namespace-private services with explicit provider routing

Status: accepted

Question: can Taskflow reproduce W3-style service stacks per namespace without
exposing ports, provider networking, authorization details, or mutable service
state in normal project code?

Decision date: 2026-09-04

Task: TF-003.15. Roadmap references: E07 namespace-private services and
endpoint routing, W3 isolated native plus mobile stack, and Gate 1.

## Context

TF-003.15 froze a result-free E07 contract at commit `7a61d88` before adding
the disposable experiment. The frozen branch order first stops on any safety
failure, then prefers a transport-neutral typed endpoint manager, and then
permits explicit provider routing only when every hard gate passes but the
fake-macOS target requires a provider-specific route capability hidden behind
its adapter.

Phase B used Python 3.9 standard-library processes bound only to OS-assigned
loopback ports, namespace-private SQLite service databases, and a controller
with SQLite WAL/FULL lifecycle state. It ran no Compose runtime, VM,
simulator, physical device, external provider, public listener, shared
runtime, production package, or prototype import.

## Predeclared gates and results

| Gate | Frozen threshold | Accepted result |
| --- | --- | --- |
| Namespace isolation | 20 simultaneous pairs; zero identity collisions, peer-state access, cross-namespace endpoint success, or project-visible provider detail | pass; every count zero |
| Endpoint authorization | 20 repetitions of each of 6 denial classes; zero unauthorized success, connection/credential disclosure, or provider connection before authorization | pass; 120/120 denied with exact diagnostics, direct guessed credentials rejected, and every count zero |
| Readiness | 30 serial samples, p95 < 1 s; no route before healthy committed readiness; slow/unhealthy/exit drain <= 2 s | pass; p95 0.0841 s, fault drain max 0.2592 s, ordering counts zero |
| Caller-loss cleanup | 20 trials; expiry lateness <= 0.5 s; cleanup p95 <= 1 s and max <= 2 s; zero residue | pass; lateness max 0.1107 s, cleanup p95 0.0614 s and max 0.0642 s, residue zero |
| Crash/restart cleanup | before/after each of 4 stages; zero committed-event loss, duplication, or reorder | pass; all 8 cases, every count zero |
| Immutable reuse | 3 namespaces; one artifact digest/publication; zero mutable/process/route/capability reuse or prior marker visibility | pass; all counts exact |
| Routing overhead | 30 alternating pairs; authorized resolution p95 < 0.025 s; fake-macOS incremental p95 <= 0.01 s | pass; 0.01205 s and 0.000655 s |

The first complete evidence set passed the service gates but was rejected by
the verifier because scheduler noise produced negative relay-minus-direct
values, which the bound T1 v2 duration schema forbids. The set is retained in
`experiments/e07-namespace-services/evidence-failed/run-1-invalid-signed-delta/`.
The documented mechanical correction retained signed observations in raw
JSONL, used non-negative incremental overhead for the T1 record, changed no
threshold or decision rule, and restarted the entire workload from sample
one.

That second set also passed the numeric verifier but final plan review found
that it had not explicitly probed a guessed direct-loopback credential or the
slow-health timeout. It is retained at
`evidence-failed/run-2-incomplete-adversarial-coverage/` and excluded. The
final accepted set added those observations without changing the contract and
again restarted the entire workload from sample one.

## Decision

**Retain typed namespace-private Service and Endpoint concepts, with
cross-target routing represented as an explicit typed provider capability.**

All hard gates passed, and the project-visible requests contained only source,
service type, endpoint type, and consumer identity. Ports, credentials,
provider options, writable roots, database paths, and process details remained
inside the experiment controller. However, the fake-macOS route needed a
provider-specific relay capability. Under the frozen precedence this excludes
the transport-neutral manager branch and selects `explicit-provider-routing`.

The provider capability must be authorized against endpoint type, endpoint
identity, namespace, consumer, handle capability, lease liveness, and provider
identity before connection details are returned or a provider route can be
created. Readiness must be health-confirmed and durably committed before
routing. Lease expiry and caller loss must revoke routes, stop services,
remove mutable state, and finalize the lease in that order, with restart-safe
idempotence.

This is evidence for Gate 1, not permission to stabilize the experiment code
or its schemas.

## Evidence

- Frozen contract and digest:
  `experiments/e07-namespace-services/{contract.json,thresholds.json,decision-matrix.json,event-schema.json,frozen-artifacts.json,protocol.sha256}`.
- Sanitized raw traces: `experiments/e07-namespace-services/evidence/raw/`.
- Mechanical verdict and summaries:
  `experiments/e07-namespace-services/evidence/{scorecard.json,authorization-matrix.json,readiness-summary.json,cleanup-summary.json,namespace-leak-collision-report.json}`.
- T1 v2 records and raw samples:
  `experiments/e07-namespace-services/evidence/benchmarks/`.
- Environment, exact command, checksums, implementation binding, evidence
  binding, limitations, and recommendation:
  `experiments/e07-namespace-services/evidence/`.
- Verification:
  `mise exec -- task --taskfile experiments/e07-namespace-services/PhaseBTaskfile.yml check`.

## Consequences and limitations

- Gate 1 may consider typed `Service[T]` and `Endpoint[T]` values, owner-held
  opaque capabilities, readiness-gated routing, lease-owned cleanup, and an
  explicit provider-routing leaf.
- Normal project code must not name ports, hosts, route credentials, provider
  options, mutable roots, databases, or processes.
- Immutable service artifacts may be content-addressed and reused; mutable
  namespace state, processes, route instances, and credentials may not.
- Same-host Darwin processes are not OS namespaces. The fake-macOS relay is
  not a real macOS provider, simulator, network boundary, or physical device.
- One-second local leases and local SQLite do not establish distributed
  consistency, production recovery bounds, or long-duration operating
  behavior.
- The experiment implementation, formats, diagnostics, and APIs remain
  disposable. No production module or public compatibility promise is
  established before Gate 1.
- Compose remains untested and receives no fallback credit; exercising it
  requires separate explicit approval and the identical hard gates.

## Revisit when

- a real heterogeneous provider cannot keep route capability details behind
  its adapter or cannot meet the same authorization and cleanup gates;
- process-level isolation proves insufficient for secrets, writable state, or
  cross-namespace network boundaries;
- distributed controller state cannot preserve cleanup order and idempotence
  across restart;
- realistic service startup, provider routing, or longer leases fail the
  frozen latency and cleanup shape; or
- Gate 1 changes the typed endpoint, namespace-owner, or provider-capability
  model.

## Contracts now allowed to stabilize

None. The typed concepts and trust-boundary rules above are Gate 1 inputs
only; no experiment source, Python API, JSON format, SQLite schema, route
transport, diagnostic code, or public package may stabilize from E07 alone.
