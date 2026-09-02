# Golden scenario: provider outage

Fixture: `w2-cross-target-artifact-pipeline` (`../graph.json`). Schema version: `t1-w2-experimental-v1`.

## Setup

Before `build` can even be placed (no worker acquired yet), the provider that
would supply `linux-build` capacity is entirely unavailable (API/connection
failure, authentication failure, or a declared zero-capacity state).

## Injected fault

Every placement attempt against the provider backing `linux-build` fails at
the acquisition step, not during execution - this is distinct from
`worker-loss.md` (a worker that was acquired and then lost).

## Expected outcome

- The run does not silently stay `pending` forever or crash the whole
  process; it durably records an explainable "provider unavailable" state for
  the blocked node.
- No partial/fabricated artifact or manifest is produced for `build` - a
  node that could not even acquire a worker has nothing to report except the
  outage itself.
- The outage state is distinguishable from every other failure mode in this
  fixture's golden set (`corrupt-artifact`, `downstream-failure-resume`,
  `worker-loss`, `cancellation`) - a human or agent reading the run's
  explanation must be able to tell these apart without reading source code.
- If the provider recovers before any cancellation/timeout policy ends the
  run, `build` is retried and the run can still complete normally end to end.

## Assertions a harness must implement

1. A durable "provider unavailable" event exists, attributed to the
   `linux-build` target role (not to a specific worker instance, since none
   was ever acquired).
2. No artifact-produced event exists for `build` while in this state.
3. If the harness simulates provider recovery, exactly one subsequent
   successful `build` completion event exists, and downstream nodes proceed
   normally from it.
4. The outage event and any later recovery/retry event are both present in
   the durable event log, in that order - state is explainable after the
   fact, not only observable while it is happening.
