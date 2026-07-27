package file_test

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/alessandro-rizzo/taskflow/state"
	statefile "github.com/alessandro-rizzo/taskflow/state/file"
)

func TestStoreRoundTrip(t *testing.T) {
	t.Parallel()

	store := statefile.New(t.TempDir())
	want := state.Run{
		ID:             "run-1",
		Pipeline:       "verify",
		PipelineDigest: "digest",
		Status:         state.Failed,
		CreatedAt:      time.Unix(10, 0).UTC(),
		UpdatedAt:      time.Unix(20, 0).UTC(),
		Steps: map[string]state.Step{
			"test": {
				ID:       "test",
				Status:   state.Failed,
				Attempts: 1,
				Error:    "failed",
			},
		},
	}

	if err := store.Save(context.Background(), want); err != nil {
		t.Fatalf("Save() error = %v", err)
	}
	got, err := store.Load(context.Background(), want.ID)
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if got.ID != want.ID || got.Status != want.Status || got.Steps["test"].Error != "failed" {
		t.Fatalf("Load() = %#v, want core fields from %#v", got, want)
	}
}

func TestStoreNotFound(t *testing.T) {
	t.Parallel()

	store := statefile.New(t.TempDir())
	_, err := store.Load(context.Background(), "missing")
	if !errors.Is(err, state.ErrNotFound) {
		t.Fatalf("Load() error = %v, want state.ErrNotFound", err)
	}
}
