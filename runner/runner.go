// Package runner defines adapters from named task-runner recipes to portable
// process specifications.
package runner

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"sync"

	"github.com/alessandro-rizzo/taskflow/process"
)

// Invocation is the typed, serializable action stored on a flow step.
type Invocation struct {
	Adapter string            `json:"adapter"`
	Recipe  string            `json:"recipe"`
	Args    []string          `json:"args,omitempty"`
	Dir     string            `json:"dir,omitempty"`
	Env     map[string]string `json:"env,omitempty"`
}

func (i Invocation) Validate() error {
	if i.Adapter == "" {
		return errors.New("runner invocation has no adapter")
	}
	if i.Recipe == "" {
		return errors.New("runner invocation has no recipe")
	}
	return nil
}

func (i Invocation) WithDir(dir string) Invocation {
	i.Dir = dir
	return i
}

func (i Invocation) WithEnv(key, value string) Invocation {
	if i.Env == nil {
		i.Env = make(map[string]string)
	} else {
		i.Env = cloneMap(i.Env)
	}
	i.Env[key] = value
	return i
}

// Identity captures adapter configuration that changes the resolved command.
type Identity struct {
	Name          string            `json:"name"`
	Version       string            `json:"version,omitempty"`
	Configuration map[string]string `json:"configuration,omitempty"`
}

// Resolved is the cacheable result of adapter resolution.
type Resolved struct {
	Process  process.Spec `json:"process"`
	Identity Identity     `json:"identity"`
}

// Adapter deterministically resolves an invocation. Identity must include
// adapter configuration such as a non-default binary or compatibility mode.
type Adapter interface {
	Name() string
	Resolve(context.Context, Invocation) (Resolved, error)
}

type Registry struct {
	mu       sync.RWMutex
	adapters map[string]Adapter
}

func NewRegistry() *Registry {
	return &Registry{adapters: make(map[string]Adapter)}
}

func (r *Registry) Register(adapter Adapter) error {
	if adapter == nil {
		return errors.New("cannot register a nil runner adapter")
	}
	name := adapter.Name()
	if name == "" {
		return errors.New("cannot register a runner adapter with an empty name")
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.adapters[name]; exists {
		return fmt.Errorf("runner adapter %q is already registered", name)
	}
	r.adapters[name] = adapter
	return nil
}

func (r *Registry) Resolve(ctx context.Context, invocation Invocation) (Resolved, error) {
	if err := invocation.Validate(); err != nil {
		return Resolved{}, err
	}
	r.mu.RLock()
	adapter, ok := r.adapters[invocation.Adapter]
	r.mu.RUnlock()
	if !ok {
		return Resolved{}, fmt.Errorf("runner adapter %q is not registered", invocation.Adapter)
	}
	resolved, err := adapter.Resolve(ctx, invocation)
	if err != nil {
		return Resolved{}, fmt.Errorf("resolve %s invocation: %w", invocation.Adapter, err)
	}
	if resolved.Process.Program == "" {
		return Resolved{}, fmt.Errorf("runner adapter %q resolved an empty program", invocation.Adapter)
	}
	if resolved.Identity.Name == "" {
		return Resolved{}, fmt.Errorf("runner adapter %q returned an empty identity", invocation.Adapter)
	}
	return resolved, nil
}

func (r *Registry) Names() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	names := make([]string, 0, len(r.adapters))
	for name := range r.adapters {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

func cloneMap(input map[string]string) map[string]string {
	output := make(map[string]string, len(input))
	for key, value := range input {
		output[key] = value
	}
	return output
}
