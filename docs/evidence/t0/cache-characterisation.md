# T0 evidence: cache ordering and local interference characterisation

Roadmap tranche: T0. Gate: G0. Workflows W1, W2. Risks R4, R5, R9. Task: TF-001.04.

Status: measured evidence, not a product claim. This characterises the
isolated prototype's *current* cache-hit/cache-miss ordering and local
concurrency behaviour. It is not a statement about what the future clean
implementation must do — it exists so E04 (`docs/roadmap.md#e04-immutable-source-lightweight-sandbox-and-cache-identity`)
starts from measured facts instead of the baseline doc's prose summary alone.

## Environment

- Source revision: `9ddea886c7b4e368b5bcd8e48c36a9e2e916cb18`
- Timestamp: 2026-09-02T19:10:20Z
- OS: Darwin (macOS 26.5.2), arm64
- Go: go1.25.12 darwin/arm64

Raw capture: [`raw-cache/environment.txt`](raw-cache/environment.txt)

## What was added

One new, clearly-labelled, removable test file:
`prototype/bootstrap/engine/t0_characterization_test.go`. It adds no new
production behaviour. Both tests exercise the real `engine.Scheduler` /
`engine.RuntimeExecutor` / `target/local.Provider` / `cache/file.Store` stack;
the only new code is thin delegating wrappers used purely to observe call
ordering (`loggingProvider`, `loggingReservation`, `loggingEnvironment`,
`loggingStore`), plus the two test functions themselves. No prototype
production file was modified.

## Measured facts

### 1. Cache-hit / cache-miss ordering, and acquisition-before-cache-resolution (AC #1, #2)

`prototype/bootstrap/engine/runtime.go`'s `runtimeExecution.Run` has a fixed,
linear structure:

| Step | Code | What happens |
| --- | --- | --- |
| 1 | `runtime.go:118` | `reservation.Acquire(ctx)` — provider/environment acquisition, explicitly documented as possibly slow network work |
| 2 | `runtime.go:142` | `Materializer.Materialize` (source upload), if a `Materializer` is configured |
| 3 | `runtime.go:158` | `environment.Identity(...)` — toolchain probing inside the acquired environment |
| 4 | `runtime.go:185` | `cache.Coordinator.ComputeIdentity(...)` — cache key computed from, among other things, the environment identity obtained in step 3 |
| 5 | `runtime.go:198` | `cache.Coordinator.Restore(...)` → `Store.Open(...)` — the actual cache lookup |

Steps 1–3 are unconditional; step 4/5 (cache resolution) cannot even begin
before step 3 completes, because the cache key includes the probed
`target.Identity`. This is a structural fact, not a race: on cache hit, `Run`
still executes steps 1–3 before it learns the step could have been skipped.

