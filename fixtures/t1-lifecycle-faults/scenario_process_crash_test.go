package lifecyclefaults

import "testing"

// TestScenarioProcessCrash covers roadmap section 8 deliverable 4's
// "process crash" injector. A run's own controller process is killed at a
// declared checkpoint, before or after that checkpoint's durable commit
// (AC #2). The test runs both timings against every checkpoint in
// StandardLifecycle to demonstrate the injection points are genuinely
// available at each transition, not just one hand-picked spot.
func TestScenarioProcessCrash(t *testing.T) {
	for _, cp := range StandardLifecycle {
		for _, timing := range []FaultTiming{BeforeCommit, AfterCommit} {
			t.Run(string(cp)+"/"+string(timing), func(t *testing.T) {
				j := NewJournal()
				runID := "run-crash-1"
				fault := &Fault{AtCheckpoint: cp, Timing: timing}

				err := RunLifecycle(j, runID, StandardLifecycle, fault)
				if err != ErrCrashed {
					t.Fatalf("expected ErrCrashed, got %v", err)
				}

				events := j.EventsForRun(runID)
				gotCrashCheckpoint := j.CountEvents(runID, cp, "ok") > 0

				switch timing {
				case BeforeCommit:
					if gotCrashCheckpoint {
						t.Fatalf("crash before commit at %q must not leave that checkpoint's event durably recorded, got: %+v", cp, events)
					}
				case AfterCommit:
					if !gotCrashCheckpoint {
						t.Fatalf("crash after commit at %q must leave that checkpoint's event durably recorded, got: %+v", cp, events)
					}
				}

				// No checkpoint after the crash point may have committed -
				// a crashed process cannot keep working.
				crashIdx := indexOf(StandardLifecycle, cp)
				for _, later := range StandardLifecycle[crashIdx+1:] {
					if j.CountEvents(runID, later, "ok") > 0 {
						t.Fatalf("checkpoint %q committed after the crash at %q, which is impossible for a genuinely crashed process", later, cp)
					}
				}
			})
		}
	}
}

func indexOf(cps []Checkpoint, target Checkpoint) int {
	for i, cp := range cps {
		if cp == target {
			return i
		}
	}
	return -1
}
