// Package lifecyclefaults implements deterministic, abstract lifecycle
// fault-injection scenarios for T1 (see docs/roadmap.md section 8,
// deliverable 4). It models the durable-transition mechanics a future
// scheduler/daemon (roadmap section 9's E05: "a scheduler simulation with
// fake local, Linux, macOS, simulator, and device providers... do not
// execute real builds") must get right, without presuming any concrete
// daemon, provider, or protocol design - none exists yet in this
// repository. Checkpoint names, event shapes, and injection semantics here
// are this package's own abstraction, not a claim about the future
// taskflowd's real state machine.
package lifecyclefaults

import (
	"encoding/json"
	"errors"
)

// ScenarioVersion is the only version this package's scenario definitions
// carry pre-Gate-1 (roadmap section 2.6, section 3 rule 3a): a breaking
// change to the checkpoint vocabulary or event semantics bumps this string.
// v2: added a real Snapshot/LoadJournal persistence boundary for
// daemon-restart (v1's restart test reused the same *Journal, making event
// preservation true by construction rather than a tested property),
// DownstreamPlaced/DownstreamComplete checkpoints so cancellation/worker-loss
// can assert what fixtures/w2/golden's docs require about downstream
// placement, cancellation-terminality in ResumeLifecycle, before/after
// injection points on worker-loss/cancellation/lease-reclamation, and
// namespace_id/resource_id fields on Event for full lease-record parity
// with fixtures/w3. Found by an independent Codex adversarial review.
const ScenarioVersion = "t1-lifecycle-faults-v2-experimental"

// Checkpoint names one durable-lifecycle transition point a run passes
// through. These are abstract stand-ins for whatever a real scheduler's
// state machine eventually calls its own transitions. DownstreamPlaced and
// DownstreamComplete stand in for W2's "test"/"inspect" node placement
// after the primary "build"-equivalent work (ExecuteComplete) finishes.
type Checkpoint string

const (
	CheckpointAdmit              Checkpoint = "admit"
	CheckpointExecuteStart       Checkpoint = "execute-start"
	CheckpointExecuteComplete    Checkpoint = "execute-complete"
	CheckpointDownstreamPlaced   Checkpoint = "downstream-placed"
	CheckpointDownstreamComplete Checkpoint = "downstream-complete"
	CheckpointCleanupStart       Checkpoint = "cleanup-start"
	CheckpointCleanupComplete    Checkpoint = "cleanup-complete"
)

// Event is one durable, committed lifecycle transition. Only committed
// events survive a simulated process crash or daemon restart; anything not
// yet appended to a Journal at the moment a fault fires is lost by
// construction - mirroring the "append-only durable run journal" roadmap
// section 12 describes for a real implementation. NamespaceID and
// ResourceID are populated only for lease/orphan events (see lease.go);
// they mirror the fields fixtures/w3/examples/scenario-caller-loss.json
// carries on its own orphan.* events, so a lease-expiry scenario can
// assert the full record, not just the event name.
type Event struct {
	Seq         int
	RunID       string // for lease events, this is the lease ID
	Checkpoint  Checkpoint
	Outcome     string
	Detail      string
	NamespaceID string
	ResourceID  string
}

// Journal is a durable append-only event log: the thing a "daemon restart"
// reloads from. Committing within one process never loses an event.
// Crossing a genuine restart requires Snapshot + LoadJournal below -
// reusing the same *Journal across a "restart" would make event
// preservation true by construction rather than by an actual persistence
// round trip.
type Journal struct {
	events  []Event
	nextSeq int
}

// NewJournal returns an empty durable journal.
func NewJournal() *Journal { return &Journal{} }

// Commit durably appends one event and returns it.
func (j *Journal) Commit(runID string, cp Checkpoint, outcome, detail string) Event {
	return j.commitFull(runID, cp, outcome, detail, "", "")
}

