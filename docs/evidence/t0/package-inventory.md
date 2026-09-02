# T0 package, interface, and review-finding inventory

Roadmap tranche: T0. Gate: G0. Task: TF-001.02.

Status: measured evidence, not a compatibility promise. This inventory
describes what `prototype/bootstrap` currently contains and what its own test
suite currently proves. None of the described interfaces are treated as
stable; `flow.Step`, `target.Environment`, and friends are explicitly
low-level per `prototype/bootstrap/docs/baseline.md` and may be replaced
entirely by the typed product SDK selected at Gate 1.

Source revision: `9ddea886c7b4e368b5bcd8e48c36a9e2e916cb18` (branch
`tf-001.02-package-inventory`, based on `main`).

## 1. Package inventory

20 packages, discovered with `go list ./...` from `prototype/bootstrap`
(raw: [`raw-inventory/file-listing.txt`](raw-inventory/file-listing.txt),
package list also embedded per-package below). Each package's full exported
surface is captured verbatim with `go doc -all <pkg>` under
[`raw-inventory/godoc/`](raw-inventory/godoc/).

| Package | Purpose (source doc comment) | Exported surface (highlights) | Test files | Verify |
| --- | --- | --- | --- | --- |
| `cache` | Content-addressed cache and coordinator (`cache/cache.go`) | `Coordinator`, `Store` interface, `Key`, `Entry` | `cache/coordinator_test.go` | `go test ./cache/... -run TestCoordinator -v` |
| `cache/file` | Atomic filesystem-backed cache store (`cache/file/file.go`) | `Store`, `New` | `cache/file/file_test.go` | `go test ./cache/file/... -v` |
| `cmd/taskflow` | CLI entrypoint (`cmd/taskflow/main.go`); wraps `internal/projectdriver` | `main` (unexported); package `main`, no exported API | none | n/a (exercised only via `internal/projectdriver` tests + manual `task example`) |
| `driver` | Project-side half of the versioned compiled-driver protocol (`driver/driver.go`) | `Main(Config) int`, `HandshakeCommand`, `ProtocolVersion` | `driver/driver_test.go` | `go test ./driver/... -run TestHandshakeListAndGraph -v` |
| `engine` | Schedules validated pipelines (`engine/runtime.go`, `engine/scheduler.go`) | `Scheduler`, `ArchiveMaterializer`, `Options`, `Result` | `engine/scheduler_test.go`, `engine/runtime_integration_test.go` | `go test ./engine/... -v` |
| `event` | Stable, line-oriented execution event stream (`event/event.go`) | `Dispatcher`, `NewDispatcher`, `Sink` | none (consumed by `engine`/`terminal` tests indirectly) | n/a directly; see `engine/scheduler_test.go` for dispatch ordering under load |
| `examples/basic` | Typed local pipeline example (`examples/basic/main.go`) | `main` (unexported); package `main`, no exported API | none | `go run ./examples/basic` (manual) |
| `flow` | Typed, code-first Taskflow DAG (`flow/flow.go`) | `Builder`, `Ref`, `CacheMode`, `MustDefine`, `Step` | `flow/flow_test.go` | `go test ./flow/... -v` |
| `internal/projectdriver` | Locates, fingerprints, builds, and invokes a project-local `.taskflow` package (`internal/projectdriver/projectdriver.go`) | `FindRoot`, `ExitError`, build/run entrypoints | `internal/projectdriver/projectdriver_test.go` | `go test ./internal/projectdriver/... -v` |
| `process` | Portable process request/result passed to execution targets (`process/process.go`) | `IO`, `Result`, `Spec` (types only) | none | n/a directly; exercised via `target/local`, `target/ssh` tests |
| `runner` | Adapters from named task-runner recipes to portable process specs (`runner/runner.go`) | `Adapter` interface, `Identity`, `Invocation`, `Resolved` | none | n/a directly; exercised via `runner/taskfile` test and `flow` tests |
| `runner/command` | Adapts direct executable invocations (`runner/command/command.go`) | `Adapter`, `New` | **none** | n/a — no package-local test |
| `runner/just` | Adapts Just recipes to invocations (`runner/just/just.go`) | `Adapter{Binary, Version}`, `New` | **none** | n/a — no package-local test |
| `runner/taskfile` | Adapts Go Task tasks to invocations (`runner/taskfile/taskfile.go`) | `Adapter{Binary, Version}`, `New` | `runner/taskfile/taskfile_test.go` (`TestResolve`, static binary/args/dir/env only — no version-probe assertion) | `go test ./runner/taskfile/... -v` |
| `state` | Revisioned transition journal for recovery (`state/state.go`) | `SchemaVersion`, `ErrNotFound`, `ErrLocked`, `ErrConflict`, `Apply` | `state/state_test.go` | `go test ./state/... -v` |
| `state/file` | One atomic file per state transition (`state/file/file.go`, plus `lock_unix.go`/`lock_other.go`) | `Store`, `New`, `Acquire` | `state/file/file_test.go` | `go test ./state/file/... -v` |
| `target` | Replaceable execution targets (`target/target.go`) | `AcquireRequest`, `Environment`, `Capabilities`, `Provider` (types/interfaces) | none | n/a directly; exercised via `target/local`, `target/ssh` |
| `target/local` | Executes steps as child processes on the controller (`target/local/local.go`) | `Provider`, `New` | `target/local/local_test.go` | `go test ./target/local/... -v` |
| `target/ssh` | Deliberately small remote provider falsifying target/transfer/cleanup/identity contracts (`target/ssh/ssh.go`) | `Config`, `Provider` | `target/ssh/ssh_test.go` | `go test ./target/ssh/... -v` |
| `terminal` | Renders events as readable, line-oriented output (`terminal/renderer.go`) | `Renderer`, `New`, `Verbosity` | **none** | n/a — no package-local test |
| `workspace` | Deterministic matching, hashing, tar transfer below a workspace root (`workspace/workspace.go`) | `Digest`, `Extract`, `Match`, `NormalizeArchive` | `workspace/workspace_test.go` | `go test ./workspace/... -v` |

