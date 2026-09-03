package lifecyclefaults

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"sort"
	"strings"
)

// LeaseStateFormatVersion versions only this fixture's lease-manager state
// envelope. It is independent of ScenarioVersion and carries no compatibility
// promise before Gate 1.
const LeaseStateFormatVersion = "t1-lifecycle-lease-state-v1-experimental"

var (
	// ErrInvalidLeaseState identifies malformed or internally inconsistent
	// lease-state bytes. Callers receive no partially constructed manager.
	ErrInvalidLeaseState = errors.New("lifecyclefaults: invalid lease state")
	// ErrIncompatibleLeaseState identifies a well-formed envelope using a
	// format version this fixture does not understand.
	ErrIncompatibleLeaseState = errors.New("lifecyclefaults: incompatible lease state")
)

// Pointer fields distinguish a required zero/false value from a missing or
// null field while decoding. The type remains private because this is a byte
// fixture contract, not a Go API contract.
type leaseStateEnvelope struct {
	FormatVersion *string             `json:"format_version"`
	LogicalNow    *int                `json:"logical_now"`
	Leases        *[]leaseStateRecord `json:"leases"`
}

type leaseStateRecord struct {
	ID               *string `json:"id"`
	NamespaceID      *string `json:"namespace_id"`
	ResourceID       *string `json:"resource_id"`
	TTLTicks         *int    `json:"ttl_ticks"`
	AcquiredAtTick   *int    `json:"acquired_at_tick"`
	RenewedAtTick    *int    `json:"renewed_at_tick"`
	Active           *bool   `json:"active"`
	ReclamationStage *int    `json:"reclamation_stage"`
}

// LeaseStateSnapshot serializes the logical clock and every tracked lease in
// stable lease-ID order. Journal bytes are intentionally separate: tests must
// reload both durability boundaries rather than accidentally treating event
// persistence as lease-state persistence.
func (m *LeaseManager) LeaseStateSnapshot() ([]byte, error) {
	version := LeaseStateFormatVersion
	now := m.now
	records := make([]leaseStateRecord, 0, len(m.leases))
	ids := make([]string, 0, len(m.leases))
	for id := range m.leases {
		ids = append(ids, id)
	}
	sort.Strings(ids)

	for _, id := range ids {
		lease := m.leases[id]
		leaseID := lease.ID
		namespaceID := lease.NamespaceID
		resourceID := lease.ResourceID
		ttl := lease.TTL
		acquiredAt := lease.acquiredAt
		renewedAt := lease.renewedAt
		active := lease.active
		reclaimStage := lease.reclaimStage
		records = append(records, leaseStateRecord{
			ID:               &leaseID,
			NamespaceID:      &namespaceID,
			ResourceID:       &resourceID,
			TTLTicks:         &ttl,
			AcquiredAtTick:   &acquiredAt,
			RenewedAtTick:    &renewedAt,
			Active:           &active,
			ReclamationStage: &reclaimStage,
		})
	}

	return json.Marshal(leaseStateEnvelope{
		FormatVersion: &version,
		LogicalNow:    &now,
		Leases:        &records,
	})
}