func (j *Journal) commitFull(runID string, cp Checkpoint, outcome, detail, namespaceID, resourceID string) Event {
	j.nextSeq++
	e := Event{Seq: j.nextSeq, RunID: runID, Checkpoint: cp, Outcome: outcome, Detail: detail, NamespaceID: namespaceID, ResourceID: resourceID}
	j.events = append(j.events, e)
	return e
}

// Events returns every committed event, in commit order. The returned slice
// is a copy; callers may not mutate the journal through it.
func (j *Journal) Events() []Event { return append([]Event(nil), j.events...) }

// EventsForRun returns every committed event for one run, in commit order.
func (j *Journal) EventsForRun(runID string) []Event {
	var out []Event
	for _, e := range j.events {
		if e.RunID == runID {
			out = append(out, e)
		}
	}
	return out
}

// CountEvents returns how many committed events for runID have the given
// checkpoint and outcome - the primitive TestScenarioWorkerLoss and
// TestScenarioDaemonRestart use to assert "exactly one successful
// completion, not zero and not two" (no lost work, no repeated work).
func (j *Journal) CountEvents(runID string, cp Checkpoint, outcome string) int {
	n := 0
	for _, e := range j.EventsForRun(runID) {
		if e.Checkpoint == cp && e.Outcome == outcome {
			n++
		}
	}
	return n
}

// Snapshot serializes every committed event to bytes, modeling what a real
// implementation would durably write to disk/a database.
func (j *Journal) Snapshot() ([]byte, error) {
	return json.Marshal(j.events)
}

// LoadJournal reconstructs a Journal purely from a Snapshot's bytes -
// modeling a fresh process reading durable storage after a restart. The
// returned Journal shares no memory with whatever produced data: an event
// silently dropped before or during snapshotting (a persistence bug) is
// genuinely absent here, not merely inaccessible through a stale
// reference. This is what makes "no lost events across a restart" a real
// check of a persistence boundary rather than a same-pointer tautology.
func LoadJournal(data []byte) (*Journal, error) {
	var events []Event
	if err := json.Unmarshal(data, &events); err != nil {
		return nil, err
	}
	j := &Journal{events: events}
	for _, e := range events {
		if e.Seq > j.nextSeq {
			j.nextSeq = e.Seq
		}
	}
	return j, nil
}

// FaultTiming says whether an injected fault fires immediately before or
// immediately after a checkpoint's durable commit. This is what lets a
// scenario declare injection points on both sides of the relevant durable
// transition (AC #2): "before-commit" loses the event entirely;
// "after-commit" loses only the work that would have happened next.
type FaultTiming string

const (
	BeforeCommit FaultTiming = "before-commit"
	AfterCommit  FaultTiming = "after-commit"
)

// Fault names one injected checkpoint failure.
type Fault struct {
	AtCheckpoint Checkpoint
	Timing       FaultTiming
}

// ErrCrashed is returned when an injected Fault fires, simulating a
// controller process dying at that exact point. It is not a real Go
// panic/os.Exit - callers return normally with this error so a test can
// inspect the Journal's state at the moment of the simulated crash.
var ErrCrashed = errors.New("lifecyclefaults: simulated process crash")

// RunLifecycle executes checkpoints in order for runID, committing a
// durable event at each one. If fault is non-nil and matches a checkpoint,
// RunLifecycle stops and returns ErrCrashed either immediately before or
// immediately after that checkpoint's event is committed, depending on
// fault.Timing. A nil fault runs the full sequence to completion.
func RunLifecycle(j *Journal, runID string, checkpoints []Checkpoint, fault *Fault) error {
	for _, cp := range checkpoints {
		if fault != nil && fault.AtCheckpoint == cp && fault.Timing == BeforeCommit {
			return ErrCrashed
		}
		j.Commit(runID, cp, "ok", "")
		if fault != nil && fault.AtCheckpoint == cp && fault.Timing == AfterCommit {
			return ErrCrashed
		}
	}
	return nil
}

