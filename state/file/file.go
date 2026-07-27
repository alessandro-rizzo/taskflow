// Package file persists one atomic file per Taskflow state transition.
package file

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/alessandro-rizzo/taskflow/state"
)

type Store struct {
	Dir string
}

func New(dir string) Store {
	return Store{Dir: dir}
}

func (s Store) Acquire(_ context.Context, id string) (state.Lease, error) {
	if err := validateID(id); err != nil {
		return nil, err
	}
	if s.Dir == "" {
		return nil, errors.New("state directory is empty")
	}
	if err := os.MkdirAll(s.Dir, 0o700); err != nil {
		return nil, fmt.Errorf("create state directory: %w", err)
	}
	lock, err := acquireFileLock(filepath.Join(s.Dir, id+".lock"))
	if err != nil {
		return nil, err
	}
	lease := &lease{
		lock: lock,
		dir:  filepath.Join(s.Dir, id),
	}
	snapshot, err := loadSnapshot(lease.dir)
	if errors.Is(err, state.ErrNotFound) {
		lease.snapshot = state.Snapshot{}
	} else if err != nil {
		lock.Close()
		return nil, err
	} else {
		lease.snapshot = snapshot
	}
	return lease, nil
}

type lease struct {
	lock     fileLock
	dir      string
	snapshot state.Snapshot
	closed   bool
}

func (l *lease) Load(context.Context) (state.Snapshot, error) {
	if l.closed {
		return state.Snapshot{}, errors.New("state lease is closed")
	}
	if l.snapshot.Revision == 0 {
		return state.Snapshot{}, state.ErrNotFound
	}
	return state.CloneSnapshot(l.snapshot), nil
}

func (l *lease) Append(_ context.Context, expected uint64, transition state.Transition) (state.Snapshot, error) {
	if l.closed {
		return state.Snapshot{}, errors.New("state lease is closed")
	}
	if l.snapshot.Revision != expected {
		return state.Snapshot{}, state.ErrConflict
	}
	transition.Schema = state.SchemaVersion
	transition.Revision = expected + 1
	next, err := state.Apply(l.snapshot, transition)
	if err != nil {
		return state.Snapshot{}, err
	}
	if err := os.MkdirAll(l.dir, 0o700); err != nil {
		return state.Snapshot{}, fmt.Errorf("create run journal: %w", err)
	}
	encoded, err := json.Marshal(transition)
	if err != nil {
		return state.Snapshot{}, fmt.Errorf("encode transition: %w", err)
	}
	temporary, err := os.CreateTemp(l.dir, ".transition-*.tmp")
	if err != nil {
		return state.Snapshot{}, fmt.Errorf("create temporary transition: %w", err)
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)
	if err := temporary.Chmod(0o600); err != nil {
		temporary.Close()
		return state.Snapshot{}, fmt.Errorf("secure transition: %w", err)
	}
	if _, err := temporary.Write(encoded); err != nil {
		temporary.Close()
		return state.Snapshot{}, fmt.Errorf("write transition: %w", err)
	}
	if err := temporary.Sync(); err != nil {
		temporary.Close()
		return state.Snapshot{}, fmt.Errorf("sync transition: %w", err)
	}
	if err := temporary.Close(); err != nil {
		return state.Snapshot{}, fmt.Errorf("close transition: %w", err)
	}
	path := filepath.Join(l.dir, fmt.Sprintf("%020d.json", transition.Revision))
	if err := os.Rename(temporaryPath, path); err != nil {
		return state.Snapshot{}, fmt.Errorf("publish transition: %w", err)
	}
	directory, err := os.Open(l.dir)
	if err != nil {
		return state.Snapshot{}, fmt.Errorf("open journal directory: %w", err)
	}
	if err := directory.Sync(); err != nil {
		directory.Close()
		return state.Snapshot{}, fmt.Errorf("sync journal directory: %w", err)
	}
	if err := directory.Close(); err != nil {
		return state.Snapshot{}, fmt.Errorf("close journal directory: %w", err)
	}
	l.snapshot = next
	return state.CloneSnapshot(next), nil
}

func (l *lease) Close() error {
	if l.closed {
		return nil
	}
	l.closed = true
	return l.lock.Close()
}

func loadSnapshot(dir string) (state.Snapshot, error) {
	entries, err := os.ReadDir(dir)
	if errors.Is(err, os.ErrNotExist) {
		return state.Snapshot{}, state.ErrNotFound
	}
	if err != nil {
		return state.Snapshot{}, fmt.Errorf("read run journal: %w", err)
	}
	files := make([]string, 0, len(entries))
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}
		files = append(files, entry.Name())
	}
	sort.Strings(files)
	transitions := make([]state.Transition, 0, len(files))
	for index, name := range files {
		revisionText := strings.TrimSuffix(name, ".json")
		revision, err := strconv.ParseUint(revisionText, 10, 64)
		if err != nil || revision != uint64(index+1) {
			return state.Snapshot{}, fmt.Errorf("invalid journal sequence at %q", name)
		}
		encoded, err := os.ReadFile(filepath.Join(dir, name))
		if err != nil {
			return state.Snapshot{}, fmt.Errorf("read transition %s: %w", name, err)
		}
		var transition state.Transition
		if err := json.Unmarshal(encoded, &transition); err != nil {
			return state.Snapshot{}, fmt.Errorf("decode transition %s: %w", name, err)
		}
		transitions = append(transitions, transition)
	}
	return state.Replay(transitions)
}

func validateID(id string) error {
	if id == "" || id == "." || id == ".." || strings.HasSuffix(id, ".lock") ||
		strings.ContainsAny(id, `/\`) {
		return fmt.Errorf("invalid run ID %q", id)
	}
	return nil
}