// LoadLeaseManager reconstructs a manager exclusively from lease-state bytes
// and a separately reconstructed journal. It validates both the envelope's
// internal invariants and that each saved reclamation stage describes exactly
// the ordered prefix already committed to the journal.
func LoadLeaseManager(data []byte, journal *Journal) (*LeaseManager, error) {
	if journal == nil {
		return nil, invalidLeaseState("journal is required")
	}

	var envelope leaseStateEnvelope
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&envelope); err != nil {
		return nil, invalidLeaseState("decode: %v", err)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		if err == nil {
			return nil, invalidLeaseState("multiple JSON values")
		}
		return nil, invalidLeaseState("trailing data: %v", err)
	}

	if envelope.FormatVersion == nil || strings.TrimSpace(*envelope.FormatVersion) == "" {
		return nil, invalidLeaseState("format_version is required")
	}
	if *envelope.FormatVersion != LeaseStateFormatVersion {
		return nil, fmt.Errorf("%w: want %q, got %q", ErrIncompatibleLeaseState, LeaseStateFormatVersion, *envelope.FormatVersion)
	}
	if envelope.LogicalNow == nil {
		return nil, invalidLeaseState("logical_now is required")
	}
	if *envelope.LogicalNow < 0 {
		return nil, invalidLeaseState("logical_now must be non-negative")
	}
	if envelope.Leases == nil {
		return nil, invalidLeaseState("leases is required")
	}

	manager := &LeaseManager{
		journal: journal,
		now:     *envelope.LogicalNow,
		leases:  make(map[string]*Lease, len(*envelope.Leases)),
	}
	for index, record := range *envelope.Leases {
		lease, err := loadLeaseStateRecord(index, record, manager.now)
		if err != nil {
			return nil, err
		}
		if _, exists := manager.leases[lease.ID]; exists {
			return nil, invalidLeaseState("leases[%d].id %q is duplicated", index, lease.ID)
		}
		manager.leases[lease.ID] = lease
	}

	for _, lease := range manager.leases {
		if err := validateLeaseJournalState(journal, lease); err != nil {
			return nil, err
		}
	}
	for _, event := range journal.Events() {
		if isLeaseJournalCheckpoint(event.Checkpoint) {
			if _, exists := manager.leases[event.RunID]; !exists {
				return nil, invalidLeaseState("journal has lease event %q for absent lease %q", event.Checkpoint, event.RunID)
			}
		}
	}

	return manager, nil
}

func loadLeaseStateRecord(index int, record leaseStateRecord, logicalNow int) (*Lease, error) {
	path := fmt.Sprintf("leases[%d]", index)
	if record.ID == nil || strings.TrimSpace(*record.ID) == "" {
		return nil, invalidLeaseState("%s.id is required", path)
	}
	if record.NamespaceID == nil || strings.TrimSpace(*record.NamespaceID) == "" {
		return nil, invalidLeaseState("%s.namespace_id is required", path)
	}
	if record.ResourceID == nil || strings.TrimSpace(*record.ResourceID) == "" {
		return nil, invalidLeaseState("%s.resource_id is required", path)
	}
	if record.TTLTicks == nil || *record.TTLTicks <= 0 {
		return nil, invalidLeaseState("%s.ttl_ticks must be positive", path)
	}
	if record.AcquiredAtTick == nil {
		return nil, invalidLeaseState("%s.acquired_at_tick is required", path)
	}
	if record.RenewedAtTick == nil {
		return nil, invalidLeaseState("%s.renewed_at_tick is required", path)
	}
	if *record.AcquiredAtTick < 0 || *record.AcquiredAtTick > *record.RenewedAtTick || *record.RenewedAtTick > logicalNow {
		return nil, invalidLeaseState("%s ticks must satisfy 0 <= acquired_at_tick <= renewed_at_tick <= logical_now", path)
	}
	if record.Active == nil {
		return nil, invalidLeaseState("%s.active is required", path)
	}
	if record.ReclamationStage == nil || *record.ReclamationStage < 0 || *record.ReclamationStage > len(reclaimStages) {
		return nil, invalidLeaseState("%s.reclamation_stage must be between 0 and %d", path, len(reclaimStages))
	}
	if *record.ReclamationStage > 0 && logicalNow-*record.RenewedAtTick < *record.TTLTicks {
		return nil, invalidLeaseState("%s cannot be reclaiming before its TTL expires", path)
	}
	if !*record.Active && *record.ReclamationStage > 0 && *record.ReclamationStage < len(reclaimStages) {
		return nil, invalidLeaseState("%s cannot be inactive during partial reclamation", path)
	}

	return &Lease{
		ID:           *record.ID,
		NamespaceID:  *record.NamespaceID,
		ResourceID:   *record.ResourceID,
		TTL:          *record.TTLTicks,
		acquiredAt:   *record.AcquiredAtTick,
		renewedAt:    *record.RenewedAtTick,
		active:       *record.Active,
		reclaimStage: *record.ReclamationStage,
	}, nil
}

