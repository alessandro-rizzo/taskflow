// Package state defines the revisioned transition journal used for recovery.
package state

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"
)

const SchemaVersion = 1

var (
	ErrNotFound = errors.New("run state not found")
	ErrLocked   = errors.New("run is locked by another controller")
	ErrConflict = errors.New("state revision conflict")
)

type Status string

const (
	Pending   Status = "pending"
	Running   Status = "running"
	Succeeded Status = "succeeded"
	Failed    Status = "failed"
	Blocked   Status = "blocked"
	Cancelled Status = "cancelled"
)

// Step records the durable result required for safe resume.
type Step struct {
	ID              string    `json:"id"`
	Status          Status    `json:"status"`
	Attempts        int       `json:"attempts"`
	Target          string    `json:"target,omitempty"`
	EnvironmentID   string    `json:"environment_id,omitempty"`
	ExecutionDigest string    `json:"execution_digest,omitempty"`
	CacheHit        bool      `json:"cache_hit,omitempty"`
	CacheKey        string    `json:"cache_key,omitempty"`
	OutputManifest  string    `json:"output_manifest,omitempty"`
	CleanupError    string    `json:"cleanup_error,omitempty"`
	StartedAt       time.Time `json:"started_at,omitempty"`
	FinishedAt      time.Time `json:"finished_at,omitempty"`
	Error           string    `json:"error,omitempty"`
}

type Run struct {
	ID               string          `json:"id"`
	Pipeline         string          `json:"pipeline"`
	StructuralDigest string          `json:"structural_digest"`
	DefinitionDigest string          `json:"definition_digest"`
	Status           Status          `json:"status"`
	CreatedAt        time.Time       `json:"created_at"`
	UpdatedAt        time.Time       `json:"updated_at"`
	Steps            map[string]Step `json:"steps"`
}

type TransitionKind string

const (
	RunCreated  TransitionKind = "run.created"
	RunChanged  TransitionKind = "run.changed"
	StepChanged TransitionKind = "step.changed"
)

// Transition is one O(1) journal record. Revision and Schema are assigned by
// the journal implementation.
type Transition struct {
	Schema   int            `json:"schema"`
	Revision uint64         `json:"revision"`
	Kind     TransitionKind `json:"kind"`
	Time     time.Time      `json:"time"`
	Run      *Run           `json:"run,omitempty"`
	Status   Status         `json:"status,omitempty"`
	Step     *Step          `json:"step,omitempty"`
}

type Snapshot struct {
	Revision uint64
	Run      Run
}

// Store acquires an exclusive run lease. A shared-store implementation must
// provide equivalent distributed exclusion.
type Store interface {
	Acquire(context.Context, string) (Lease, error)
}

// Lease owns one run while a controller is scheduling it.
type Lease interface {
	Load(context.Context) (Snapshot, error)
	Append(context.Context, uint64, Transition) (Snapshot, error)
	Close() error
}

func Created(run Run, at time.Time) Transition {
	copy := Clone(run)
	return Transition{Kind: RunCreated, Time: at, Run: &copy}
}

func RunStatus(status Status, at time.Time) Transition {
	return Transition{Kind: RunChanged, Time: at, Status: status}
}

func StepStatus(step Step, at time.Time) Transition {
	copy := step
	return Transition{Kind: StepChanged, Time: at, Step: &copy}
}

// Apply validates and applies one transition.
func Apply(snapshot Snapshot, transition Transition) (Snapshot, error) {
	return apply(CloneSnapshot(snapshot), transition)
}

func apply(snapshot Snapshot, transition Transition) (Snapshot, error) {
	if transition.Schema != SchemaVersion {
		return Snapshot{}, fmt.Errorf("unsupported state schema %d", transition.Schema)
	}
	if transition.Revision != snapshot.Revision+1 {
		return Snapshot{}, fmt.Errorf("%w: have %d, transition %d", ErrConflict, snapshot.Revision, transition.Revision)
	}
	switch transition.Kind {
	case RunCreated:
		if snapshot.Revision != 0 || transition.Run == nil {
			return Snapshot{}, errors.New("invalid run creation transition")
		}
		snapshot.Run = Clone(*transition.Run)
	case RunChanged:
		if snapshot.Revision == 0 || transition.Status == "" {
			return Snapshot{}, errors.New("invalid run status transition")
		}
		snapshot.Run.Status = transition.Status
		snapshot.Run.UpdatedAt = transition.Time
	case StepChanged:
		if snapshot.Revision == 0 || transition.Step == nil {
			return Snapshot{}, errors.New("invalid step transition")
		}
		if _, exists := snapshot.Run.Steps[transition.Step.ID]; !exists {
			return Snapshot{}, fmt.Errorf("unknown step %q", transition.Step.ID)
		}
		snapshot.Run.Steps[transition.Step.ID] = *transition.Step
		snapshot.Run.UpdatedAt = transition.Time
	default:
		return Snapshot{}, fmt.Errorf("unknown transition kind %q", transition.Kind)
	}
	snapshot.Revision = transition.Revision
	return snapshot, nil
}

func Replay(transitions []Transition) (Snapshot, error) {
	var snapshot Snapshot
	for _, transition := range transitions {
		next, err := apply(snapshot, transition)
		if err != nil {
			return Snapshot{}, err
		}
		snapshot = next
	}
	if snapshot.Revision == 0 {
		return Snapshot{}, ErrNotFound
	}
	return snapshot, nil
}

type MemoryStore struct {
	mu       sync.Mutex
	journals map[string]*memoryJournal
}

type memoryJournal struct {
	token       chan struct{}
	transitions []Transition
}

func NewMemory() *MemoryStore {
	return &MemoryStore{journals: make(map[string]*memoryJournal)}
}

func (s *MemoryStore) Acquire(_ context.Context, id string) (Lease, error) {
	s.mu.Lock()
	journal, ok := s.journals[id]
	if !ok {
		journal = &memoryJournal{token: make(chan struct{}, 1)}
		journal.token <- struct{}{}
		s.journals[id] = journal
	}
	s.mu.Unlock()
	select {
	case <-journal.token:
		return &memoryLease{journal: journal}, nil
	default:
		return nil, ErrLocked
	}
}

type memoryLease struct {
	journal *memoryJournal
	closed  bool
}

func (l *memoryLease) Load(context.Context) (Snapshot, error) {
	return Replay(append([]Transition(nil), l.journal.transitions...))
}

func (l *memoryLease) Append(_ context.Context, expected uint64, transition Transition) (Snapshot, error) {
	if l.closed {
		return Snapshot{}, errors.New("state lease is closed")
	}
	if uint64(len(l.journal.transitions)) != expected {
		return Snapshot{}, ErrConflict
	}
	transition.Schema = SchemaVersion
	transition.Revision = expected + 1
	current, err := Replay(l.journal.transitions)
	if errors.Is(err, ErrNotFound) {
		current = Snapshot{}
	} else if err != nil {
		return Snapshot{}, err
	}
	next, err := Apply(current, transition)
	if err != nil {
		return Snapshot{}, err
	}
	l.journal.transitions = append(l.journal.transitions, transition)
	return CloneSnapshot(next), nil
}

func (l *memoryLease) Close() error {
	if l.closed {
		return nil
	}
	l.closed = true
	l.journal.token <- struct{}{}
	return nil
}

func Clone(run Run) Run {
	steps := make(map[string]Step, len(run.Steps))
	for id, step := range run.Steps {
		steps[id] = step
	}
	run.Steps = steps
	return run
}

func CloneSnapshot(snapshot Snapshot) Snapshot {
	snapshot.Run = Clone(snapshot.Run)
	return snapshot
}
