# T1 lifecycle fault-injection fixtures

Roadmap tranche: T1. Task: TF-002.06. Version: `t1-lifecycle-faults-v2-experimental`
(`ScenarioVersion` in `lifecycle.go`, roadmap section 3 rule 3a).

Status: pre-Gate-1 experimental fixture/harness. Not a production package,
carries no compatibility promise, and must not be imported by any production
code.

v2 fixed several gaps an independent Codex adversarial review found in v1 -
see "What changed in v2" below. v1 is not preserved; git history has it if
needed.

## Question

Roadmap section 8 deliverable 4 asks for deterministic injectors for
"process crash, daemon restart, worker loss, corrupt artifact, cancellation,
lease expiry, and source mutation." This ticket covers the five lifecycle
faults in its own acceptance criteria - process crash, daemon restart,
worker loss, cancellation, and lease expiry. (Corrupt artifact and source
mutation are TF-002.07's integrity/source-mutation fixtures, a distinct
ticket - not duplicated here.)

## Why this is abstract, not tied to a real daemon

Roadmap section 9's E05 ("daemon, fairness, and durable lease simulation")
is itself explicitly "a scheduler simulation with fake local, Linux, macOS,
simulator, and device providers... do not execute real builds." There is no
real daemon, scheduler, or provider anywhere in this repository today
(`prototype/bootstrap`'s scheduler is frozen evidence, not a production
target - `AGENTS.md`/roadmap section 3). This package therefore models the
abstract mechanics a future scheduler's state machine must get right -
durable commit ordering, crash/restart recovery, worker-loss retry,
cancellation semantics, lease expiry - using its own checkpoint vocabulary
(`Checkpoint`, `Event`, `Journal`) rather than presuming any concrete
daemon design. `CheckpointDownstreamPlaced`/`CheckpointDownstreamComplete`
stand in for W2's "test"/"inspect" node placement after the primary
"build"-equivalent work finishes - this package does not use W2's literal
node names, only the same shape.

## Relationship to fixtures/w2 and fixtures/w3 (read-only cross-reference)