func validateLeaseJournalState(journal *Journal, lease *Lease) error {
	acquisitions := 0
	releases := 0
	prefixLength := 0
	for _, event := range journal.EventsForRun(lease.ID) {
		switch event.Checkpoint {
		case "lease.acquired":
			acquisitions++
			if acquisitions != 1 {
				return invalidLeaseState("lease %q must have exactly one acquisition event", lease.ID)
			}
			if prefixLength != 0 || releases != 0 {
				return invalidLeaseState("lease %q acquisition event is out of order", lease.ID)
			}
			if event.Outcome != "ok" || event.NamespaceID != lease.NamespaceID || event.ResourceID != lease.ResourceID {
				return invalidLeaseState("lease %q acquisition event disagrees with lease state", lease.ID)
			}
			continue
		case "lease.renewed":
			if acquisitions != 1 || releases != 0 || prefixLength != 0 {
				return invalidLeaseState("lease %q renewal event is out of order", lease.ID)
			}
			if event.Outcome != "ok" || event.NamespaceID != lease.NamespaceID || event.ResourceID != lease.ResourceID {
				return invalidLeaseState("lease %q renewal event disagrees with lease state", lease.ID)
			}
			continue
		case "lease.released":
			releases++
			if acquisitions != 1 || releases != 1 || prefixLength != 0 {
				return invalidLeaseState("lease %q release event is duplicated, out of order, or contradicts reclamation", lease.ID)
			}
			if event.Outcome != "released" || event.NamespaceID != lease.NamespaceID || event.ResourceID != lease.ResourceID {
				return invalidLeaseState("lease %q release event disagrees with lease state", lease.ID)
			}
			continue
		}

		stageIndex := reclamationStageIndex(event.Checkpoint)
		if stageIndex < 0 {
			continue
		}
		if acquisitions != 1 || releases != 0 {
			return invalidLeaseState("lease %q reclamation event precedes acquisition or follows release", lease.ID)
		}
		if stageIndex != prefixLength {
			return invalidLeaseState("lease %q journal reclamation events are not an ordered unique prefix", lease.ID)
		}
		wantOutcome := "expired"
		if event.Checkpoint == "orphan.reclaimed" {
			wantOutcome = "reclaimed"
		}
		if event.Outcome != wantOutcome || event.NamespaceID != lease.NamespaceID || event.ResourceID != lease.ResourceID {
			return invalidLeaseState("lease %q journal reclamation event %q disagrees with lease state", lease.ID, event.Checkpoint)
		}
		prefixLength++
	}
	if acquisitions != 1 {
		return invalidLeaseState("lease %q must have exactly one acquisition event", lease.ID)
	}
	if prefixLength != lease.reclaimStage {
		return invalidLeaseState("lease %q saved reclamation_stage is %d but journal prefix length is %d", lease.ID, lease.reclaimStage, prefixLength)
	}
	if releases == 1 {
		if lease.active || lease.reclaimStage != 0 {
			return invalidLeaseState("lease %q release event contradicts active or reclaimed state", lease.ID)
		}
	} else if !lease.active && lease.reclaimStage == 0 {
		return invalidLeaseState("lease %q is inactive without release or completed reclamation", lease.ID)
	}
	return nil
}

func isLeaseJournalCheckpoint(checkpoint Checkpoint) bool {
	switch checkpoint {
	case "lease.acquired", "lease.renewed", "lease.released":
		return true
	default:
		return reclamationStageIndex(checkpoint) >= 0
	}
}

func reclamationStageIndex(checkpoint Checkpoint) int {
	for index, stage := range reclaimStages {
		if checkpoint == stage {
			return index
		}
	}
	return -1
}

func invalidLeaseState(format string, args ...any) error {
	return fmt.Errorf("%w: %s", ErrInvalidLeaseState, fmt.Sprintf(format, args...))
}
