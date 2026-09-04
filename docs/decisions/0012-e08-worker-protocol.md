# ADR 0012: E08 worker protocol remains state-machine-first

Status: accepted

Question: which E08 worker-protocol branch should inform Gate 1: stop or
narrow, state-machine-first transport deferral, separated worker/sandbox/session
protocols, or one typed core with capability extensions?

Decision date: 2026-09-04

Task: TF-003.16. Roadmap references:
[E08 minimal remote worker protocol](../roadmap.md#e08-minimal-remote-worker-protocol)
and [Gate 1](../roadmap.md#10-gate-1-product-and-architecture-convergence).

## Context

E08 froze its state machines, typed experimental envelopes, thresholds, fault
matrix, SSH approval boundary, and branch precedence at commit
`fe41c6428c4d7d432cdd463c82dd12c3465e1103` before Phase B implementation.
The approved Phase B scope implemented one disposable typed controller, a real
in-process adapter, and an E06-shaped in-memory macOS stub. The stub retains
separate reusable-worker, disposable-sandbox, and optional namespace-session
identities without calling Xcode, `simctl`, a VM, the filesystem, or a provider.

No approved SSH availability manifest or representative Linux endpoint was
available. The experiment made zero SSH connections and did not inspect SSH
configuration or credentials. It therefore has no evidence for remote Linux
admission, host-key and credential mediation, reconnect framing, remote process
ownership, or remote cleanup.

## Options considered

1. Stop or narrow remote execution if a correctness, integrity, ownership,
   publication, cleanup, or orphan-accounting hard gate fails, or if no
   credible remote-worker path remains.
2. Defer transport while retaining the state and ownership semantics when the
   local core passes but representative SSH/Linux evidence is absent or
   transport behavior dominates.
3. Separate worker, sandbox, and session protocols if the E06 macOS lifecycle
   cannot preserve stateless execution semantics without leakage.
4. Carry one typed core with capability extensions if all three shapes pass
   every hard gate without provider-option or forced-session leakage.

The frozen order above is conjunctive and unweighted.

## Predeclared thresholds and evidence

The frozen contract requires 30 cache-hit samples per adapter below 300 ms at
p95 with zero capacity/resource work; 30 `TryReserve` samples at or below 100
ms maximum while acquisition is deliberately delayed; five cancellation
acknowledgement samples at or below one second maximum; and five bounded
cleanup samples at or below 30 seconds maximum or an exact orphan. A separate
30-sample warm SSH/Linux admission gate requires p95 below two seconds,
excluding declared queue time. Every fault case requires five repetitions per
adapter and all correctness counters remain zero-tolerance.

Evidence is under `experiments/e08-worker-protocol/evidence/`:

- `scorecard.json` records the mechanical branch evaluation and local timing
  results;
- `raw/` retains ten rows per fault case for the two approved adapter shapes,
  with executable/typed-core and state-machine-analysis strength explicitly
  distinguished;
- `benchmarks/` retains T1 benchmark-v2 records and raw samples;
- `implementation-manifest.json` and `manifest.json` bind implementation and
  evidence bytes; and
- `limitations.md` states the untested boundaries.

The applicable local measurements and executable/typed-core assertions pass.
Ready hits perform zero reservation or other resource work; attestation
precedes sandbox/session creation; immutable bytes are digest-checked before
use; publication uses compare-and-swap; operation replay is idempotent;
log replay verifies cursor order and byte digests; cancellation runs detached
bounded cleanup; and exact orphan query/reconciliation is exercised. Analysis-
only rows are not treated as implemented transport fault evidence.

## Decision

**Select state-machine-first transport deferral.** This is precedence branch
two. Branch one is not selected because no exercised local hard gate failed
and the contract retains a credible, approval-gated representative SSH/Linux
path. Branch two necessarily matches because local core semantics pass while
representative approved SSH/Linux and transport/reconnect evidence is absent.
Later branches are not evaluated as successful after the first match.

The E06-shaped optional session remains isolated from stateless in-process
execution, so the partial evidence does not currently force separate protocol
families. It also cannot justify the one-core success branch, because that
branch requires all three adapter shapes, including representative SSH/Linux.

## Consequences and unsupported cases

- Gate 1 may consider cache-before-reservation, immutable planned profile
  identity, exact attestation ordering, separated ownership identities,
  digest-before-use, idempotent operations, cursor-based replay, atomic
  publication, bounded detached cleanup, and exact orphan accounting as
  semantic inputs only.
- The SSH adapter and warm Linux admission threshold remain unimplemented and
  unmeasured. AC #1 and dependent all-three-adapter gates remain unpassed.
- SSH framing, reconnect-token encoding/authentication, gRPC, Connect, HTTP,
  credential mediation, and provider APIs remain unselected.
- The macOS stub proves only shape compatibility. It does not prove native
  build, simulator, VM, reset, performance, or host-lifecycle behavior.
- State-machine-analysis traces preserve coverage and reviewability but do not
  prove transport disconnection, worker loss, lease expiry, or remote resume.
- All code, schemas, trace formats, and adapters remain disposable experiment
  artifacts and must not be imported by production or prototype code.

## Trigger for revisiting this decision

- An explicit SSH availability manifest and approval permit representative
  Linux execution under the frozen host-key, credential, ownership, command,
  timeout, cleanup, and orphan-query boundaries.
- Representative transport faults reveal stale success, duplicate effects,
  cursor divergence, unsafe cleanup, or ownership ambiguity.
- The real macOS lifecycle requires session behavior that leaks into or
  distorts stateless execution.
- Gate 1 changes the semantic identity, CAS, ownership, publication, cleanup,
  or durability requirements bound by this experiment.

## Contracts now allowed to stabilize

No production contract, transport, wire envelope, public Go API, provider
adapter, reconnect token, or compatibility policy is allowed to stabilize.
The proven semantic invariants are Gate 1 inputs only.
