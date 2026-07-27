// Package file implements an atomic filesystem-backed cache store.
package file

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/alessandro-rizzo/taskflow/cache"
)

type Store struct {
	Dir string
}

func New(dir string) Store {
	return Store{Dir: dir}
}

func (s Store) Open(_ context.Context, key cache.Key) (cache.Entry, io.ReadCloser, bool, error) {
	blob, metadata, err := s.paths(key)
	if err != nil {
		return cache.Entry{}, nil, false, err
	}
	encoded, err := os.ReadFile(metadata)
	if errors.Is(err, os.ErrNotExist) {
		return cache.Entry{}, nil, false, nil
	}
	if err != nil {
		return cache.Entry{}, nil, false, fmt.Errorf("read cache metadata: %w", err)
	}
	var entry cache.Entry
	if err := json.Unmarshal(encoded, &entry); err != nil {
		return cache.Entry{}, nil, false, fmt.Errorf("decode cache metadata: %w", err)
	}
	file, err := os.Open(blob)
	if errors.Is(err, os.ErrNotExist) {
		return cache.Entry{}, nil, false, nil
	}
	if err != nil {
		return cache.Entry{}, nil, false, fmt.Errorf("open cache blob: %w", err)
	}
	if entry.Key != key {
		file.Close()
		return cache.Entry{}, nil, false, errors.New("cache metadata key does not match requested key")
	}
	hash := sha256.New()
	size, err := io.Copy(hash, file)
	if err != nil {
		file.Close()
		return cache.Entry{}, nil, false, fmt.Errorf("verify cache blob: %w", err)
	}
	if size != entry.Size || hex.EncodeToString(hash.Sum(nil)) != entry.Manifest {
		file.Close()
		return cache.Entry{}, nil, false, errors.New("cache blob does not match its manifest")
	}
	if _, err := file.Seek(0, io.SeekStart); err != nil {
		file.Close()
		return cache.Entry{}, nil, false, fmt.Errorf("rewind cache blob: %w", err)
	}
	return entry, file, true, nil
}

func (s Store) Put(_ context.Context, key cache.Key, source io.Reader) (cache.Entry, error) {
	blob, metadata, err := s.paths(key)
	if err != nil {
		return cache.Entry{}, err
	}
	dir := filepath.Dir(blob)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return cache.Entry{}, fmt.Errorf("create cache directory: %w", err)
	}
	temporary, err := os.CreateTemp(dir, ".blob-*.tmp")
	if err != nil {
		return cache.Entry{}, fmt.Errorf("create temporary cache blob: %w", err)
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)
	hash := sha256.New()
	size, err := io.Copy(io.MultiWriter(temporary, hash), source)
	if err != nil {
		temporary.Close()
		return cache.Entry{}, fmt.Errorf("write cache blob: %w", err)
	}
	if err := temporary.Sync(); err != nil {
		temporary.Close()
		return cache.Entry{}, fmt.Errorf("sync cache blob: %w", err)
	}
	if err := temporary.Close(); err != nil {
		return cache.Entry{}, fmt.Errorf("close cache blob: %w", err)
	}
	entry := cache.Entry{
		Key: key, Manifest: hex.EncodeToString(hash.Sum(nil)), Size: size,
	}
	metadataJSON, err := json.Marshal(entry)
	if err != nil {
		return cache.Entry{}, err
	}
	metadataTemp, err := os.CreateTemp(dir, ".metadata-*.tmp")
	if err != nil {
		return cache.Entry{}, fmt.Errorf("create temporary cache metadata: %w", err)
	}
	metadataTempPath := metadataTemp.Name()
	defer os.Remove(metadataTempPath)
	if _, err := metadataTemp.Write(metadataJSON); err != nil {
		metadataTemp.Close()
		return cache.Entry{}, fmt.Errorf("write cache metadata: %w", err)
	}
	if err := metadataTemp.Sync(); err != nil {
		metadataTemp.Close()
		return cache.Entry{}, fmt.Errorf("sync cache metadata: %w", err)
	}
	if err := metadataTemp.Close(); err != nil {
		return cache.Entry{}, fmt.Errorf("close cache metadata: %w", err)
	}
	if err := os.Rename(temporaryPath, blob); err != nil {
		return cache.Entry{}, fmt.Errorf("publish cache blob: %w", err)
	}
	if err := os.Rename(metadataTempPath, metadata); err != nil {
		return cache.Entry{}, fmt.Errorf("publish cache metadata: %w", err)
	}
	directory, err := os.Open(dir)
	if err != nil {
		return cache.Entry{}, fmt.Errorf("open cache directory: %w", err)
	}
	if err := directory.Sync(); err != nil {
		directory.Close()
		return cache.Entry{}, fmt.Errorf("sync cache directory: %w", err)
	}
	if err := directory.Close(); err != nil {
		return cache.Entry{}, fmt.Errorf("close cache directory: %w", err)
	}
	return entry, nil
}

func (s Store) Exists(ctx context.Context, key cache.Key, manifest string) (bool, error) {
	entry, reader, found, err := s.Open(ctx, key)
	if reader != nil {
		reader.Close()
	}
	return found && entry.Manifest == manifest, err
}

func (s Store) paths(key cache.Key) (string, string, error) {
	value := string(key)
	if s.Dir == "" {
		return "", "", errors.New("cache directory is empty")
	}
	if len(value) != 64 || strings.Trim(value, "0123456789abcdef") != "" {
		return "", "", fmt.Errorf("invalid cache key %q", value)
	}
	base := filepath.Join(s.Dir, value[:2], value[2:])
	return base + ".tar", base + ".json", nil
}
