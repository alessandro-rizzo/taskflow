# Golden scenario: downstream failure resumes on a compatible worker

Fixture: `w2-cross-target-artifact-pipeline` (`../graph.json`). Schema version: `t1-w2-experimental-v1`.

## Setup

`build` completes successfully and publishes `backend-binary`. `test` is
placed on a `linux-test` worker instance and fails for a reason unrelated to
the artifact itself (e.g. the worker becomes unreachable mid-execution, or
the test process crashes for an environment reason such as an OOM kill - not
a genuine test-assertion failure).

## Injected fault

The specific `linux-test` worker instance handling `test` becomes permanently
unavailable (simulated crash/loss) after accepting the artifact but before
completing.

## Expected outcome

- `test` resumes on a **different** worker instance that also satisfies the
  `linux-test` role's required capabilities (`os: linux`, `toolchain: go`) -
  the fixture does not require worker identity to be preserved, only
  capability compatibility (roadmap: "a failed downstream node resumes on
  another compatible worker").
- `build` is **not** re-run. `backend-binary` is reused from its original
  manifest-verified location; this is the "successful work is not repeated"
  property applied to the upstream node.
- The resumed `test` run either re-transfers the already-verified artifact or
  reuses a still-valid transferred copy - either way, the artifact's digest
  is re-verified against the original manifest before use on the new worker
  (do not assume a fresh worker already trusts a manifest it never saw).
- The final `go-tests-report` reflects one logical `test` execution's true
  result, not the crashed attempt's partial/missing output.

## Assertions a harness must implement

1. Exactly one `build` completion event exists in the durable event log for
   the whole run, regardless of how many `test` attempts occurred.
2. At least two `test` placement/attempt events exist (the crashed one and
   the resumed one), on two distinct worker identities.
3. The resumed attempt's artifact-integrity-check event is present (see
   `corrupt-artifact.md`'s assertion #1) - resume does not skip
   re-verification.
4. Final run state has no `unknown`/`pending` residue from the crashed
   attempt; it is cleanly superseded by the resumed attempt's outcome.
