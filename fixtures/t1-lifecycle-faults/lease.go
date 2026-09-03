package lifecyclefaults

import "sort"

// Lease is a resource hold with a time-to-live, modeling the abstract shape
// of the leases roadmap section 13 describes ("namespace and lease
// records, heartbeat, TTL, and reaper") and the concrete lease shape
// fixtures/w3/examples/scenario-caller-loss.json already illustrates at the
// namespace level (lease.heartbeat.missed -> lease.expired ->
// orphan.detected -> orphan.reclaimed). This package implements that same
// event vocabulary generically, and with the same event fields
// (namespace_id, lease_id, resource_id, an outcome), so it is executable
// and its records are directly comparable to that JSON fixture's shape,
// not only its event names.
type Lease struct {
	ID          string
	NamespaceID string
	ResourceID  string
	TTL         int // logical clock ticks
	acquiredAt  int
	renewedAt   int
	active      bool
	// reclaimStage is how far a lease's reclamation sequence has
	// progressed (0 = not started, len(reclaimStages) = fully reclaimed).
	// Tracked per lease so ResumeReclamation can continue exactly where an
	// injected fault left off, mirroring ResumeLifecycle's
	// LastCommittedCheckpoint mechanism for the main lifecycle.
	reclaimStage int
}

// LeaseManager tracks active leases against a logical clock (ticks, not
// wall-clock time) so lease-expiry is deterministic and instant to test.
type LeaseManager struct {
	journal *Journal
	now     int
	leases  map[string]*Lease
}

// NewLeaseManager returns a LeaseManager whose logical clock starts at 0.
func NewLeaseManager(j *Journal) *LeaseManager {
	return &LeaseManager{journal: j, leases: map[string]*Lease{}}
}

// Advance moves the logical clock forward by ticks.
func (m *LeaseManager) Advance(ticks int) { m.now += ticks }

// Acquire commits a lease-acquire event and starts tracking the lease.
func (m *LeaseManager) Acquire(leaseID, namespaceID, resourceID string, ttl int) {
	m.leases[leaseID] = &Lease{ID: leaseID, NamespaceID: namespaceID, ResourceID: resourceID, TTL: ttl, acquiredAt: m.now, renewedAt: m.now, active: true}
	m.journal.commitFull(leaseID, "lease.acquired", "ok", "", namespaceID, resourceID)
}

// Renew resets a lease's TTL countdown from the current logical time and
// commits a lease-renew event. Renewing after expiry is a no-op: an
// expired lease cannot be resurrected by a late renewal, it must be
// re-acquired.
func (m *LeaseManager) Renew(leaseID string) {
	l, ok := m.leases[leaseID]
	if !ok || !l.active {
		return
	}
	l.renewedAt = m.now
	m.journal.commitFull(leaseID, "lease.renewed", "ok", "", l.NamespaceID, l.ResourceID)
}

// Release explicitly releases leaseID outside of TTL expiry - the
// mechanism a worker-loss scenario uses to model that a lost worker's own
// reservation/lease is durably released once the loss is detected, rather
// than left held indefinitely (fixtures/w2/golden/worker-loss.md's
// assertion 4).
func (m *LeaseManager) Release(leaseID string) {
	l, ok := m.leases[leaseID]
	if !ok || !l.active {
		return
	}
	m.journal.commitFull(leaseID, "lease.released", "released", "", l.NamespaceID, l.ResourceID)
	l.active = false
}

// reclaimStages is the fixed, ordered reclamation sequence
// fixtures/w3/examples/scenario-caller-loss.json declares.
var reclaimStages = []Checkpoint{
	"lease.heartbeat.missed",
	"lease.expired",
	"orphan.detected",
	"orphan.reclaimed",
}

// reclaim runs leaseID's reclamation sequence starting from its current
// reclaimStage, committing one event per stage with the same
// namespace_id/resource_id fields fixtures/w3's fixture carries. If timing
// is non-empty, reclaim simulates a crash immediately before or after the
// commit for the FIRST stage it processes this call - this is the
// injection seam AC #2 requires between lease.expired, orphan.detected,
// and orphan.reclaimed: a controller can die in the middle of reclaiming
// an expired lease, and a later call (ResumeReclamation) must continue
// from exactly where it left off rather than re-emitting already-committed
// stages.
func (m *LeaseManager) reclaim(leaseID string, timing FaultTiming) error {
	l, ok := m.leases[leaseID]
	if !ok {
		return nil
	}
	first := true
	for l.reclaimStage < len(reclaimStages) {
		stage := reclaimStages[l.reclaimStage]
		outcome := "expired"
		if stage == "orphan.reclaimed" {
			outcome = "reclaimed"
		}
		if first && timing == BeforeCommit {
			return ErrCrashed
		}
		m.journal.commitFull(leaseID, stage, outcome, "", l.NamespaceID, l.ResourceID)
		l.reclaimStage++
		if first && timing == AfterCommit {
			return ErrCrashed
		}
		first = false
	}
	l.active = false
	return nil
}

// ResumeReclamation continues leaseID's reclamation sequence from wherever
// an earlier reclaim call (via CheckExpiry or CheckExpiryOne) left off
// after a simulated crash, without re-emitting stages already committed.
func (m *LeaseManager) ResumeReclamation(leaseID string) error {
	return m.reclaim(leaseID, "")
}

// CheckExpiry evaluates every active lease against the current logical
// clock and, for any lease whose TTL has elapsed since its last renewal,
// runs its full reclamation sequence. Leases are processed in
// lexicographically sorted ID order, not Go map iteration order, so the
// resulting event sequence is deterministic across runs - a prior version
// of this method iterated the leases map directly, which does not
// guarantee order and made a multi-lease scenario's expected event
// sequence nondeterministic. It returns the IDs of leases reclaimed by
// this call, in that same sorted order.
func (m *LeaseManager) CheckExpiry() []string {
	var ids []string
	for id, l := range m.leases {
		if l.active && m.now-l.renewedAt >= l.TTL {
			ids = append(ids, id)
		}
	}
	sort.Strings(ids)

	var reclaimed []string
	for _, id := range ids {
		if err := m.reclaim(id, ""); err == nil {
			reclaimed = append(reclaimed, id)
		}
	}
	return reclaimed
}

// CheckExpiryOne evaluates a single lease for expiry and, if expired, runs
// its reclamation sequence with the given injected fault timing - the
// single-lease entry point TestScenarioLeaseExpiry uses to exercise AC #2's
// before/after injection points for this scenario.
func (m *LeaseManager) CheckExpiryOne(leaseID string, timing FaultTiming) error {
	l, ok := m.leases[leaseID]
	if !ok || !l.active || m.now-l.renewedAt < l.TTL {
		return nil
	}
	return m.reclaim(leaseID, timing)
}

// Active reports whether leaseID is still tracked as active.
func (m *LeaseManager) Active(leaseID string) bool {
	l, ok := m.leases[leaseID]
	return ok && l.active
}
