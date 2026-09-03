package lifecyclefaults

import "testing"

// TestScenarioLeaseExpiry covers roadmap section 8 deliverable 4's "lease
// expiry" injector, implementing the exact
// lease.heartbeat.missed -> lease.expired -> orphan.detected ->
// orphan.reclaimed event sequence fixtures/w3/examples/scenario-caller-loss.json
// already declares at the namespace level, generically and executably,
// including that fixture's full record shape (namespace_id, lease_id,
// resource_id, an outcome) - not only its event names, which an
// independent Codex adversarial review found the original version of this
// test checked instead.
func TestScenarioLeaseExpiry(t *testing.T) {
	t.Run("renewed lease never expires", func(t *testing.T) {
		j := NewJournal()
		m := NewLeaseManager(j)
		m.Acquire("lease-1", "ns-1", "resource-1", 10)

		m.Advance(6)
		m.Renew("lease-1")
		m.Advance(6)
		reclaimed := m.CheckExpiry()

		if len(reclaimed) != 0 {
			t.Fatalf("a renewed-in-time lease must not expire, got reclaimed=%v", reclaimed)
		}
		if !m.Active("lease-1") {
			t.Fatal("lease-1 should still be active")
		}
	})

	t.Run("unrenewed lease expires and is reclaimed with the full w3 record shape", func(t *testing.T) {
		j := NewJournal()
		m := NewLeaseManager(j)
		m.Acquire("lease-2", "ns-2", "resource-2", 10)

		m.Advance(11) // TTL elapses with no renewal
		reclaimed := m.CheckExpiry()

		if len(reclaimed) != 1 || reclaimed[0] != "lease-2" {
			t.Fatalf("expected lease-2 to be reclaimed, got %v", reclaimed)
		}
		if m.Active("lease-2") {
			t.Fatal("lease-2 should no longer be active after expiry")
		}

		// Full record shape matching
		// fixtures/w3/examples/scenario-caller-loss.json field for field,
		// not only its event names: lease.heartbeat.missed/lease.expired
		// carry the lease id (this package's RunID field); orphan.detected/
		// orphan.reclaimed carry namespace_id and resource_id.
		want := []struct {
			checkpoint  string
			outcome     string
			namespaceID string
			resourceID  string
		}{
			{"lease.acquired", "ok", "ns-2", "resource-2"},
			{"lease.heartbeat.missed", "expired", "ns-2", "resource-2"},
			{"lease.expired", "expired", "ns-2", "resource-2"},
			{"orphan.detected", "expired", "ns-2", "resource-2"},
			{"orphan.reclaimed", "reclaimed", "ns-2", "resource-2"},
		}
		events := j.EventsForRun("lease-2")
		if len(events) != len(want) {
			t.Fatalf("event count = %d, want %d: got %+v", len(events), len(want), events)
		}
		for i, e := range events {
			w := want[i]
			if string(e.Checkpoint) != w.checkpoint || e.Outcome != w.outcome || e.NamespaceID != w.namespaceID || e.ResourceID != w.resourceID {
				t.Fatalf("event %d = %+v, want checkpoint=%q outcome=%q namespace_id=%q resource_id=%q", i, e, w.checkpoint, w.outcome, w.namespaceID, w.resourceID)
			}
		}
	})

	t.Run("late renewal after expiry does not resurrect the lease", func(t *testing.T) {
		j := NewJournal()
		m := NewLeaseManager(j)
		m.Acquire("lease-3", "ns-3", "resource-3", 10)
		m.Advance(11)
		m.CheckExpiry()

		m.Renew("lease-3") // must be a no-op
		if m.Active("lease-3") {
			t.Fatal("a late renewal must not resurrect an already-expired lease")
		}
		if n := j.CountEvents("lease-3", "lease.renewed", "ok"); n != 0 {
			t.Fatalf("expected no lease.renewed event after expiry, got %d", n)
		}
	})

	t.Run("multiple simultaneously-expiring leases reclaim in deterministic order", func(t *testing.T) {
		// A prior version of CheckExpiry iterated a Go map directly, which
		// does not guarantee order - an independent Codex adversarial
		// review flagged this as making a multi-lease scenario's expected
		// event sequence nondeterministic. Run this several times: a
		// map-order bug would show up as flakiness across iterations.
		for iter := 0; iter < 5; iter++ {
			j := NewJournal()
			m := NewLeaseManager(j)
			// Acquire in an order deliberately different from sorted-ID
			// order, so a correct sort is actually exercised.
			m.Acquire("lease-z", "ns-multi", "resource-z", 10)
			m.Acquire("lease-a", "ns-multi", "resource-a", 10)
			m.Acquire("lease-m", "ns-multi", "resource-m", 10)
			m.Advance(11)

			reclaimed := m.CheckExpiry()
			want := []string{"lease-a", "lease-m", "lease-z"}
			if len(reclaimed) != len(want) {
				t.Fatalf("iter %d: reclaimed = %v, want %v", iter, reclaimed, want)
			}
			for i := range want {
				if reclaimed[i] != want[i] {
					t.Fatalf("iter %d: reclaimed[%d] = %q, want %q (nondeterministic order): full result %v", iter, i, reclaimed[i], want[i], reclaimed)
				}
			}
		}
	})

	// AC #2 / review point 7: an injection seam between lease.expired,
	// orphan.detected, and orphan.reclaimed, so a restart mid-reclamation
	// can be exercised and resumed without re-emitting already-committed
	// stages.
	t.Run("crash during reclamation resumes without repeating stages", func(t *testing.T) {
		for _, timing := range []FaultTiming{BeforeCommit, AfterCommit} {
			t.Run(string(timing), func(t *testing.T) {
				j := NewJournal()
				m := NewLeaseManager(j)
				m.Acquire("lease-crash", "ns-crash", "resource-crash", 10)
				m.Advance(11)

				err := m.CheckExpiryOne("lease-crash", timing)
				if err != ErrCrashed {
					t.Fatalf("expected ErrCrashed, got %v", err)
				}
				// The lease must still be tracked (not silently dropped)
				// so a later resume can find it.
				preCount := len(j.EventsForRun("lease-crash"))

				if err := m.ResumeReclamation("lease-crash"); err != nil {
					t.Fatalf("ResumeReclamation: unexpected error: %v", err)
				}

				events := j.EventsForRun("lease-crash")
				want := []string{"lease.acquired", "lease.heartbeat.missed", "lease.expired", "orphan.detected", "orphan.reclaimed"}
				if len(events) != len(want) {
					t.Fatalf("after resume: event count = %d, want %d (preCount was %d before resume): got %+v", len(events), len(want), preCount, events)
				}
				for i, e := range events {
					if string(e.Checkpoint) != want[i] {
						t.Fatalf("after resume: event %d = %q, want %q - resume must not repeat or skip a stage: full sequence %+v", i, e.Checkpoint, want[i], events)
					}
				}
				if m.Active("lease-crash") {
					t.Fatal("expected lease-crash to be inactive after full reclamation completes")
				}
			})
		}
	})
}
