package lifecyclefaults

import "testing"

// TestScenarioCancellation covers roadmap section 8 deliverable 4's
// "cancellation" injector, mirroring fixtures/w2/golden/cancellation.md's
// two sub-cases at this package's abstract level. Both sub-cases start
// from a run where the primary work ("build", ExecuteComplete) has already
// completed - matching cancellation.md's own setup exactly ("both starting
// from a run where build has completed") - which an independent Codex
// adversarial review found the original version of this test did not: its
// "cancel-while-running" cancelled during ExecuteStart, before any build
// analogue had completed, so it could not check cancellation.md's
// assertion 4 (manifest retention) in that sub-case, and never recorded a
// worker-release/cleanup event for the in-flight work being stopped.
func TestScenarioCancellation(t *testing.T) {
	t.Run("cancel-while-running", func(t *testing.T) {
		j := NewJournal()
		runID := "run-cancel-while-running"

		// build-equivalent work completes, then downstream (test/inspect
		// equivalent) placement starts and is actively running when
		// cancellation arrives.
		if err := RunLifecycle(j, runID, []Checkpoint{CheckpointAdmit, CheckpointExecuteStart, CheckpointExecuteComplete, CheckpointDownstreamPlaced}, nil); err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		Cancel(j, runID, "caller requested cancellation while downstream work is running")

		if !IsCancelled(j, runID) {
			t.Fatal("expected the run to carry a durable cancelled event")
		}
		// The active downstream execution is stopped, not left running
		// unattended (cancellation.md: "the active test execution is
		// stopped ... not left running unattended").
		if n := j.CountEvents(runID, CheckpointDownstreamComplete, "ok"); n != 0 {
			t.Fatalf("cancel-while-running must not record a successful downstream-complete, got %d", n)
		}
		// Its worker/workspace is released within a bounded window, not
		// left as an orphaned reservation (cancellation.md's explicit
		// requirement) - this is what Cancel's resource-released event
		// implements; check it is actually present, not merely that Cancel
		// exists.
		if n := j.CountEvents(runID, "resource-released", "released"); n != 1 {
			t.Fatalf("cancel-while-running must record a resource-released event for the in-flight work, got %d", n)
		}
		// The already-completed build's manifest/state remains present and
		// unaltered (cancellation.md assertion 4, which the original test
		// never checked for this sub-case because nothing had completed
		// yet in it).
		if n := j.CountEvents(runID, CheckpointExecuteComplete, "ok"); n != 1 {
			t.Fatalf("cancel-while-running must retain the completed execute-complete event, got %d", n)
		}
	})

	t.Run("cancel-before-placement", func(t *testing.T) {
		j := NewJournal()
		runID := "run-cancel-before-placement"

		// admit, execute-start, and execute-complete all finish normally
		// (analogous to W2's "build" completing) before cancellation
		// arrives, so downstream (test/inspect) is never placed at all.
		if err := RunLifecycle(j, runID, []Checkpoint{CheckpointAdmit, CheckpointExecuteStart, CheckpointExecuteComplete}, nil); err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		Cancel(j, runID, "caller requested cancellation before downstream placement")

		if !IsCancelled(j, runID) {
			t.Fatal("expected the run to carry a durable cancelled event")
		}
		// The already-completed upstream work is retained
		// (cancellation.md: "a cancellation does not retroactively
		// invalidate upstream work that already durably succeeded").
		if n := j.CountEvents(runID, CheckpointExecuteComplete, "ok"); n != 1 {
			t.Fatalf("cancel-before-placement must retain the already-completed execute-complete event, got %d", n)
		}
		// No downstream placement/acquisition event exists for this
		// sub-case at all.
		if n := j.CountEvents(runID, CheckpointDownstreamPlaced, "ok"); n != 0 {
			t.Fatalf("cancel-before-placement must not place downstream work, got %d", n)
		}
		// Nothing was in flight, so no release event is expected either -
		// there was nothing to release.
		if n := j.CountEvents(runID, "resource-released", "released"); n != 0 {
			t.Fatalf("cancel-before-placement must not record a resource-released event (nothing was in flight), got %d", n)
		}
	})

	// AC #2: the controller recording a cancellation can itself crash
	// before or after that "cancelled" event's own durable commit.
	for _, timing := range []FaultTiming{BeforeCommit, AfterCommit} {
		t.Run("cancel-crash/"+string(timing), func(t *testing.T) {
			j := NewJournal()
			runID := "run-cancel-crash"
			if err := RunLifecycle(j, runID, []Checkpoint{CheckpointAdmit, CheckpointExecuteStart, CheckpointExecuteComplete}, nil); err != nil {
				t.Fatalf("unexpected error: %v", err)
			}

			err := CancelWithFault(j, runID, "cancel during crash", timing)
			if err != ErrCrashed {
				t.Fatalf("expected ErrCrashed, got %v", err)
			}

			switch timing {
			case BeforeCommit:
				if IsCancelled(j, runID) {
					t.Fatal("crash before commit must not leave the cancelled event durably recorded")
				}
			case AfterCommit:
				if !IsCancelled(j, runID) {
					t.Fatal("crash after commit must leave the cancelled event durably recorded")
				}
			}
		})
	}

	t.Run("cancelled distinct from worker-lost and ordinary crash", func(t *testing.T) {
		jCancelled := NewJournal()
		Cancel(jCancelled, "run-x", "test")
		jWorkerLost := NewJournal()
		DetectWorkerLoss(jWorkerLost, "run-x", "test", 0, "")

		cancelledEvents := jCancelled.EventsForRun("run-x")
		lostEvents := jWorkerLost.EventsForRun("run-x")
		if cancelledEvents[0].Outcome == lostEvents[0].Outcome {
			t.Fatalf("cancelled and worker-lost outcomes must be distinguishable, both were %q", cancelledEvents[0].Outcome)
		}
	})

	t.Run("a cancelled run is never resumed by daemon restart recovery", func(t *testing.T) {
		j := NewJournal()
		runID := "run-cancel-not-resumed"
		if err := RunLifecycle(j, runID, []Checkpoint{CheckpointAdmit, CheckpointExecuteStart}, nil); err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		Cancel(j, runID, "cancelled before a later restart")

		if got := IncompleteRuns(j); len(got) != 0 {
			t.Fatalf("a cancelled run must not be reported incomplete/resumable, got %v", got)
		}
		if err := ResumeLifecycle(j, runID); err != nil {
			t.Fatalf("ResumeLifecycle on a cancelled run should be a no-op, got error: %v", err)
		}
		if n := j.CountEvents(runID, CheckpointExecuteComplete, "ok"); n != 0 {
			t.Fatal("ResumeLifecycle must not resurrect a cancelled run by continuing its checkpoints")
		}
	})
}