**9 of 20 packages have no package-local `_test.go` file**: `cmd/taskflow`,
`event`, `examples/basic`, `process`, `runner`, `runner/command`,
`runner/just`, `target`, `terminal`. Several of these are thin type/interface
definitions exercised indirectly through consumers' tests (`process`,
`runner`, `target`), but `runner/command`, `runner/just`, and `terminal` have
no direct or clearly-attributable indirect test coverage found in this
inventory pass.

## 2. Fable 5 review findings vs. current tests

Source: [`prototype/bootstrap/docs/reviews/2026-07-27-fable-5.md`](../../../prototype/bootstrap/docs/reviews/2026-07-27-fable-5.md).
All findings below were marked "Fixed" (or "Fixed within the declared-output
model") by the review's disposition; this table records whether a current
test demonstrates the fix, independent of the review's own claim.

| Severity | # | Finding | Mapped test | Coverage |
| --- | --- | --- | --- | --- |
| Critical | 1 | Cross-target dependency outputs not transferred | `engine/runtime_integration_test.go:103` `TestRuntimeTransfersDependencyArtifactsAcrossTargets` | Covered |
| Critical | 2 | Early `io.Pipe` consumer failure could deadlock | `cache/coordinator_test.go:136` `TestPublishDoesNotDeadlockWhenStoreRejectsBeforeReading`; `engine/scheduler_test.go:410` `TestArchiveMaterializerDoesNotDeadlockWhenUploadReturnsEarly` | Covered |
| Critical | 3 | Archive symlink `..` escape | `workspace/workspace_test.go:16` `TestExtractRejectsSymlinkEscapeAndSymlinkParentTraversal`; `:65` `TestExtractAllowsSafeRelativeSymlinkAndIsIdempotent` | Covered |
| Critical | 4 | SSH path components accepted `.`/`..` | `target/ssh/ssh_test.go:99` `TestProviderContainsHostileComponentsBelowRoot`; `flow/flow_test.go:130` `TestDefineRejectsDotOnlyRemotePathComponents` | Covered |
| Critical | 5 | Resume invalidation not transitive | `engine/scheduler_test.go:73` `TestSchedulerResumeTransitivelyInvalidatesDependents` | Covered |
| High | 1 | Corrupt/torn cache entries failed instead of missing | `cache/file/file_test.go:57` `TestStoreRejectsCorruptBlob`; `:79` `TestStoreTreatsCorruptMetadataAsMiss` | Covered |
| High | 2 | Driver fingerprints ignored imported packages/embedded files | `internal/projectdriver/projectdriver_test.go` (`TestBuildCachesAndRunsCompiledDriver`, asserts at line 108: "imported main-module source edit did not change cache digest" fails without the fix) | Covered |
| High | 3 | Cleanup failure converted completed work into failed work | `engine/scheduler_test.go:374` `TestRuntimeCleanupFailureDoesNotFailCompletedWork` | Covered |
| High | 4 | Concurrent local steps shared mutable workspace | `target/local/local_test.go:105` `TestProviderSerializesExclusiveWorkspaceExecutions` | Covered |
| Medium | 1 | Retries could wait behind unrelated work | `engine/scheduler_test.go:241` `TestSchedulerWakesRetryWhileUnrelatedStepRuns` | Covered |
| Medium | 2 | Resume retained spent retry attempts / stale output identity | `engine/scheduler_test.go:206` `TestSchedulerPersistsEveryRetryAttempt` covers attempt persistence during a run, not attempt/identity reset specifically on resume; `TestSchedulerResumeTransitivelyInvalidatesDependents` (line 73) covers transitive resume invalidation generally | **Explicit gap**: no test asserts retry-attempt counters or stale output identity are actually reset by a resume, specifically |
| Medium | 3 | `state.Apply` mutated caller's map before durable append | `state/state_test.go:10` `TestApplyDoesNotMutateUncommittedSnapshot` | Covered |
| Medium | 4 | SSH and local archive pattern/determinism semantics differed | `target/ssh/ssh_test.go:17-89` `TestProviderTransfersExecutesAndCleansRemoteWorkspace` (asserts remote output archive determinism); `workspace/workspace_test.go:125` `TestPackIsDeterministicAcrossModificationTimes` (local determinism) | Covered (two separate tests, one per side; no single test directly diffs SSH vs. local semantics) |
| Medium | 5 | Remote tar extraction bypassed Taskflow validation | `target/ssh/ssh_test.go:142` `TestUploadRejectsHostileArchiveBeforeRemoteExtraction` | Covered |
| Medium | 6 | Symlink restoration not idempotent | `workspace/workspace_test.go:65` `TestExtractAllowsSafeRelativeSymlinkAndIsIdempotent` | Covered |
| Medium | 7 | Admission errors returned before journaling final state | `engine/scheduler_test.go:267` `TestSchedulerPersistsAdmissionFailureAndFinalRunStatus` | Covered |
| Medium | 8 | Task/Just cache identity did not observe installed runner version | `runner/taskfile/taskfile_test.go:11` `TestResolve` asserts only a static `binary` identity field (no `--version` probe assertion); `runner/just` has **no test file at all** | **Explicit gap**: neither adapter's version-probe contribution to cache identity is tested |
| Medium | 9 | CLI cancellation bypassed graceful journal/cleanup | `internal/projectdriver/projectdriver_test.go:130` `TestRunForwardsCancellationToDriverForGracefulShutdown` | Covered |

Lower-severity observations (provider non-blocking contract, digest schema
version, driver mismatch guidance text, `.lock`-suffixed run IDs, race
detector in the guarded check) are documentation/contract notes rather than
independently testable code-behavior findings and are not mapped to
individual tests here.

Raw test-function listing used to build this table:
[`raw-inventory/test-functions.txt`](raw-inventory/test-functions.txt).

## 3. Concept classification: proven, unproven, disproven

Cross-referenced against `prototype/bootstrap/docs/baseline.md`'s
"Demonstrated concepts" and "Important limitations," each independently
re-checked against source and tests in this pass rather than restated.

### Proven (source-and-test-backed in this prototype)

- Compiled Go pipeline definitions with structural/definition digests that
  change on meaningful edits and ignore cosmetic ones —
  `flow/flow_test.go:159,194` (`TestStructuralDigestIgnoresCosmeticsTuningAndOrder`,
  `TestStructuralDigestGolden`).
- Parallel DAG scheduling with fail-fast, retry, and resource admission —
  `engine/scheduler_test.go` (`TestSchedulerParallelisesReadySteps`,
  `TestSchedulerFailFastCancelsRunningAndBlocksPending`,
  `TestSchedulerPersistsEveryRetryAttempt`,
  `TestSchedulerSkipsSaturatedTargetWithoutConsumingGlobalSlot`).
- Non-blocking provider reservation before acquisition —
  `target/local/local_test.go:72` `TestProviderReservesFiniteResources`.
- Content-addressed result cache with hit/miss/corruption handling —
  `cache/coordinator_test.go`, `cache/file/file_test.go`.
- Append-only durable transition journal, revisioned, with exclusive
  ownership and conflict detection — `state/file/file_test.go`
  (`TestJournalRoundTripAndRevision`, `TestJournalRejectsConcurrentController`).
- Compatible resume that revalidates output manifests and transitively
  invalidates dependents — `engine/scheduler_test.go:45,73,107`.
- Deterministic, symlink-safe archive transfer — `workspace/workspace_test.go`.
- A deliberately crude SSH target contract falsification (transfer, remote
  exec, cleanup) — `target/ssh/ssh_test.go`. Explicitly **not** proof of a
  production remote provider (see baseline.md limitations).

### Unproven (present in code or docs, but no test/source evidence found in this pass)

- Any claim that `runner/command`, `runner/just`, or `terminal` behave
  correctly beyond compiling — no package-local tests exist (Section 1).
- Task/Just adapters' cache-identity sensitivity to installed runner version
  (Fable Medium #8 above) — code exists (`runner/taskfile.go`,
  `runner/just.go` both declare a `Version` field per their `go doc` output)
  but no test exercises it.
- Retry-attempt/output-identity reset specifically on resume (Fable Medium
  #2 above) — plausible from adjacent scheduler tests but not directly
  asserted.
- Any performance or latency property (cold/warm discovery, cache-hit
  latency) — out of scope for this inventory; see TF-001.03.
- Cache-hit ordering relative to worker/environment acquisition — out of
  scope for this inventory; see TF-001.04 (baseline.md already flags this as
  a known limitation: "The runtime acquires and probes an environment before
  cache lookup can finish").

### Disproven / explicitly retracted by the prototype's own documentation

- That `target.Environment` is a reproducible sandbox — baseline.md states
  the local provider "shares the checkout and inherits ambient host state; it
  is not a reproducible sandbox," and no test in this inventory contradicts
  that.
- That the source materializer captures one immutable run snapshot —
  baseline.md states it "captures the live workspace during each
  acquisition," not a single immutable snapshot; consistent with there being
  no test asserting immutability across concurrent mutation during a single
  run (only `target/local/local_test.go:59`
  `TestEnvironmentRejectsEscapingDirectory`, which is a path-traversal check,
  not a snapshot-immutability check).
- That the current public graph surface (`flow.Step`, `flow.Ref`, string path
  patterns, functional options) is the product's typed authoring API —
  baseline.md is explicit that there is "no typed project-domain value model
  such as `Artifact[T]`, `Service[T]`, `Endpoint[T]`, `Optional[T]`, or
  `Effect[T]`," which this inventory's `flow` package doc confirms by
  omission (no such types appear in `raw-inventory/godoc/flow.txt`).

None of the above proven items imply API stability. `prototype/bootstrap` is
preserved evidence; new production code must not import it
(`AGENTS.md`, `docs/roadmap.md` section 3).

## 4. Limitations and open questions

- This inventory covers the module's own test suite as of revision `9ddea88`
  on macOS/arm64; it does not re-run cross-platform (`lock_other.go` vs.
  `lock_unix.go` in `state/file`) behavior, which is an explicit source-level
  fork not exercised on this machine.
- "Covered" in Section 2 means a test exists that plausibly exercises the
  fixed behavior, established by reading the test body's assertions; it is
  not a fresh adversarial re-verification of the original Fable exploit.
- The two explicit gaps found (retry/resume attempt reset; runner
  version-probe cache identity) are new findings from this inventory pass,
  not carried over from the Fable review's own "Test gaps" section (which
  lists different, forward-looking gaps: Sprite provider, single immutable
  snapshot, recursive `replace`-module hashing, distributed journal leases,
  execution-group GC — all still open per baseline.md).
- Open question for TF-001.05 / G0: do the two gaps above (Section 2, Medium
  #2 and #8) need a regression test before G0 accepts this evidence, or are
  they acceptable residual risk given neither blocks Risk Lab experiments
  E01-E08 (they are optimizations/observability of the prototype, not
  semantic-model risks)? This inventory does not decide that; it hands the
  question to TF-001.05.