// StandardLifecycle is the default checkpoint sequence a run passes
// through absent any fault: admission, primary execution ("build"),
// downstream placement ("test"/"inspect"), and cleanup.
var StandardLifecycle = []Checkpoint{
	CheckpointAdmit,
	CheckpointExecuteStart,
	CheckpointExecuteComplete,
	CheckpointDownstreamPlaced,
	CheckpointDownstreamComplete,
	CheckpointCleanupStart,
	CheckpointCleanupComplete,
}

// IncompleteRuns scans the journal and returns the RunIDs that reached any
// checkpoint in StandardLifecycle - including CheckpointAdmit alone, so a
// restart injected during admission is recoverable too (E05's requirement,
// roadmap section 9: "daemon restarts during admission, execution, and
// cleanup") - are not cancelled, but never reached CheckpointCleanupComplete.
// These are the runs a daemon restart's recovery pass must resume, in
// commit order of first appearance. A cancelled run is terminal, not
// incomplete (see ResumeLifecycle). A run with zero committed events at
// all (its admission itself was never durably recorded, e.g. a crash
// before the admit commit) is out of this abstraction's recovery scope by
// definition - there is nothing durable to recover from, documented as a
// limitation in README.md.
func IncompleteRuns(j *Journal) []string {
	lifecycleCheckpoint := map[Checkpoint]bool{}
	for _, cp := range StandardLifecycle {
		lifecycleCheckpoint[cp] = true
	}
	started := map[string]bool{}
	completed := map[string]bool{}
	var order []string
	for _, e := range j.Events() {
		if e.Outcome != "ok" || !lifecycleCheckpoint[e.Checkpoint] {
			continue
		}
		if !started[e.RunID] {
			order = append(order, e.RunID)
		}
		started[e.RunID] = true
		if e.Checkpoint == CheckpointCleanupComplete {
			completed[e.RunID] = true
		}
	}
	var out []string
	for _, runID := range order {
		if !completed[runID] && !IsCancelled(j, runID) {
			out = append(out, runID)
		}
	}
	return out
}

// LastCommittedCheckpoint returns the checkpoint (from StandardLifecycle's
// order) that runID last durably reached, or "" if it has no committed
// events at all.
func LastCommittedCheckpoint(j *Journal, runID string) Checkpoint {
	order := map[Checkpoint]int{}
	for i, cp := range StandardLifecycle {
		order[cp] = i
	}
	best := -1
	var last Checkpoint
	for _, e := range j.EventsForRun(runID) {
		if e.Outcome != "ok" {
			continue
		}
		if idx, ok := order[e.Checkpoint]; ok && idx > best {
			best = idx
			last = e.Checkpoint
		}
	}
	return last
}

// ResumeLifecycle continues runID from the checkpoint immediately after its
// LastCommittedCheckpoint through the end of StandardLifecycle, committing
// only checkpoints not already durably present.
//
// A cancelled run is terminal: ResumeLifecycle is a no-op for it. Without
// this check, a daemon-restart recovery pass could resurrect a run the
// caller had already explicitly cancelled, contradicting
// fixtures/w2/golden/cancellation.md's requirement that cancellation
// produce a final, explainable "cancelled" outcome.
func ResumeLifecycle(j *Journal, runID string) error {
	if IsCancelled(j, runID) {
		return nil
	}
	last := LastCommittedCheckpoint(j, runID)
	startIdx := 0
	for i, cp := range StandardLifecycle {
		if cp == last {
			startIdx = i + 1
			break
		}
	}
	return RunLifecycle(j, runID, StandardLifecycle[startIdx:], nil)
}

// Cancel commits a terminal "cancelled" event for runID (mirrors
// fixtures/w2/golden/cancellation.md's assertion 1). If runID's last
// committed checkpoint is CheckpointDownstreamPlaced (work is actively in
// flight, analogous to W2's "test" executing), Cancel first commits a
// "resource-released" event, modeling that the in-flight worker/workspace
// is released within a bounded window rather than left orphaned
// (cancellation.md: "its worker/workspace is released ... not left as an
// orphaned reservation").
func Cancel(j *Journal, runID, detail string) Event {
	if LastCommittedCheckpoint(j, runID) == CheckpointDownstreamPlaced {
		j.Commit(runID, "resource-released", "released", "in-flight downstream execution released on cancel")
	}
	return j.Commit(runID, "cancelled", "cancelled", detail)
}

