# ADR 0010: E06 macOS and simulator feasibility

Status: proposed; awaiting separately approved Phase-B execution

Question: which E06 branch should inform Gate 1: warm VM with cloned
workspaces, VM per namespace, trusted native host, coarse external runner,
serialized macOS capacity, or stopping/narrowing the native-mobile goal?

Decision date: pending evidence

Task: TF-003.14. Roadmap references:
[E06 macOS feasibility](../roadmap.md#e06-macos-vm-xcode-and-simulator-feasibility),
[Gate 1](../roadmap.md#10-gate-1-product-and-architecture-convergence), and
[decision-record fields](../roadmap.md#21-decision-records).

## Context

TF-003.13 accepted the read-only host inventory, candidate procedures,
profile/lifecycle shape, measurement protocol, hard gates, and execution
manifest schema at commit `098035b`. It selected no candidate and explicitly
reserved all lifecycle mutation, measurement, and branch selection for this
ticket.

This proposed record is part of the result-free repository preparation. Four
worker candidates are rejected before execution from accepted inventory. The
trusted native host remains blocked pending an exclusive window, a complete
schema-valid manifest, current attestation, and fresh explicit approval of its
exact commands and cleanup targets. No candidate has been executed.

## Options considered

1. Warm VM with cloned disposable workspaces.
2. VM per namespace or run.
3. Trusted native host with strict experiment-owned workspace and simulator
   reset.
4. Coarse external macOS runner.
5. Serialized macOS capacity when only concurrency one is credible.
6. Stop or narrow the native-mobile product goal.

## Predeclared thresholds

- Warm workspace-ready p95 must be strictly below 3 seconds over 30 samples.
- Simulator ready-to-install p95 must be strictly below 15 seconds over 30
  samples for each admitted simulator mechanism.
- Build, install, test, reset, and cleanup use 15 samples each where applicable.
- Alternating namespace contamination uses 20 handoffs with zero residue.
- Two-namespace isolation uses 10 repetitions with zero identity, writable
  path, simulator, reservation, namespace, or lease collision.
- Concurrency levels 1, 2, 3, and 4 use five repetitions per level and stop on
  the frozen safety conditions.
- Simulator loss, cancellation, and caller loss use five repetitions each.
- Unauthorized cleanup, immutable-input mutation, unrecorded orphans,
  cross-namespace contamination, and identity/lease collisions have tolerance
  zero.
- Thresholds and branch rules cannot be relaxed after results are observed.

## Evidence and raw-result locations

The accepted Phase-A contract is under
`experiments/e06-macos-feasibility/`. Repository-only Phase-B preparation is
under `experiments/e06-macos-feasibility/phase-b/`. A future approved manifest
would place sanitized evidence under
`experiments/e06-macos-feasibility/evidence/taskflow-e06-native-a/`.

There is currently no Phase-B raw evidence, benchmark record, scorecard, or
selected branch.

## Decision

Pending separately approved execution. Repository preparation, plan approval,
and any later implementation commit do not authorize external or destructive
commands.

## Consequences and deliberately unsupported cases

Pending evidence. E06 will not claim Linux-to-macOS endpoint routing, runtime
authorization, a production provider, hermetic native execution, image-update
performance for a native-only run, or a universal capacity limit from one
host.

## Trigger for revisiting this decision

Pending evidence. Any host/profile, command-ledger, cleanup-target, toolchain,
runtime, or approved-window change requires a new manifest and approval before
execution.

## Contracts now allowed to stabilize

None before Gate 1.
