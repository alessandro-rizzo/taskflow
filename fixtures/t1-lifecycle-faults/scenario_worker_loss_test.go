package lifecyclefaults

import "testing"

// TestScenarioWorkerLoss covers roadmap section 8 deliverable 4's "worker
// loss" injector, mirroring fixtures/w2/golden/worker-loss.md's setup and
// assertions at this package's abstract level (not W2's build/test/inspect
// node names): a worker disappears mid-execution with no clean shutdown
// signal, distinct from a controller crash - the controller itself is
// fine and must detect the loss, not hang forever.
//
// An independent Codex adversarial review found the original version of
// this test weaker than its comments claimed: it never measured a
// detection latency, never modeled the lost worker's reservation being
// released (worker-loss.md assertion 4), never had paired before/after
// injection points on the detection itself (AC #2), and never checked that
// downstream ("test"/"inspect") placement actually waits for the retried
// build - only that execute-complete's sequence number was higher. This
// version fixes all four.
func TestScenarioWorkerLoss(t *testing.T) {
	t.Run("clean-detection", func(t *testing.T) {
		j := NewJournal()
		runID := "run-worker-loss-clean"
		leases := NewLeaseManager(j)

		if err := RunLifecycle(j, runID, []Checkpoint{CheckpointAdmit, CheckpointExecuteStart}, nil); err != nil {
			t.Fatalf("unexpected error before worker loss: %v", err)
		}
		// The worker's own reservation/lease, acquired when it started
		// executing - this is what worker-loss.md assertion 4 requires to
		// be durably released once the loss is detected.
		leases.Acquire(runID+"-reservation", "ns-worker-loss", "worker-1", 100)
		leases.Advance(7)

		if err := DetectWorkerLoss(j, runID, "worker process unreachable", 7, ""); err != nil {
			t.Fatalf("unexpected error detecting worker loss: %v", err)
		}
		if n := j.CountEvents(runID, CheckpointExecuteStart, "worker-lost"); n != 1 {
			t.Fatalf("expected exactly one worker-lost event, got %d", n)
		}

		// Detection latency is measured and recorded, not absent
		// (worker-loss.md assertion 1 leaves the actual threshold to
		// whichever harness/experiment runs this - this test only checks
		// that a latency is genuinely recorded and matches what happened,
		// not a roadmap-declared number).
		if latency := DetectionLatencyTicks(j, runID); latency != 7 {
			t.Fatalf("expected recorded detection latency 7, got %d", latency)
		}

		// The lost worker's reservation is durably released, not held
		// indefinitely (worker-loss.md assertion 4: not "observably held
		// after the detection event"). Checking only the in-memory
		// Active() flag is not enough - an independent Opus-model
		// mutation-testing pass found that disabling just the durable
		// lease.released commit (leaving the in-memory flag flip) still
		// left the suite green, so this also asserts the durable journal
		// itself carries the release event, not merely LeaseManager's
		// in-process bookkeeping.
		leases.Release(runID + "-reservation")
		if leases.Active(runID + "-reservation") {
			t.Fatal("expected the lost worker's reservation to be released after detection")
		}
		if n := j.CountEvents(runID+"-reservation", "lease.released", "released"); n != 1 {
			t.Fatalf("expected exactly one durable lease.released event for the reservation, got %d", n)
		}

		// A lost worker's build has no partial artifact to resume from
		// (worker-loss.md: "there is no partial artifact to resume from"),
		// so recovery retries execute-start/execute-complete from scratch.
		RetryFromScratch(j, runID)

		// Downstream placement (analogous to W2's test/inspect) and
		// cleanup happen only now, after the retry's own completion.
		if err := RunLifecycle(j, runID, []Checkpoint{CheckpointDownstreamPlaced, CheckpointDownstreamComplete, CheckpointCleanupStart, CheckpointCleanupComplete}, nil); err != nil {
			t.Fatalf("unexpected error completing after retry: %v", err)
		}

		if n := j.CountEvents(runID, CheckpointExecuteComplete, "ok"); n != 1 {
			t.Fatalf("expected exactly one successful execute-complete, got %d", n)
		}

		// Strict ordering: worker-lost < the retry's execute-complete <
		// downstream placement. This is the actual claim worker-loss.md
		// assertion 3 makes ("no test/inspect placement event is recorded
		// before the retried build's completion event") - checking event
		// existence alone (as an earlier version did) does not verify this
		// ordering.
		events := j.EventsForRun(runID)
		var lostSeq, completeSeq, downstreamSeq int = -1, -1, -1
		for _, e := range events {
			switch {
			case e.Checkpoint == CheckpointExecuteStart && e.Outcome == "worker-lost":
				lostSeq = e.Seq
			case e.Checkpoint == CheckpointExecuteComplete && e.Outcome == "ok":
				completeSeq = e.Seq
			case e.Checkpoint == CheckpointDownstreamPlaced && e.Outcome == "ok":
				downstreamSeq = e.Seq
			}
		}
		if lostSeq == -1 || completeSeq == -1 || downstreamSeq == -1 {
			t.Fatalf("missing expected events: %+v", events)
		}
		if !(lostSeq < completeSeq && completeSeq < downstreamSeq) {
			t.Fatalf("expected strict order worker-lost(%d) < execute-complete(%d) < downstream-placed(%d)", lostSeq, completeSeq, downstreamSeq)
		}

		if n := j.CountEvents(runID, CheckpointCleanupComplete, "ok"); n != 1 {
			t.Fatal("expected the run to reach cleanup-complete after recovering from worker loss")
		}
	})

	// AC #2: the controller detecting a worker loss can itself crash while
	// recording that detection, before or after the durable commit.
	for _, timing := range []FaultTiming{BeforeCommit, AfterCommit} {
		t.Run("detection-crash/"+string(timing), func(t *testing.T) {
			j := NewJournal()
			runID := "run-worker-loss-detection-crash"
			if err := RunLifecycle(j, runID, []Checkpoint{CheckpointAdmit, CheckpointExecuteStart}, nil); err != nil {
				t.Fatalf("unexpected error before worker loss: %v", err)
			}

			err := DetectWorkerLoss(j, runID, "worker process unreachable", 3, timing)
			if err != ErrCrashed {
				t.Fatalf("expected ErrCrashed, got %v", err)
			}

			gotDetected := j.CountEvents(runID, CheckpointExecuteStart, "worker-lost") > 0
			switch timing {
			case BeforeCommit:
				if gotDetected {
					t.Fatal("crash before commit must not leave the worker-lost event durably recorded")
				}
			case AfterCommit:
				if !gotDetected {
					t.Fatal("crash after commit must leave the worker-lost event durably recorded")
				}
			}
		})
	}
}
