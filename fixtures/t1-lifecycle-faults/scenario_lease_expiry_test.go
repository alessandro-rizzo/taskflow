package lifecyclefaults

import (
	"bytes"
	"encoding/json"
	"errors"
	"testing"
)

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

	// AC #1/#2: crash on either side of every reclamation-stage commit,
	// persist journal and lease state independently, reconstruct fresh
	// objects, and resume exactly once from the saved prefix.
	t.Run("every reclamation crash point survives a fresh-manager restart", func(t *testing.T) {
		for stageIndex, stage := range reclaimStages {
			for _, timing := range []FaultTiming{BeforeCommit, AfterCommit} {
				t.Run(string(stage)+"/"+string(timing), func(t *testing.T) {
					journal := NewJournal()
					manager := NewLeaseManager(journal)
					manager.Acquire("lease-crash", "ns-crash", "resource-crash", 10)
					manager.Advance(11)

					err := manager.CheckExpiryOne("lease-crash", &Fault{AtCheckpoint: stage, Timing: timing})
					if !errors.Is(err, ErrCrashed) {
						t.Fatalf("expected ErrCrashed, got %v", err)
					}
					wantPersistedStage := stageIndex
					if timing == AfterCommit {
						wantPersistedStage++
					}
					if got := manager.leases["lease-crash"].reclaimStage; got != wantPersistedStage {
						t.Fatalf("in-memory stage after crash = %d, want %d", got, wantPersistedStage)
					}

					restarted := snapshotAndReloadLeaseManager(t, manager)
					if restarted == manager || restarted.journal == journal || restarted.leases["lease-crash"] == manager.leases["lease-crash"] {
						t.Fatal("restart must reconstruct manager, journal, and lease without shared memory")
					}
					if got := restarted.leases["lease-crash"].reclaimStage; got != wantPersistedStage {
						t.Fatalf("reloaded stage = %d, want %d", got, wantPersistedStage)
					}
					if !restarted.Active("lease-crash") {
						t.Fatal("a crash-point lease, including after the final commit, must remain active until resume finalizes it")
					}

					if err := restarted.ResumeReclamation("lease-crash"); err != nil {
						t.Fatalf("ResumeReclamation: %v", err)
					}
					assertCanonicalReclamation(t, restarted.journal, "lease-crash")
					if restarted.Active("lease-crash") {
						t.Fatal("lease must be inactive after reclamation completes")
					}
				})
			}
		}
	})
}

func TestLeaseStateRoundTripHasNoSharedMemory(t *testing.T) {
	journal := NewJournal()
	manager := NewLeaseManager(journal)
	manager.Acquire("lease-z", "ns-z", "resource-z", 20)
	manager.Advance(4)
	manager.Renew("lease-z")
	manager.Acquire("lease-a", "ns-a", "resource-a", 7)
	manager.Advance(3)

	first, err := manager.LeaseStateSnapshot()
	if err != nil {
		t.Fatalf("LeaseStateSnapshot: %v", err)
	}
	second, err := manager.LeaseStateSnapshot()
	if err != nil {
		t.Fatalf("second LeaseStateSnapshot: %v", err)
	}
	if !bytes.Equal(first, second) {
		t.Fatalf("identical state must serialize deterministically:\nfirst:  %s\nsecond: %s", first, second)
	}

	restarted := snapshotAndReloadLeaseManager(t, manager)
	if restarted == manager || restarted.journal == journal {
		t.Fatal("restart reused manager or journal memory")
	}
	if restarted.now != 7 {
		t.Fatalf("logical clock = %d, want 7", restarted.now)
	}
	leaseZ := restarted.leases["lease-z"]
	if leaseZ == nil || leaseZ == manager.leases["lease-z"] {
		t.Fatal("lease-z was absent or shared with the original manager")
	}
	if leaseZ.TTL != 20 || leaseZ.acquiredAt != 0 || leaseZ.renewedAt != 4 || !leaseZ.active || leaseZ.reclaimStage != 0 {
		t.Fatalf("lease-z fields did not round-trip: %+v", leaseZ)
	}

	manager.now = 999
	manager.leases["lease-z"].NamespaceID = "mutated-original"
	if restarted.now != 7 || restarted.leases["lease-z"].NamespaceID != "ns-z" {
		t.Fatal("mutating the original manager changed reloaded state")
	}
}

