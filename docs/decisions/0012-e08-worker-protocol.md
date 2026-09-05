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

The initial Phase B checkpoint had no approved SSH endpoint. A subsequent
approved extension created an isolated ARM64 Linux/OpenSSH container inside a
ticket-owned local Colima VM. Its manifest pins the loopback endpoint, Ed25519
host key, experiment-only client identity, complete Linux profile and runner
digests, command and fault scope, owned paths/processes, and cleanup policy.
The adapter invokes `/usr/bin/ssh` with ambient configuration, agents,
interactive authentication, forwarding, and unknown host keys disabled.

This is genuine SSH/Linux execution rather than a mocked command or macOS
advertised as Linux. It exercises transport framing, strict host identity,
digest-verified transfer, Linux process/filesystem ownership, persistent
operation replay, and cleanup. Because controller and worker still share one
physical Mac, it is not external-host, WAN, provider, or physical-host-loss
evidence.

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
- `raw/` retains ten rows per fault case for the original two adapter shapes,
  while `ssh-linux/raw/` adds five rows per case for the Linux shape; evidence
  strength remains explicit;
- `benchmarks/` retains T1 benchmark-v2 records and raw samples;
- `implementation-manifest.json` and `manifest.json` bind implementation and
  evidence bytes; and
- `limitations.md` states the untested boundaries.

All 13 measurements and all 390 retained rows pass. The SSH/Linux measurements
are: ready-hit p95 12.066 ms, warm admission p95 51.178 ms, `TryReserve`
maximum 8.129 ms, cancellation acknowledgement maximum 7.563 ms, and bounded
cleanup maximum 55.801 ms. The frozen limits are unchanged.

The applicable executable/typed-core assertions pass.
Ready hits perform zero reservation or other resource work; attestation
precedes sandbox/session creation; immutable bytes are digest-checked before
use; publication uses compare-and-swap; operation replay is idempotent;
log replay verifies cursor order and byte digests; cancellation runs detached
bounded cleanup; and exact orphan query/reconciliation is exercised. Analysis-
only rows are not treated as implemented transport fault evidence. The Linux
records include 125 manifest-bound SSH connections across the accepted fault
and benchmark sets, plus exact strict-host/profile/container provenance.

## Decision

**Retain state-machine-first transport deferral.** This remains precedence
branch two. Branch one is not selected because no exercised correctness,
integrity, ownership, publication, cleanup, or orphan-accounting gate failed.
The SSH/Linux extension strengthens the result substantially: one typed core
drives all three shapes and the frozen timing gates pass. Branch two still
matches because thirty Linux rows remain explicitly analysis-only and the
disconnect rows prove durable replay across fresh connections at acknowledged
boundaries rather than a precisely timed mid-flight socket cut. Local hosting
also cannot close WAN, external-provider, credential-broker, physical-host-loss,
or cross-host recovery questions. Later branches are not selected after the
first matching precedence branch.

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
- The experimental SSH adapter and warm Linux admission threshold are now
  implemented and measured on a local Linux VM. This proves the minimum typed
  core can drive all three required shapes, but not that its transport should
  stabilize.
- SSH framing, reconnect-token encoding/authentication, gRPC, Connect, HTTP,
  external credential mediation, and provider APIs remain unselected.
- The macOS stub proves only shape compatibility. It does not prove native
  build, simulator, VM, reset, performance, or host-lifecycle behavior.
- The two Linux worker identities share one container and physical host.
  Resume proves compatible identity separation, not cross-host recovery.
- State-machine-analysis traces preserve coverage and reviewability but do not
  prove precise mid-flight cancellation, permanent physical worker loss,
  cleanup timeout, lease expiry, or output failure over a WAN transport.
- All code, schemas, trace formats, and adapters remain disposable experiment
  artifacts and must not be imported by production or prototype code.

## Trigger for revisiting this decision

- A representative external Linux host becomes available under an equally
  strict host-key, credential, ownership, command, timeout, cleanup, and
  orphan-query manifest.
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
