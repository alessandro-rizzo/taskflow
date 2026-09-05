# ADR 0010: E06 macOS and simulator feasibility

Status: accepted; stop-or-narrow

Question: which E06 branch should inform Gate 1: warm VM with cloned
workspaces, VM per namespace, trusted native host, coarse external runner,
serialized macOS capacity, or stopping/narrowing the native-mobile goal?

Decision date: 2026-09-05

Task: TF-003.14. Roadmap references:
[E06 macOS feasibility](../roadmap.md#e06-macos-vm-xcode-and-simulator-feasibility),
[Gate 1](../roadmap.md#10-gate-1-product-and-architecture-convergence), and
[decision-record fields](../roadmap.md#21-decision-records).

## Context

TF-003.13 accepted the read-only host inventory, candidate procedures,
profile/lifecycle shape, measurement protocol, hard gates, and execution
manifest schema at commit `098035b`. It selected no candidate and reserved all
lifecycle mutation, measurement, and branch selection for this ticket.

TF-003.14 then implemented an approval-bound native ledger and a separate
single-cycle VM smoke adapter. The native path remained unavailable: the host
was shared and unreserved, the managed session could not access CoreSimulator,
and using shared/default simulator state was forbidden. A pinned Tart 2.36.0
controller and Cirrus Labs macOS Tahoe/Xcode 26.5 image were therefore acquired
under a separate explicit scope. The guest was attested as macOS 26.4 build
25E246, Xcode 26.5 build 17F42, iOS Simulator runtime 26.5 build 23F77, arm64,
with SIP disabled and approximately 49.4 GiB free disk.

Three separately approved, immutable-input VM smoke attempts were executed.
Each used one disposable clone, an isolated device set, a bounded command
ledger, and post-failure base-integrity and clone-cleanup gates:

1. The first app launch exited successfully but `simctl --console` did not
   transport the application report. The runner rejected the missing result.
2. The second attempt switched to PTY transport. UserDefaults and the document
   canary persisted, but the Keychain value did not. The unsigned fixture did
   not report Security framework status codes, so this was retained as negative
   evidence rather than assigned a definitive cause.
3. The third fixture recorded Security status codes and requested
   credential-free ad-hoc signing. Xcode generated an intermediate
   `application-identifier`, but its logged `codesign` command did not attach
   the entitlement file. Signature verification succeeded while effective
   entitlement inspection returned no plist. The runner stopped before
   simulator creation, install, or launch.

Attempt three was the predeclared terminal retry. No Apple account, development
team, certificate, provisioning update, personal credential, or fourth attempt
was used. Weakening the Keychain canary would have changed the contamination
criterion after seeing results.

## Options considered

1. Warm VM with cloned disposable workspaces.
2. Warm immutable VM restore.
3. VM per namespace or run.
4. Trusted native host with strict experiment-owned workspace and simulator
   reset.
5. Coarse external macOS runner.
6. Serialized macOS capacity when only concurrency one is credible.
7. Stop or narrow the native-mobile product goal.

The VM families share the failed credential-free smoke prerequisite and were
rejected before timing. No suspended-memory restore mechanism was admitted for
the warm-restore option. The native host shares the same credential boundary
and remained operationally unavailable. The external-runner option had no
endpoint, credential mediator, profile, quota, reset/orphan API, or reservation
to exercise. Serialization cannot repair the signing/Keychain correctness
failure.

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
- Simulator loss, cancellation, caller loss, and VM loss use five repetitions
  each.
- Unauthorized cleanup, immutable-input mutation, unrecorded orphans,
  cross-namespace contamination, and identity/lease collisions have tolerance
  zero.

The mandatory smoke failed before the measurement matrix. Both latency
thresholds therefore remain not reached, not failed or passed. No p95,
contamination, capacity, reset, cancellation, caller-loss, simulator-loss,
VM-loss, or image-update result exists, and no threshold was relaxed.

## Evidence and raw-result locations

The accepted Phase-A contract is under
`experiments/e06-macos-feasibility/`; immutable Phase-B execution contracts are
under `experiments/e06-macos-feasibility/phase-b/`. The sanitized terminal
evidence, source-directory digests, approval/failure/cleanup/base records,
decisive launch/signing records, result, checksums, and verifier are under
`experiments/e06-macos-feasibility/evidence/taskflow-e06-vm-a/`.

The three complete live evidence roots contained 146, 153, and 118 files and
had deterministic aggregate digests
`c7e89d3417f2cd1be24d72909928a3894244a2282f61d8c00585d74a5f28aa03`,
`7911622d78c44e4755597a4009039f42795733ba01b2e78bf09b766b02822f38`,
and `882df5a27fa2d6bdfff04c9c2dbad115a900c7741776801b0ea0bd60512f0473`.
Every attempt retained zero benchmark samples, removed its exact disposable
clone within the 30-second grace, and preserved the pinned manifest, config,
NVRAM, and disk hashes.

Verification command:

```sh
mise exec -- task --dir experiments/e06-macos-feasibility/evidence/taskflow-e06-vm-a check
```

## Decision

Select **stop-or-narrow**. Gate 1 must not authorize a first-class Taskflow
macOS provider, a warm-VM performance claim, or a credible W3 native-mobile
path from this evidence.

Narrow the native-mobile scope until signing and credential mediation are an
explicitly designed trust boundary and a properly entitled application can be
tested on representative, reserved infrastructure. A coarse external macOS
runner is the bounded fallback to evaluate because it can own signing identity,
Keychain access, reset, and credential mediation without transferring personal
credentials into Taskflow's worker experiment. That fallback is a future
experiment, not an accepted provider or current feasibility claim.

## Consequences and deliberately unsupported cases

- Gate 1 may proceed only with the native-mobile product thesis marked narrowed
  or paused; it cannot infer warm macOS feasibility from repository contracts,
  VM acquisition, guest attestation, or a partial smoke.
- E06 does not establish the 3-second workspace or 15-second simulator budgets,
  safe concurrency, namespace isolation, reset reliability, failure recovery,
  or image update cost.
- The evidence does not show that a properly entitled, development-signed app
  cannot persist simulator Keychain state. It shows that this credential-free
  ad-hoc path did not embed the required entitlement.
- The SIP-disabled third-party guest is not a production security profile.
- No production provider, protocol, public package, signing abstraction, or
  credential contract is allowed to stabilize from this result.
- The retained Tart image/controller, host helper, and raw working evidence
  were removed after evidence preservation using the guarded cleanup procedure.
  The cleanup reclaimed 81.9 GiB at the filesystem level; no DHCP preference
  mutation was needed because the experiment key was already absent.

## Trigger for revisiting this decision

Revisit E06 only when an approved follow-up supplies all of: a credential and
signing mediation design that does not expose personal material to workloads; a
reserved representative macOS target or external runner; an entitled smoke app
that passes Keychain write, immediate read, relaunch persistence, erase/reset,
and cross-namespace absence; exact cleanup/orphan authority; and the original
frozen timing, contamination, concurrency, recovery, and update-cost matrix.

New evidence must cite this decision and retain the failed attempts. It must not
reinterpret an unmeasured threshold as passed or silently broaden the previous
approval.

## Contracts now allowed to stabilize

None for native macOS execution, signing, simulator lifecycle, or provider
placement. The evidence supports only the existing fail-closed approval,
identity, bounded-cleanup, and immutable-input principles; their experiment
formats remain non-production and versioned as experimental.