Two of these five scenarios already have partial specifications elsewhere,
each explicitly waiting on an executable harness. This package implements
their "Assertions a harness must implement" sections for real, generically
(not tied to W2's node names), citing the specific assertion each test
checks - it does not modify either fixture's own files.

- `fixtures/w2/golden/worker-loss.md` and `cancellation.md` (TF-002.02):
  `scenario_worker_loss_test.go` implements assertions 1-4 (detection is
  recorded with a measured latency; retry starts from scratch; exactly one
  successful completion survives; downstream placement strictly follows
  the retry's completion). `scenario_cancellation_test.go` implements both
  golden sub-cases as W2 itself sets them up - **both starting from
  completed primary work** (cancellation.md: "both starting from a run
  where build has completed") - including the worker-release event for
  cancel-while-running and manifest retention in both sub-cases.
- `fixtures/w3/examples/scenario-caller-loss.json` (TF-002.03):
  `lease.go`/`scenario_lease_expiry_test.go` implement the exact
  `lease.heartbeat.missed -> lease.expired -> orphan.detected ->
  orphan.reclaimed` sequence with the same record fields (namespace_id,
  lease_id, resource_id), not only the event names.

## Scenarios and what each demonstrates

| Scenario | File | Key assertions |
| --- | --- | --- |
| Process crash | `scenario_process_crash_test.go` | Every checkpoint (7, including downstream placement) can be crashed before or after its durable commit (AC #2); nothing after the crash point is ever committed |
| Daemon restart | `scenario_daemon_restart_test.go` | Genuinely crosses a persistence boundary (`Journal.Snapshot`/`LoadJournal` into a separate object, not the same in-memory journal); zero lost committed events, checked two ways - byte-for-byte pre/post comparison, AND an independent per-checkpoint count anchored to the constant `StandardLifecycle` (the first check alone cannot catch a bug that always drops one checkpoint, since that reproduces identically before and after "restart" - see "Adversarial self-checks" below); covers restarts during admission, execution, and cleanup (E05's explicit requirement) with both injection timings; recovery never repeats work and never resumes a cancelled run |
| Worker loss | `scenario_worker_loss_test.go` | Loss is detected with a measured, bounded detection latency; the worker's own reservation is durably released; retry starts from scratch; strict event ordering (worker-lost < retry-complete < downstream-placed), not just existence; the detecting controller itself can crash before/after recording the loss (AC #2) |
| Cancellation | `scenario_cancellation_test.go` | Both W2 golden sub-cases, matching W2's actual setup (primary work already complete in both); cancel-while-running records a resource-released event and retains the completed primary work's record; cancel-before-placement places nothing downstream; a cancelled run is never resumed by daemon-restart recovery; the controller recording cancellation can itself crash before/after that commit (AC #2) |
| Lease expiry | `scenario_lease_expiry_test.go` | The full w3 record shape (namespace_id, lease_id, resource_id, outcome) per event, not only event names; multiple simultaneously-expiring leases reclaim in deterministic sorted-ID order (not Go map iteration order); an injection seam between each reclamation stage so a crash mid-reclamation resumes without repeating stages (AC #2) |

## Adversarial self-checks performed during implementation

- Confirmed the daemon-restart persistence boundary is real: temporarily
  mutated `Journal.Commit` to silently drop `CheckpointAdmit` events (the
  exact mutation an independent Codex review suggested) and re-ran
  `TestScenarioDaemonRestart` - it failed, citing the missing admit events,
  before the mutation was reverted. A first attempt at this fix (adding
  `Snapshot`/`LoadJournal` alone) did NOT catch this specific mutation,
  because a checkpoint dropped unconditionally by `Commit` is missing
  identically before and after "restart," so a purely relative
  byte-for-byte comparison passes vacuously; the independent per-checkpoint
  count anchored to `StandardLifecycle` (added after finding this) is what
  actually catches it.
- Confirmed the lease-expiry sorted-order fix is not order-dependent by
  running the multi-lease test across several iterations with leases
  acquired in non-sorted order.

## Limitations

- `IncompleteRuns` tracks runs from `CheckpointAdmit` onward (any committed
  standard-lifecycle checkpoint counts). A run whose admission itself was
  never durably recorded at all (a crash strictly before the admit commit)
  is outside this abstraction's recovery scope by definition - there is
  nothing durable to recover from; a real caller would need to resubmit it.
- The logical clock in `lease.go` and the detection-latency tick counter in
  `lifecycle.go` are simulated ticks, not wall-clock time; this makes both
  deterministic and instant to test but does not itself validate any real
  TTL/heartbeat/detection-latency timing budget - the 50-tick bound in
  `scenario_worker_loss_test.go` is this test's own illustrative choice,
  not a roadmap number.
- This package's checkpoint vocabulary and event shapes are this ticket's
  own abstraction. E05's eventual scheduler simulation (and any real
  daemon after Gate 1) is not obligated to reuse them; they exist so E05
  has a concrete, versioned, already-tested target to validate against or
  diverge from with evidence, per roadmap section 2.3.
- "Repeated work" here means a duplicate `ok` event for the same
  checkpoint; it does not model resource-level side effects (e.g. two
  builds writing to the same disk path), which is closer to TF-002.07's
  integrity/source-mutation territory.
- The worker-loss and cancellation scenarios exercise this package's own
  generic checkpoint vocabulary, not fixtures/w2/graph.json's literal
  `build`/`test`/`inspect` node identifiers - a future harness that
  actually drives fixtures/w2 will need its own mapping between the two,
  not provided here.

## Verification command

```sh
cd fixtures/t1-lifecycle-faults
mise trust
mise install
mise exec -- task check
```