// CancelWithFault behaves like Cancel but additionally supports injecting a
// crash immediately before or after the "cancelled" event's own commit
// (AC #2's paired injection-point requirement applied to cancellation
// itself).
func CancelWithFault(j *Journal, runID, detail string, timing FaultTiming) error {
	if LastCommittedCheckpoint(j, runID) == CheckpointDownstreamPlaced {
		j.Commit(runID, "resource-released", "released", "in-flight downstream execution released on cancel")
	}
	if timing == BeforeCommit {
		return ErrCrashed
	}
	j.Commit(runID, "cancelled", "cancelled", detail)
	if timing == AfterCommit {
		return ErrCrashed
	}
	return nil
}

// IsCancelled reports whether runID has a committed "cancelled" event.
func IsCancelled(j *Journal, runID string) bool {
	for _, e := range j.EventsForRun(runID) {
		if e.Checkpoint == "cancelled" && e.Outcome == "cancelled" {
			return true
		}
	}
	return false
}

// DetectWorkerLoss commits a durable "worker-lost" event for runID at
// CheckpointExecuteStart (mirrors fixtures/w2/golden/worker-loss.md's
// setup), plus a "worker-loss-detected" event recording detectedAtTick -
// the logical-clock tick detection happened at - so a scenario can assert
// a bounded detection latency instead of leaving it entirely unmeasured
// (worker-loss.md's assertion 1 leaves the threshold itself to the
// harness/experiment, but does require the latency to be recorded).
//
// timing supports the same before/after-commit injection AC #2 requires
// for every scenario: a zero-value timing ("") commits normally; a
// non-empty timing additionally simulates the controller crashing while it
// is in the middle of recording the loss.
func DetectWorkerLoss(j *Journal, runID, detail string, detectedAtTick int, timing FaultTiming) error {
	if timing == BeforeCommit {
		return ErrCrashed
	}
	j.commitFull(runID, CheckpointExecuteStart, "worker-lost", detail, "", "")
	j.Commit(runID, "worker-loss-detected", "ok", "detected_at_tick="+itoa(detectedAtTick))
	if timing == AfterCommit {
		return ErrCrashed
	}
	return nil
}

// DetectionLatencyTicks returns the detectedAtTick value DetectWorkerLoss
// recorded for runID, or -1 if no worker-loss-detected event exists.
func DetectionLatencyTicks(j *Journal, runID string) int {
	for _, e := range j.EventsForRun(runID) {
		if e.Checkpoint == "worker-loss-detected" && e.Outcome == "ok" {
			return atoi(e.Detail[len("detected_at_tick="):])
		}
	}
	return -1
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var buf [20]byte
	i := len(buf)
	for n > 0 {
		i--
		buf[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		buf[i] = '-'
	}
	return string(buf[i:])
}

func atoi(s string) int {
	n := 0
	neg := false
	for i, c := range s {
		if i == 0 && c == '-' {
			neg = true
			continue
		}
		if c < '0' || c > '9' {
			break
		}
		n = n*10 + int(c-'0')
	}
	if neg {
		n = -n
	}
	return n
}

// RetryFromScratch commits a fresh execute-start/execute-complete pair for
// runID after a worker-loss event, modeling that a build which never
// finished has no partial artifact to resume from
// (fixtures/w2/golden/worker-loss.md: "there is no partial artifact to
// resume from"), unlike ResumeLifecycle's checkpoint-preserving resume
// after a daemon restart.
func RetryFromScratch(j *Journal, runID string) {
	j.Commit(runID, CheckpointExecuteStart, "ok", "retry")
	j.Commit(runID, CheckpointExecuteComplete, "ok", "retry")
}
