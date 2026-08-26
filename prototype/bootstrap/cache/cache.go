// Package cache defines Taskflow's content-addressed cache and coordinator.
package cache

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"sort"

	"github.com/arr/taskflow/flow"
	"github.com/arr/taskflow/runner"
	"github.com/arr/taskflow/target"
	"github.com/arr/taskflow/workspace"
)

type Key string

func NewKey(parts ...[]byte) Key {
	hash := sha256.New()
	for _, part := range parts {
		writeFragment(hash, part)
	}
	return Key(hex.EncodeToString(hash.Sum(nil)))
}

type Entry struct {
	Key      Key    `json:"key"`
	Manifest string `json:"manifest"`
	Size     int64  `json:"size"`
}

type Store interface {
	// Open must return found=false for incomplete, corrupt, or unverifiable
	// entries. Cache corruption is a miss, not an execution failure.
	Open(context.Context, Key) (Entry, io.ReadCloser, bool, error)
	Put(context.Context, Key, io.Reader) (Entry, error)
	Exists(context.Context, Key, string) (bool, error)
}

type Coordinator struct {
	Store         Store
	WorkspaceRoot string
}

type Identity struct {
	Key             Key
	ExecutionDigest string
	InputDigest     string
}

func RunArtifactKey(runID, pipeline string, stepID flow.StepID, executionDigest string) Key {
	return NewKey(
		[]byte("taskflow-run-artifact-v1"),
		[]byte(runID),
		[]byte(pipeline),
		[]byte(stepID),
		[]byte(executionDigest),
	)
}

type dependencyManifest struct {
	ID       string `json:"id"`
	Manifest string `json:"manifest"`
}

// ComputeIdentity uses the command after adapter resolution and the identity
// observed inside the acquired target.
func (c Coordinator) ComputeIdentity(
	ctx context.Context,
	pipeline string,
	step flow.Step,
	resolved runner.Resolved,
	environment target.Identity,
	dependencyManifests map[string]string,
) (Identity, error) {
	if c.Store == nil {
		return Identity{}, errors.New("cache store is nil")
	}
	inputDigest, err := workspace.Digest(ctx, c.WorkspaceRoot, step.Inputs)
	if err != nil {
		return Identity{}, err
	}
	dependencies := make([]dependencyManifest, 0, len(dependencyManifests))
	for id, manifest := range dependencyManifests {
		dependencies = append(dependencies, dependencyManifest{ID: id, Manifest: manifest})
	}
	sort.Slice(dependencies, func(i, j int) bool { return dependencies[i].ID < dependencies[j].ID })
	inputs := append([]string(nil), step.Inputs...)
	outputs := append([]string(nil), step.Outputs...)
	sort.Strings(inputs)
	sort.Strings(outputs)

	executionValue := struct {
		Resolved    runner.Resolved `json:"resolved"`
		Environment target.Identity `json:"environment"`
	}{
		Resolved: resolved, Environment: environment,
	}
	executionJSON, err := json.Marshal(executionValue)
	if err != nil {
		return Identity{}, fmt.Errorf("encode execution identity: %w", err)
	}
	executionSum := sha256.Sum256(executionJSON)
	executionDigest := hex.EncodeToString(executionSum[:])

	keyValue := struct {
		Schema          int                  `json:"schema"`
		Pipeline        string               `json:"pipeline"`
		StepID          string               `json:"step_id"`
		CacheVersion    string               `json:"cache_version"`
		ExecutionDigest string               `json:"execution_digest"`
		InputDigest     string               `json:"input_digest"`
		Inputs          []string             `json:"inputs"`
		Outputs         []string             `json:"outputs"`
		Dependencies    []dependencyManifest `json:"dependencies"`
	}{
		Schema: 1, Pipeline: pipeline, StepID: string(step.ID), CacheVersion: step.Cache.Version,
		ExecutionDigest: executionDigest, InputDigest: inputDigest,
		Inputs: inputs, Outputs: outputs, Dependencies: dependencies,
	}
	encoded, err := json.Marshal(keyValue)
	if err != nil {
		return Identity{}, fmt.Errorf("encode cache key: %w", err)
	}
	return Identity{
		Key: NewKey(encoded), ExecutionDigest: executionDigest, InputDigest: inputDigest,
	}, nil
}

func (c Coordinator) Restore(ctx context.Context, key Key, environment target.Environment) (Entry, bool, error) {
	entry, reader, found, err := c.Store.Open(ctx, key)
	if err != nil || !found {
		return Entry{}, found, err
	}
	defer reader.Close()
	if err := environment.Upload(ctx, reader); err != nil {
		return Entry{}, false, fmt.Errorf("restore cached outputs: %w", err)
	}
	return entry, true, nil
}

func (c Coordinator) RestoreExpected(
	ctx context.Context,
	key Key,
	manifest string,
	environment target.Environment,
) error {
	entry, hit, err := c.Restore(ctx, key, environment)
	if err != nil {
		return err
	}
	if !hit {
		return fmt.Errorf("required artifact %s is not present", key)
	}
	if entry.Manifest != manifest {
		return fmt.Errorf(
			"required artifact %s manifest is %s, want %s",
			key,
			entry.Manifest,
			manifest,
		)
	}
	return nil
}

func (c Coordinator) Publish(
	ctx context.Context,
	key Key,
	environment target.Environment,
	outputs []string,
) (Entry, error) {
	reader, writer := io.Pipe()
	defer reader.Close()
	downloaded := make(chan error, 1)
	go func() {
		err := environment.Download(ctx, outputs, writer)
		_ = writer.CloseWithError(err)
		downloaded <- err
	}()
	entry, storeErr := c.Store.Put(ctx, key, reader)
	_ = reader.Close()
	downloadErr := <-downloaded
	if err := errors.Join(storeErr, downloadErr); err != nil {
		return Entry{}, fmt.Errorf("publish cached outputs: %w", err)
	}
	return entry, nil
}

func (c Coordinator) Valid(ctx context.Context, key, manifest string) (bool, error) {
	if c.Store == nil || key == "" || manifest == "" {
		return false, nil
	}
	return c.Store.Exists(ctx, Key(key), manifest)
}

func writeFragment(writer io.Writer, value []byte) {
	var length [8]byte
	size := uint64(len(value))
	for index := 7; index >= 0; index-- {
		length[index] = byte(size)
		size >>= 8
	}
	_, _ = writer.Write(length[:])
	_, _ = writer.Write(value)
}