func TestLoadLeaseManagerRejectsInvalidState(t *testing.T) {
	journal := NewJournal()
	manager := NewLeaseManager(journal)
	manager.Acquire("lease-1", "ns-1", "resource-1", 10)
	manager.Advance(5)
	valid, err := manager.LeaseStateSnapshot()
	if err != nil {
		t.Fatalf("LeaseStateSnapshot: %v", err)
	}

	tests := []struct {
		name       string
		data       []byte
		wantErr    error
		journalMut func(*Journal)
	}{
		{name: "malformed JSON", data: []byte(`{"format_version":`), wantErr: ErrInvalidLeaseState},
		{name: "trailing JSON value", data: append(append([]byte(nil), valid...), []byte(` {}`)...), wantErr: ErrInvalidLeaseState},
		{name: "missing format", data: mutateLeaseStateJSON(t, valid, func(document map[string]any) { delete(document, "format_version") }), wantErr: ErrInvalidLeaseState},
		{name: "incompatible format", data: mutateLeaseStateJSON(t, valid, func(document map[string]any) { document["format_version"] = "future-v99" }), wantErr: ErrIncompatibleLeaseState},
		{name: "unknown envelope field", data: mutateLeaseStateJSON(t, valid, func(document map[string]any) { document["unexpected"] = true }), wantErr: ErrInvalidLeaseState},
		{name: "missing active field", data: mutateLeaseStateJSON(t, valid, func(document map[string]any) { delete(firstLeaseRecord(t, document), "active") }), wantErr: ErrInvalidLeaseState},
		{name: "duplicate lease ID", data: mutateLeaseStateJSON(t, valid, func(document map[string]any) {
			leases := document["leases"].([]any)
			document["leases"] = append(leases, leases[0])
		}), wantErr: ErrInvalidLeaseState},
		{name: "blank lease ID", data: mutateLeaseStateJSON(t, valid, func(document map[string]any) { firstLeaseRecord(t, document)["id"] = " " }), wantErr: ErrInvalidLeaseState},
		{name: "non-positive TTL", data: mutateLeaseStateJSON(t, valid, func(document map[string]any) { firstLeaseRecord(t, document)["ttl_ticks"] = 0 }), wantErr: ErrInvalidLeaseState},
		{name: "impossible tick order", data: mutateLeaseStateJSON(t, valid, func(document map[string]any) { firstLeaseRecord(t, document)["renewed_at_tick"] = 6 }), wantErr: ErrInvalidLeaseState},
		{name: "stage out of range", data: mutateLeaseStateJSON(t, valid, func(document map[string]any) { firstLeaseRecord(t, document)["reclamation_stage"] = 5 }), wantErr: ErrInvalidLeaseState},
		{name: "reclamation before TTL expiry", data: mutateLeaseStateJSON(t, valid, func(document map[string]any) { firstLeaseRecord(t, document)["reclamation_stage"] = 1 }), wantErr: ErrInvalidLeaseState, journalMut: func(j *Journal) {
			j.commitFull("lease-1", reclaimStages[0], "expired", "", "ns-1", "resource-1")
		}},
		{name: "inactive during partial reclamation", data: mutateLeaseStateJSON(t, valid, func(document map[string]any) {
			record := firstLeaseRecord(t, document)
			record["active"] = false
			record["reclamation_stage"] = 1
		}), wantErr: ErrInvalidLeaseState},
		{name: "missing acquisition event", data: valid, wantErr: ErrInvalidLeaseState, journalMut: func(j *Journal) {
			j.events = nil
			j.nextSeq = 0
		}},
		{name: "acquisition identity disagrees", data: valid, wantErr: ErrInvalidLeaseState, journalMut: func(j *Journal) {
			j.events[0].NamespaceID = "wrong-namespace"
		}},
		{name: "duplicate acquisition event", data: valid, wantErr: ErrInvalidLeaseState, journalMut: func(j *Journal) {
			j.commitFull("lease-1", "lease.acquired", "ok", "", "ns-1", "resource-1")
		}},
		{name: "renewal metadata disagrees", data: valid, wantErr: ErrInvalidLeaseState, journalMut: func(j *Journal) {
			j.commitFull("lease-1", "lease.renewed", "ok", "", "ns-1", "wrong-resource")
		}},
		{name: "release contradicts active state", data: valid, wantErr: ErrInvalidLeaseState, journalMut: func(j *Journal) {
			j.commitFull("lease-1", "lease.released", "released", "", "ns-1", "resource-1")
		}},
		{name: "inactive state lacks release", data: mutateLeaseStateJSON(t, valid, func(document map[string]any) { firstLeaseRecord(t, document)["active"] = false }), wantErr: ErrInvalidLeaseState},
		{name: "release contradicts reclamation", data: valid, wantErr: ErrInvalidLeaseState, journalMut: func(j *Journal) {
			j.commitFull("lease-1", "lease.released", "released", "", "ns-1", "resource-1")
			j.commitFull("lease-1", reclaimStages[0], "expired", "", "ns-1", "resource-1")
		}},
		{name: "saved stage disagrees with journal", data: mutateLeaseStateJSON(t, valid, func(document map[string]any) { firstLeaseRecord(t, document)["reclamation_stage"] = 1 }), wantErr: ErrInvalidLeaseState},
		{name: "journal prefix exists for absent lease", data: valid, wantErr: ErrInvalidLeaseState, journalMut: func(j *Journal) {
			j.commitFull("absent", reclaimStages[0], "expired", "", "ns-absent", "resource-absent")
		}},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			journalData, snapshotErr := journal.Snapshot()
			if snapshotErr != nil {
				t.Fatalf("Journal.Snapshot: %v", snapshotErr)
			}
			reloadedJournal, loadErr := LoadJournal(journalData)
			if loadErr != nil {
				t.Fatalf("LoadJournal: %v", loadErr)
			}
			if test.journalMut != nil {
				test.journalMut(reloadedJournal)
			}
			got, loadErr := LoadLeaseManager(test.data, reloadedJournal)
			if got != nil {
				t.Fatalf("LoadLeaseManager returned partial manager %+v", got)
			}
			if !errors.Is(loadErr, test.wantErr) {
				t.Fatalf("error = %v, want errors.Is(_, %v)", loadErr, test.wantErr)
			}
		})
	}
}

