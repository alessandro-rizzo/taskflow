// Package state defines the durable run journal used for failure recovery.
package state

import (
	"context"
	"errors"
	"sync"
	"time"
)

// ErrNotFound indicates that a run does not exist.
var ErrNotFound = errors.New("run state not found")

// Status is a run or step lifecycle state.
type Status string

const (
	Pending   Status = "pending"
	Running   Status = "running"
	Succeeded Status = "succeeded"
	Failed    Status = "failed"
	Blocked   Status = "blocked"
)

// Step records the durable state of one DAG node.
type Step struct {
	ID         string    `json:"id"`
	Status     Status    `json:"status"`
	Attempts   int       `json:"attempts"`
	Target     string    `json:"target,omitempty"`
	StartedAt  time.Time `json:"started_at,omitempty"`
	FinishedAt time.Time `json:"finished_at,omitempty"`
	Error      string    `json:"error,omitempty"`
}

// Run is the durable state required to resume a compatible pipeline.
type Run struct {
	ID             string          `json:"id"`
	Pipeline       string          `json:"pipeline"`
	PipelineDigest string          `json:"pipeline_digest"`
	Status         Status          `json:"status"`
	CreatedAt      time.Time       `json:"created_at"`
	UpdatedAt      time.Time       `json:"updated_at"`
	Steps          map[string]Step `json:"steps"`
}

// Store persists complete run snapshots atomically.
type Store interface {
	Load(context.Context, string) (Run, error)
	Save(context.Context, Run) error
}

// MemoryStore is a concurrency-safe store for tests and embedded use.
type MemoryStore struct {
	mu   sync.RWMutex
	runs map[string]Run
}

// NewMemory constructs an empty in-memory store.
func NewMemory() *MemoryStore {
	return &MemoryStore{runs: make(map[string]Run)}
}

// Load returns a defensive copy.
func (s *MemoryStore) Load(_ context.Context, id string) (Run, error) {
	s.mu.RLock()
	run, ok := s.runs[id]
	s.mu.RUnlock()
	if !ok {
		return Run{}, ErrNotFound
	}
	return Clone(run), nil
}

// Save atomically replaces a run snapshot.
func (s *MemoryStore) Save(_ context.Context, run Run) error {
	s.mu.Lock()
	s.runs[run.ID] = Clone(run)
	s.mu.Unlock()
	return nil
}

// Clone returns a defensive copy of a run.
func Clone(run Run) Run {
	steps := make(map[string]Step, len(run.Steps))
	for id, step := range run.Steps {
		steps[id] = step
	}
	run.Steps = steps
	return run
}
