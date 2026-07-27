// Package file implements an atomic filesystem-backed cache blob store.
package file

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/alessandro-rizzo/taskflow/cache"
)

// Store keeps blobs below Dir, sharded by key prefix.
type Store struct {
	Dir string
}

// New constructs a filesystem cache store.
func New(dir string) Store {
	return Store{Dir: dir}
}

// Get opens a cache blob when present.
func (s Store) Get(_ context.Context, key cache.Key) (io.ReadCloser, bool, error) {
	path, err := s.path(key)
	if err != nil {
		return nil, false, err
	}
	file, err := os.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, fmt.Errorf("open cache blob: %w", err)
	}
	return file, true, nil
}

// Put writes and atomically publishes a cache blob.
func (s Store) Put(_ context.Context, key cache.Key, source io.Reader) error {
	path, err := s.path(key)
	if err != nil {
		return err
	}
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return fmt.Errorf("create cache directory: %w", err)
	}
	temporary, err := os.CreateTemp(dir, ".blob-*.tmp")
	if err != nil {
		return fmt.Errorf("create temporary cache blob: %w", err)
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)

	if _, err := io.Copy(temporary, source); err != nil {
		temporary.Close()
		return fmt.Errorf("write cache blob: %w", err)
	}
	if err := temporary.Sync(); err != nil {
		temporary.Close()
		return fmt.Errorf("sync cache blob: %w", err)
	}
	if err := temporary.Close(); err != nil {
		return fmt.Errorf("close cache blob: %w", err)
	}
	if err := os.Rename(temporaryPath, path); err != nil {
		return fmt.Errorf("publish cache blob: %w", err)
	}
	return nil
}

func (s Store) path(key cache.Key) (string, error) {
	value := string(key)
	if s.Dir == "" {
		return "", errors.New("cache directory is empty")
	}
	if len(value) != 64 || strings.Trim(value, "0123456789abcdef") != "" {
		return "", fmt.Errorf("invalid cache key %q", value)
	}
	return filepath.Join(s.Dir, value[:2], value[2:]), nil
}
