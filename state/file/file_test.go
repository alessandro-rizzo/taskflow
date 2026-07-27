package file_test

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/alessandro-rizzo/taskflow/state"
	statefile "github.com/alessandro-rizzo/taskflow/state/file"
)

func TestJournalRoundTripAndRevision(t *testing.T) {
	t.Parallel()
	store := statefile.New(t.TempDir())
	lease, err := store.Acquire(context.Background(), "run-1")
	if err != nil {
		t.Fatalf("Acquire() error = %v", err)
	}
	run := state.Run{
		ID: "run-1", Pipeline: "verify", StructuralDigest: "structural",
		DefinitionDigest: "full", Status: state.Running,
		CreatedAt: time.Unix(10, 0).UTC(), UpdatedAt: time.Unix(10, 0).UTC(),
		Steps: map[string]state.Step{
			"test": {ID: "test", Status: state.Pending},
		},
	}
	snapshot, err := lease.Append(
		context.Background(), 0, state.Created(run, run.CreatedAt),
	)
	if err != nil {
		t.Fatalf("Append(create) error = %v", err)
	}
	step := snapshot.Run.Steps["test"]
	step.Status = state.Failed
	step.Error = "failed"
	snapshot, err = lease.Append(
		context.Background(), snapshot.Revision,
		state.StepStatus(step, time.Unix(20, 0).UTC()),
	)
	if err != nil {
		t.Fatalf("Append(step) error = %v", err)
	}
	if snapshot.Revision != 2 {
		t.Fatalf("revision = %d, want 2", snapshot.Revision)
	}
	if err := lease.Close(); err != nil {
		t.Fatalf("Close() error = %v", err)
	}

	reopened, err := store.Acquire(context.Background(), "run-1")
	if err != nil {
		t.Fatalf("reopen Acquire() error = %v", err)
	}
	defer reopened.Close()
	got, err := reopened.Load(context.Background())
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if got.Run.Steps["test"].Error != "failed" || got.Revision != 2 {
		t.Fatalf("Load() = %#v, want failed step at revision 2", got)
	}
}

func TestJournalRejectsConcurrentController(t *testing.T) {
	t.Parallel()
	store := statefile.New(t.TempDir())
	first, err := store.Acquire(context.Background(), "run-1")
	if err != nil {
		t.Fatalf("first Acquire() error = %v", err)
	}
	defer first.Close()
	_, err = store.Acquire(context.Background(), "run-1")
	if !errors.Is(err, state.ErrLocked) {
		t.Fatalf("second Acquire() error = %v, want state.ErrLocked", err)
	}
}

func TestJournalNotFound(t *testing.T) {
	t.Parallel()
	store := statefile.New(t.TempDir())
	lease, err := store.Acquire(context.Background(), "missing")
	if err != nil {
		t.Fatalf("Acquire() error = %v", err)
	}
	defer lease.Close()
	_, err = lease.Load(context.Background())
	if !errors.Is(err, state.ErrNotFound) {
		t.Fatalf("Load() error = %v, want state.ErrNotFound", err)
	}
}
