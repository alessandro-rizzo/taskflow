// Package file persists Taskflow run journals as atomic JSON snapshots.
package file

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/alessandro-rizzo/taskflow/state"
)

// Store persists one JSON file per run.
type Store struct {
	Dir string
}

// New constructs a filesystem state store.
func New(dir string) Store {
	return Store{Dir: dir}
}

// Load reads one run snapshot.
func (s Store) Load(_ context.Context, id string) (state.Run, error) {
	path, err := s.path(id)
	if err != nil {
		return state.Run{}, err
	}
	encoded, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return state.Run{}, state.ErrNotFound
	}
	if err != nil {
		return state.Run{}, fmt.Errorf("read run state: %w", err)
	}
	var run state.Run
	if err := json.Unmarshal(encoded, &run); err != nil {
		return state.Run{}, fmt.Errorf("decode run state: %w", err)
	}
	return run, nil
}

// Save writes and renames a complete snapshot.
func (s Store) Save(_ context.Context, run state.Run) error {
	path, err := s.path(run.ID)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(s.Dir, 0o700); err != nil {
		return fmt.Errorf("create state directory: %w", err)
	}
	encoded, err := json.MarshalIndent(run, "", "  ")
	if err != nil {
		return fmt.Errorf("encode run state: %w", err)
	}
	temporary, err := os.CreateTemp(s.Dir, ".run-*.tmp")
	if err != nil {
		return fmt.Errorf("create temporary run state: %w", err)
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)

	if err := temporary.Chmod(0o600); err != nil {
		temporary.Close()
		return fmt.Errorf("secure temporary run state: %w", err)
	}
	if _, err := temporary.Write(encoded); err != nil {
		temporary.Close()
		return fmt.Errorf("write temporary run state: %w", err)
	}
	if err := temporary.Sync(); err != nil {
		temporary.Close()
		return fmt.Errorf("sync temporary run state: %w", err)
	}
	if err := temporary.Close(); err != nil {
		return fmt.Errorf("close temporary run state: %w", err)
	}
	if err := os.Rename(temporaryPath, path); err != nil {
		return fmt.Errorf("replace run state: %w", err)
	}
	return nil
}

func (s Store) path(id string) (string, error) {
	if s.Dir == "" {
		return "", errors.New("state directory is empty")
	}
	if id == "" || id == "." || id == ".." || strings.ContainsAny(id, `/\`) {
		return "", fmt.Errorf("invalid run ID %q", id)
	}
	return filepath.Join(s.Dir, id+".json"), nil
}
