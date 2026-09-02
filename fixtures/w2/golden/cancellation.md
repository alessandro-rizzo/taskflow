# Golden scenario: cancellation

Fixture: `w2-cross-target-artifact-pipeline` (`../graph.json`). Schema version: `t1-w2-experimental-v1`.

## Setup

Two sub-cases, both starting from a run where `build` has completed and
`test`/`inspect` are in progress or about to be placed:

1. **cancel-while-running**: the run is cancelled while `test` is actively
   executing on its `linux-test` worker.
2. **cancel-before-placement**: the run is cancelled after `build` completes
   but before `test`/`inspect` are placed.

## Injected fault

An explicit cancellation request, not a crash or outage - the difference
matters: cancellation is caller-initiated and must be handled gracefully,
not treated as a fault to recover from.

## Expected outcome

- **cancel-while-running**: the active `test` execution is stopped (not left
  running unattended on the worker), and its worker/workspace is released
  within a bounded, declared window - not left as an orphaned reservation.
- **cancel-before-placement**: `test`/`inspect` are never placed at all; no
  worker is acquired for them.
- In both sub-cases, `build`'s already-completed, manifest-verified artifact
  is retained (or at least its manifest/state remains queryable) - a
  cancellation does not retroactively invalidate upstream work that already
  durably succeeded, so a future resume of the same run could reuse it
  without re-running `build` (connects to "successful work is not repeated").
- The run's final durable state is an explicit `cancelled` outcome, not
  `failed` and not silently absent from state.

## Assertions a harness must implement

1. A durable `cancelled` event exists for the run, distinguishable from
   `failed`/`worker-lost`/`provider-unavailable` outcomes in the other golden
   files.
2. In cancel-while-running: a worker-release/cleanup event for the
   in-flight `test` node is recorded within the declared bounded window (the
   window's actual value is measured evidence recorded by whichever
   harness/experiment executes this scenario, per TF-002.04's benchmark
   contract - this fixture does not fix the number).
3. In cancel-before-placement: no placement/acquisition event exists for
   `test` or `inspect`.
4. `build`'s completion event and manifest remain present and unaltered in
   the durable event/state log after cancellation in both sub-cases.
