package lifecyclefaults

import "testing"

// TestScenarioDaemonRestart covers roadmap section 8 deliverable 4's
// "daemon restart" injector and directly implements the initial budget in
// roadmap section 8: "no lost durable event after injected daemon restart"
// (AC #4). It simulates the whole scheduler dying mid-batch while several
// runs are at different checkpoints, then genuinely crosses a persistence
// boundary via Journal.Snapshot/LoadJournal (NOT the same *Journal
// pointer - an earlier version of this test reused the same in-memory
// object before and after "restart", which made event preservation true
// by construction rather than a tested property; an independent Codex
// adversarial review found this and a concrete mutation - Commit silently
// not appending an event - that would still have passed the old test).
// The restarted journal here shares no memory with the pre-restart one.
func TestScenarioDaemonRestart(t *testing.T) {
	j := NewJournal()

	// Three runs, three different states when the daemon dies:
	// run-a completes fully before the restart;
	// run-b is mid-execution (admit + execute-start committed, nothing more);
	// run-c has not started at all.
	if err := RunLifecycle(j, "run-a", StandardLifecycle, nil); err != nil {
		t.Fatalf("run-a: unexpected error: %v", err)
	}
	if err := RunLifecycle(j, "run-b", StandardLifecycle, &Fault{AtCheckpoint: CheckpointExecuteComplete, Timing: BeforeCommit}); err != ErrCrashed {
		t.Fatalf("run-b: expected ErrCrashed, got %v", err)
	}
	// run-c: nothing committed at all yet.

	restartAndRecover(t, j, map[string]bool{"run-b": true}, []string{"run-a", "run-b"})
}

// TestScenarioDaemonRestartDuringAdmission covers E05's requirement
// (roadmap section 9: "daemon restarts during admission, execution, and
// cleanup") for the admission phase specifically, with both before/after
// injection timings (AC #2) - a gap an independent Codex adversarial
// review found: the original version only exercised a restart during
// execution.
func TestScenarioDaemonRestartDuringAdmission(t *testing.T) {
	for _, timing := range []FaultTiming{BeforeCommit, AfterCommit} {
		t.Run(string(timing), func(t *testing.T) {
			j := NewJournal()
			err := RunLifecycle(j, "run-admit", StandardLifecycle, &Fault{AtCheckpoint: CheckpointAdmit, Timing: timing})
			if err != ErrCrashed {
				t.Fatalf("expected ErrCrashed, got %v", err)
			}

			wantIncomplete := map[string]bool{}
			if timing == AfterCommit {
				// admit committed durably before the crash, so this run
				// has begun and is incomplete; recovery must resume it
				// from admit onward.
				wantIncomplete["run-admit"] = true
			}
			// If timing == BeforeCommit, admit itself was never committed
			// at all, so IncompleteRuns (which tracks any run with at
			// least one committed standard-lifecycle checkpoint, from
			// admit onward) will not see it either - there is nothing
			// durable to recover from, documented in README.md's
			// limitations.
			restartAndRecover(t, j, wantIncomplete, nil)
		})
	}
}

// TestScenarioDaemonRestartDuringCleanup covers E05's cleanup-phase
// restart requirement, with both before/after injection timings. A crash
// injected AFTER cleanup-complete's own commit means the run had already
// fully finished at the moment of the crash - it is not incomplete, and
// restartAndRecover's checkTerminal check alone (not resume) verifies that.
func TestScenarioDaemonRestartDuringCleanup(t *testing.T) {
	for _, timing := range []FaultTiming{BeforeCommit, AfterCommit} {
		t.Run(string(timing), func(t *testing.T) {
			j := NewJournal()
			err := RunLifecycle(j, "run-cleanup", StandardLifecycle, &Fault{AtCheckpoint: CheckpointCleanupComplete, Timing: timing})
			if err != ErrCrashed {
				t.Fatalf("expected ErrCrashed, got %v", err)
			}
			wantIncomplete := map[string]bool{}
			if timing == BeforeCommit {
				// cleanup-complete never committed, so cleanup-start is
				// this run's last durable checkpoint - genuinely
				// incomplete and must be resumed.
				wantIncomplete["run-cleanup"] = true
			}
			// timing == AfterCommit: cleanup-complete already committed
			// before the crash, so the run had already fully finished -
			// not incomplete, nothing to resume.
			restartAndRecover(t, j, wantIncomplete, []string{"run-cleanup"})
		})
	}
}

// restartAndRecover crosses a genuine persistence boundary (Snapshot then
// LoadJournal into a fresh *Journal), asserts IncompleteRuns matches
// wantIncomplete exactly, resumes every incomplete run, and then asserts
// (a) every event present before the restart is still present afterward,
// byte-for-byte, and (b) every run named in checkTerminal independently has
// exactly one "ok" event for EVERY checkpoint in StandardLifecycle - not
// merely execute-complete/cleanup-complete, and not derived by re-reading
// j (an adversarial self-check found that a Commit bug which always drops
// a given checkpoint, present before the "restart" as much as after it,
// passes a purely relative pre-vs-post comparison vacuously; only an
// assertion anchored to the constant StandardLifecycle, independent of
// what j actually contains, catches that class of bug).
func restartAndRecover(t *testing.T, j *Journal, wantIncomplete map[string]bool, checkTerminal []string) {
	t.Helper()

	preRestart := j.Events()
	data, err := j.Snapshot()
	if err != nil {
		t.Fatalf("Snapshot: %v", err)
	}

	// The restarted journal is a genuinely separate object built only from
	// the serialized bytes - j itself is never touched again below.
	restarted, err := LoadJournal(data)
	if err != nil {
		t.Fatalf("LoadJournal: %v", err)
	}

	gotIncomplete := IncompleteRuns(restarted)
	if len(gotIncomplete) != len(wantIncomplete) {
		t.Fatalf("IncompleteRuns after restart = %v, want exactly the keys of %v", gotIncomplete, wantIncomplete)
	}
	for _, runID := range gotIncomplete {
		if !wantIncomplete[runID] {
			t.Fatalf("unexpected incomplete run %q after restart", runID)
		}
	}

	for _, runID := range gotIncomplete {
		if err := ResumeLifecycle(restarted, runID); err != nil {
			t.Fatalf("ResumeLifecycle(%q): unexpected error: %v", runID, err)
		}
	}

	// Core assertion (AC #4 / roadmap's initial budget): every event
	// committed before the restart is still present, byte-for-byte, in the
	// genuinely-reloaded journal. Recovery must be strictly additive.
	postRestart := restarted.Events()
	if len(postRestart) < len(preRestart) {
		t.Fatalf("lost committed events across restart: had %d before, %d after", len(preRestart), len(postRestart))
	}
	for i, e := range preRestart {
		if postRestart[i] != e {
			t.Fatalf("event %d changed across restart: had %+v, now %+v", i, e, postRestart[i])
		}
	}

	for _, runID := range checkTerminal {
		// Independent absolute check, anchored to the constant
		// StandardLifecycle rather than derived from j/restarted: every
		// checkpoint must have exactly one "ok" event. This is what
		// catches a Commit bug that always silently drops one particular
		// checkpoint (e.g. admit) - such a bug reproduces identically in
		// preRestart and postRestart, so the byte-for-byte comparison
		// above cannot see it; only checking against the independent,
		// hardcoded expectation below can.
		for _, cp := range StandardLifecycle {
			if n := restarted.CountEvents(runID, cp, "ok"); n != 1 {
				t.Fatalf("run %q has %d %q events after recovery, want exactly 1 (either lost or repeated work)", runID, n, cp)
			}
		}
	}
}
