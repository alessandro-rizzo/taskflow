# Golden scenario: worker loss during build

Fixture: `w2-cross-target-artifact-pipeline` (`../graph.json`). Schema version: `t1-w2-experimental-v1`.

## Setup

`build` is placed on a `linux-build` worker and is mid-execution (source
transferred, compilation in progress) when the worker is lost entirely
(process killed, host unreachable, provider deallocates it without warning).

## Injected fault

The `linux-build` worker instance disappears with no clean shutdown signal -
distinct from `downstream-failure-resume.md`'s scenario (which loses a
*downstream* worker after the upstream artifact already exists); here nothing
has been produced yet.

## Expected outcome

- The run does not hang waiting for a worker that will never respond; loss is
  detected within a bounded period and the node's state durably transitions
  to a distinct, explainable "worker lost" outcome, not left `running`
  forever.
- `build` is retried on a new compatible `linux-build` worker instance from
  scratch (there is no partial artifact to resume from - a build that never
  finished has nothing to reuse).
- `test` and `inspect` remain unplaced/blocked until the retried `build`
  actually succeeds - neither speculatively starts against a `build` that
  hasn't produced a verified artifact.
- No stale reservation on the lost worker survives the run indefinitely (this
  connects to TF-001.04's finding that admission/reservation state was not
  observed to be scoped correctly across instances - this fixture requires
  that a lost worker's reservation is eventually and durably released, which
  today's prototype does not demonstrate and is left to E04/E05).

## Assertions a harness must implement

1. A durable "worker lost" event is recorded with a bounded detection
   latency (the fixture does not fix a number here; a harness/experiment
   declares its own threshold and records it as measured evidence, per T1's
   benchmark contract in TF-002.04).
2. Exactly one successful `build` completion event exists once the run
   finishes, from the retry, not the lost attempt.
3. No `test` or `inspect` placement event is recorded before the retried
   `build`'s completion event.
4. The lost worker's reservation/lease is not observably held after the
   detection event (this assertion may be marked "not yet satisfiable" by a
   harness run against the current prototype, per TF-001.04's open questions
   to E04 - record it as an explicit gap rather than omitting the check).
