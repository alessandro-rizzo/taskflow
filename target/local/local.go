// Package local executes steps as child processes on the controller.
package local

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"

	"github.com/alessandro-rizzo/taskflow/process"
	"github.com/alessandro-rizzo/taskflow/target"
)

// Provider acquires local execution environments rooted at Root.
type Provider struct {
	Root string
}

// New constructs a local provider.
func New(root string) Provider {
	return Provider{Root: root}
}

// Name returns the default target selector.
func (Provider) Name() string {
	return "local"
}

// Capabilities describes the local host.
func (Provider) Capabilities(context.Context) (target.Capabilities, error) {
	return target.Capabilities{
		OS:             runtime.GOOS,
		Architecture:   runtime.GOARCH,
		MaxConcurrency: runtime.NumCPU(),
	}, nil
}

// Acquire returns a lightweight local environment.
func (p Provider) Acquire(_ context.Context, request target.AcquireRequest) (target.Environment, error) {
	root := p.Root
	if request.Workspace != "" {
		if filepath.IsAbs(request.Workspace) {
			root = request.Workspace
		} else {
			root = filepath.Join(root, request.Workspace)
		}
	}
	if root == "" {
		var err error
		root, err = os.Getwd()
		if err != nil {
			return nil, fmt.Errorf("resolve local working directory: %w", err)
		}
	}
	root, err := filepath.Abs(root)
	if err != nil {
		return nil, fmt.Errorf("resolve local root: %w", err)
	}
	return &environment{id: "local:" + request.StepID, root: root}, nil
}

type environment struct {
	id   string
	root string
}

func (e *environment) ID() string {
	return e.id
}

func (e *environment) Exec(ctx context.Context, spec process.Spec, streams process.IO) (process.Result, error) {
	if spec.Program == "" {
		return process.Result{}, errors.New("process program is empty")
	}

	dir, err := resolveDir(e.root, spec.Dir)
	if err != nil {
		return process.Result{}, err
	}

	command := exec.CommandContext(ctx, spec.Program, spec.Args...)
	command.Dir = dir
	command.Env = mergeEnv(os.Environ(), spec.Env)
	command.Stdin = streams.Stdin
	command.Stdout = writerOrDiscard(streams.Stdout)
	command.Stderr = writerOrDiscard(streams.Stderr)

	result := process.Result{StartedAt: time.Now()}
	err = command.Run()
	result.FinishedAt = time.Now()
	if err == nil {
		return result, nil
	}

	var exitError *exec.ExitError
	if errors.As(err, &exitError) {
		result.ExitCode = exitError.ExitCode()
	}
	return result, fmt.Errorf("execute %s: %w", spec.Program, err)
}

func (e *environment) Release(context.Context, target.Release) error {
	return nil
}

func resolveDir(root, relative string) (string, error) {
	if relative == "" {
		return root, nil
	}
	if filepath.IsAbs(relative) {
		return "", errors.New("process directory must be relative to the target workspace")
	}
	resolved := filepath.Clean(filepath.Join(root, relative))
	prefix := root + string(filepath.Separator)
	if resolved != root && !strings.HasPrefix(resolved, prefix) {
		return "", errors.New("process directory escapes the target workspace")
	}
	return resolved, nil
}

func mergeEnv(base []string, overrides map[string]string) []string {
	values := make(map[string]string, len(base)+len(overrides))
	for _, entry := range base {
		key, value, ok := strings.Cut(entry, "=")
		if ok {
			values[key] = value
		}
	}
	for key, value := range overrides {
		values[key] = value
	}
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	env := make([]string, 0, len(keys))
	for _, key := range keys {
		env = append(env, key+"="+values[key])
	}
	return env
}

func writerOrDiscard(writer io.Writer) io.Writer {
	if writer == nil {
		return io.Discard
	}
	return writer
}
