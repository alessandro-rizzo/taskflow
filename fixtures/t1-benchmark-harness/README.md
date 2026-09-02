# T1 benchmark evidence format and runner

Roadmap tranche: T1. Task: TF-002.04.

Status: pre-Gate-1 experimental fixture/harness. This is not a production
package, carries no compatibility promise, and must not be imported by any
production code (`docs/roadmap.md` section 3, rule 3a).

## Question

Roadmap section 8 requires "a benchmark runner recording hardware, OS build,
toolchain, cold/warm state, sample count, median, p95, and raw result
location," reusable across every Risk Lab experiment (E01-E08) and both
remaining T1 fixture tickets (TF-002.01/.02/.03). Left to each experiment
individually, this drifts — T0's own evidence tickets (TF-001.01/.03/.04)
each invented a slightly different ad hoc markdown+raw-file layout because
this harness did not yet exist. The question this fixture answers: what
result format and runner make Risk Lab measurements structurally comparable
and impossible to record with missing or self-contradictory data?

## Fixture / workload

This is infrastructure, not a single fixture: a Go library (`benchmark`
package, `record.go` + `validate.go`) defining the result schema and its
validator, plus a CLI (`cmd/t1bench`) that times N repetitions of an
arbitrary shell command and emits a validated record. Every future T1/Risk
Lab benchmark is expected to either call `t1bench` directly or produce a
`benchmark.Record` and pass it through `benchmark.Validate` before treating a
measurement as evidence.

## Measurement method and raw results

`t1bench` times each sample with Go's own monotonic clock
(`time.Since(time.Now())`) around one `sh -c <command>` invocation — the same
wall-clock approach TF-001.03 used with bash's `time` builtin, just measured
in-process instead of shelled out. Median and p95 use the method
`docs/evidence/t0/w1-startup.md` already documented and this package's tests
verify against that same recorded result (sorted ascending; median is the
middle value, or the average of the two middle values for even N; p95 is the
nearest-rank value at index `round(0.95*(N-1))`).

`t1bench` does not decide what "cold" or "warm" means for an arbitrary
command — that is prepared by the caller before invoking it. What the schema
guarantees is that the resulting record states precisely what was declared:
a required `state` (cold/warm/cache-hit) for the primary cache dimension
under test, plus an optional `cache_dimensions` map for any secondary caches
the caller pinned down (for example `gocache=warm`). This directly answers
the ambiguity TF-001.03 hit in practice — that Go's own build cache
(`GOCACHE`) and the driver's own binary cache (`TASKFLOW_DRIVER_CACHE`) are
two independent dimensions that both affected its timings — by making both
representable instead of collapsed into one bit.

Raw sample data always accompanies a record: `t1bench` writes `samples.txt`
(one wall-clock sample per line) alongside `record.json` in its `--out`
directory, and `record.json`'s own `raw_result_location` field points back to
it.

## Pass, pivot, and stop thresholds

This ticket is infrastructure, not a hypothesis experiment, so there is no
continue/pivot/stop branch of its own. Its own bar (from the ticket's
acceptance criteria) is binary and mechanical, checked by
`validate_test.go`:

- a record missing any required metadata field is rejected, naming the field;
- a record with empty, non-finite, or negative samples is rejected;
- a record whose `sample_count` does not match `len(samples)` is rejected;
- a record whose `median`/`p95` does not match a fresh recomputation from its
  own `samples` is rejected (guards against hand-edited or mislabeled
  results, not just missing ones);
- a `state: cache-hit` record without `reservation_count` is rejected (this
  is what lets a later result be checked against the roadmap's "W1 cache hit
  after planning: p95 below 300 ms and zero worker reservations" budget).

## Limitations and threats to validity

- This ticket does not evaluate any result against the roadmap section 8
  budgets. No daemon, remote provider, or production cache/plan pipeline
  exists yet to produce most of the measurements those budgets describe;
  this fixture only makes results comparable and internally valid, it does
  not gate anything against a threshold itself.
- `t1bench`'s cold/warm/cache-hit "unambiguity" is enforced by requiring the
  caller to *declare* the state and any secondary cache dimensions — it
  cannot detect on its own whether a caller mislabeled what they actually
  cleared or warmed before invoking it. The schema makes preparation
  auditable, not automatically correct.
- Hardware/OS/toolchain auto-detection in `t1bench` covers macOS and Linux
  only (the platforms named across roadmap sections 4 and 9); on any other
  platform the caller must supply `--cpu`/`--ram-gib`/etc. explicitly or
  `t1bench` will fail validation rather than write an incomplete record.
- T0's existing evidence (`docs/evidence/t0/`, TF-001.01/.02/.03/.04) is
  explicitly **not** retroactively migrated to this format by this ticket. It
  remains as originally recorded; only TF-002.01/.02/.03 and later Risk Lab
  experiments are expected to adopt `benchmark.Record` going forward.

## Recommendation

Adopt `benchmark.Record` / `benchmark.Validate` / `cmd/t1bench` as the
required result format for every T1 fixture (TF-002.01/.02/.03) and Risk Lab
experiment (E01-E08) benchmark going forward, per the G0 decision
(`docs/decisions/0003-g0-t0-exit.md`) that named this ticket the sole owner
of a standardized benchmark format. This decision is recorded operationally
here (the schema and its tests), not as a separate ADR, since roadmap section
8 already mandates the deliverable and no competing design was evaluated.

## Verification command

```sh
cd fixtures/t1-benchmark-harness
mise trust
mise install
mise exec -- task check
```
