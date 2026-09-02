# Golden scenario: corrupt artifact

Fixture: `w2-cross-target-artifact-pipeline` (`../graph.json`). Schema version: `t1-w2-experimental-v1`.

## Setup

The `build` node completes normally and publishes `backend-binary` with a
manifest (digest, size, produced-by). Before `test` or `inspect` consume it,
the transferred bytes are corrupted (bit flip, truncation, or a
digest/manifest mismatch introduced in transit or at rest) without changing
the recorded manifest digest.

## Injected fault

One of, exercised as separate sub-cases:

- **transit corruption**: bytes received by `linux-test` or `local-inspect`
  do not hash to the manifest's recorded digest.
- **manifest tamper**: the manifest itself is altered after `build` recorded
  it (recorded digest no longer matches what `build` actually produced).

## Expected outcome

- The consuming node (`test` or `inspect`) MUST detect the digest mismatch
  before using the artifact for anything (running tests against it,
  inspecting it) - not after.
- The node's outcome is a distinct, explainable failure state (e.g.
  `artifact-integrity-failed`), not a generic execution failure and not a
  silent pass.
- `build`'s own recorded state is unaffected - `build` already completed
  successfully and produced a correctly-digested artifact; corruption
  happened downstream of it, so `build` must not be re-run or marked failed
  as a side effect.
- The failure is durable: re-querying run status after the failure (without
  re-running anything) reports the same `artifact-integrity-failed` outcome,
  not an unknown or transient state.

## Assertions a harness must implement

1. Lifecycle event order includes an explicit integrity-check event between
   "artifact received" and "artifact used", and that check's failure event
   carries the expected vs. actual digest.
2. `build`'s recorded outcome remains `succeeded` after the downstream
   integrity failure.
3. No retry of `test`/`inspect` is attempted automatically against the same
   corrupt bytes without an explicit re-fetch/re-verify step (retrying
   against unchanged corrupt data cannot succeed and must not silently loop).