`TestT0CacheOrderingAcrossMissThenHit` confirms this dynamically. It runs one
cacheable step twice against `target/local.Provider` (no `Materializer`
configured, matching the existing `engine` test suite's convention), first as
a cache miss then, after deleting the output, as a cache hit, recording an
ordered, timestamped event log through instrumented wrappers around the real
`Provider`/`Reservation`/`Environment`/`Store`.

Observed event order — miss run:

```
reserve, acquire-start, acquire-done, identity-probe-start, identity-probe-done,
cache-open-start, cache-open-miss
```

Observed event order — hit run:

```
reserve, acquire-start, acquire-done, identity-probe-start, identity-probe-done,
cache-open-start, cache-open-hit, environment-upload-start, environment-upload-done
```

The trailing `environment-upload-*` pair on the hit run is
`cache.Coordinator.Restore`'s own call to `environment.Upload` to place the
cached artifact into the workspace (`cache.go:140`) — it is not source
materialization (no `Materializer` was configured in this test, so no
pre-execution upload occurs; when one is configured it runs at `runtime.go:142`,
which is still before the identity probe and cache resolution). In both runs,
`acquire-done` and `identity-probe-done` occur strictly before
`cache-open-{hit,miss}`; the test asserts this explicitly and fails otherwise.

Raw output: [`raw-cache/t0-ordering-and-interference.log`](raw-cache/t0-ordering-and-interference.log),
[`raw-cache/t0-ordering-and-interference-race.log`](raw-cache/t0-ordering-and-interference-race.log)
(same assertions under `go test -race`, exit 0).

This directly confirms the limitation already named in
`prototype/bootstrap/docs/baseline.md`: "The runtime acquires and probes an
environment before cache lookup can finish" — and sharpens it: cache identity
is *computed from* the acquired environment's probed identity, so cache
resolution is not merely ordered after acquisition, it is data-dependent on
it in the current design.

### 2. Concurrent local runs, shared checkout, filesystem interference (AC #3)

`target/local.Provider` (`local.go:24-32`) holds all admission state
(`running`, `exclusive`, `used`) as private, in-process fields guarded by a
`sync.Mutex`. Two `Provider` instances constructed over the *same* root
directory — which is exactly what happens when two independent Taskflow CLI
invocations run concurrently against one shared worktree, since each process
builds its own `target.Registry`/`Provider` — do not share this state.

`TestT0ConcurrentLocalProvidersDoNotCoordinateAcrossInstances` demonstrates
this: two independent `local.Provider` instances are created over one shared
temp root; both successfully `TryReserve` with `ExclusiveWorkspace: true` and
both are admitted simultaneously (the second admission is not supposed to
succeed while an exclusive execution is active — `TestProviderSerializesExclusiveWorkspaceExecutions`
in `target/local/local_test.go` proves that serialization *does* work within
a single `Provider` instance). Their environments then run 50 concurrent
`sh -c` append invocations each against one shared file with no coordination.

Observed result: 100/100 attempted appends landed (50 from each side), for
100 bytes total — no byte-level corruption, because POSIX `O_APPEND` writes of
this size are atomic on this filesystem. The interleaving order between the
two sides is not controlled or observable as safe by Taskflow: nothing in the
admission layer prevented the two "exclusive" executions from running at the
same time and against the same files.

Raw output: [`raw-cache/t0-ordering-and-interference.log`](raw-cache/t0-ordering-and-interference.log)
(same test also run under `-race`: [`raw-cache/t0-ordering-and-interference-race.log`](raw-cache/t0-ordering-and-interference-race.log),
exit 0, no data race reported).

## Limitations

- The concurrency test uses two `Provider` instances inside one Go test
  process, not two literal OS processes. This faithfully models the
  in-process admission-state scope (the actual bug: state is per-`Provider`
  object, not per-filesystem-root), but does not exercise OS-level process
  isolation, signal handling, or two real `taskflow` binaries racing.
- Go's `-race` detector instruments shared Go memory in one process. It
  cannot and does not detect filesystem-level races between the two
  independent `os/exec` child processes here — its "no race" result is
  expected and is not evidence that concurrent shared-checkout writes are
  safe.
- The interference scenario used small (`printf`) appends, which happen to be
  atomic at the OS level; it does not demonstrate corruption for larger or
  non-atomic writes (e.g. non-append writes, multi-step file replacement, or
  a reader observing a partially-written file). The absence of observed
  corruption in this run is not a safety guarantee.
- Only the `local` target was characterised. `target/ssh` and any future
  container/VM provider were out of scope for this ticket.
- This is a single-machine, single-OS (macOS/arm64) characterisation.

## Open questions handed to E04

1. **Cache identity is not resolvable independently of environment
   acquisition.** `ComputeIdentity` consumes `target.Identity`, which is only
   available after `Acquire` and a toolchain probe inside the acquired
   environment (`runtime.go:118-185`). E04's required demonstration #4
   ("Cache identity is computed from source, inputs, process, profile, policy,
   and dependency manifests before any worker reservation") is disproven by
   the current prototype design and needs a profile-identity model that does
   not require an acquired environment.
2. **"Non-blocking reservation" (`TryReserve`) is necessary but not
   sufficient — the actual `Reservation.Acquire` still runs before cache
   resolution.** E04's demonstration #5 ("A cache hit performs zero provider
   reservations/acquisitions") fails today: `Acquire` always runs, even on a
   guaranteed hit, because the hit cannot be known until after acquisition.
3. **Admission exclusivity is scoped to a single in-process `Provider`
   instance, not to the filesystem root it manages.** Two independent
   processes (or two `Provider` instances in one process) sharing a checkout
   have zero enforced mutual exclusion. E04's required demonstration #2
   ("Two concurrent W1 runs cannot observe each other's writable outputs")
   fails for the local target as currently implemented; a design that
   attaches admission/locking to the workspace root (or replaces the shared
   checkout with per-run copy-on-write/immutable snapshots, as E04 already
   proposes) needs to close this specifically.
4. **What corruption modes are possible for the local target with truly
   concurrent, non-atomic writes?** This ticket verified no corruption for
   atomic small appends; it did not probe larger or non-atomic writes. E04
   should decide whether to invest in reproducing worse interference (as
   further evidence) or treat "shared checkout with no isolation" as
   sufficiently disproven already and move directly to the immutable
   source/copy-on-write design it was already considering.

## Reproduction

From `prototype/bootstrap/` at revision `9ddea88` or later:

```sh
mise trust
mise install
go test -v -race -run TestT0 ./engine/...
```