func TestLoadLeaseManagerAcceptsReleasedLease(t *testing.T) {
	journal := NewJournal()
	manager := NewLeaseManager(journal)
	manager.Acquire("lease-released", "ns-released", "resource-released", 10)
	manager.Release("lease-released")

	restarted := snapshotAndReloadLeaseManager(t, manager)
	lease := restarted.leases["lease-released"]
	if lease == nil || lease.active || lease.reclaimStage != 0 {
		t.Fatalf("released stage-0 lease did not round-trip: %+v", lease)
	}
	if n := restarted.journal.CountEvents("lease-released", "lease.released", "released"); n != 1 {
		t.Fatalf("release event count = %d, want 1", n)
	}
}

func snapshotAndReloadLeaseManager(t *testing.T, manager *LeaseManager) *LeaseManager {
	t.Helper()
	journalData, err := manager.journal.Snapshot()
	if err != nil {
		t.Fatalf("Journal.Snapshot: %v", err)
	}
	leaseData, err := manager.LeaseStateSnapshot()
	if err != nil {
		t.Fatalf("LeaseStateSnapshot: %v", err)
	}
	restartedJournal, err := LoadJournal(journalData)
	if err != nil {
		t.Fatalf("LoadJournal: %v", err)
	}
	restarted, err := LoadLeaseManager(leaseData, restartedJournal)
	if err != nil {
		t.Fatalf("LoadLeaseManager: %v", err)
	}
	return restarted
}

func assertCanonicalReclamation(t *testing.T, journal *Journal, leaseID string) {
	t.Helper()
	want := []Checkpoint{"lease.acquired", "lease.heartbeat.missed", "lease.expired", "orphan.detected", "orphan.reclaimed"}
	events := journal.EventsForRun(leaseID)
	if len(events) != len(want) {
		t.Fatalf("event count = %d, want %d: %+v", len(events), len(want), events)
	}
	for index, event := range events {
		if event.Checkpoint != want[index] {
			t.Fatalf("event %d = %q, want %q: %+v", index, event.Checkpoint, want[index], events)
		}
		if n := journal.CountEvents(leaseID, want[index], event.Outcome); n != 1 {
			t.Fatalf("checkpoint %q count = %d, want exactly 1", want[index], n)
		}
	}
}

func mutateLeaseStateJSON(t *testing.T, data []byte, mutate func(map[string]any)) []byte {
	t.Helper()
	var document map[string]any
	if err := json.Unmarshal(data, &document); err != nil {
		t.Fatalf("decode seed lease state: %v", err)
	}
	mutate(document)
	mutated, err := json.Marshal(document)
	if err != nil {
		t.Fatalf("encode mutated lease state: %v", err)
	}
	return mutated
}

func firstLeaseRecord(t *testing.T, document map[string]any) map[string]any {
	t.Helper()
	leases, ok := document["leases"].([]any)
	if !ok || len(leases) == 0 {
		t.Fatalf("seed state has no leases: %+v", document)
	}
	record, ok := leases[0].(map[string]any)
	if !ok {
		t.Fatalf("seed lease has unexpected shape: %+v", leases[0])
	}
	return record
}
