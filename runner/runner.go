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

// Validate checks the fields common to every adapter.
func (i Invocation) Validate() error {
	if i.Adapter == "" {
		return errors.New("runner invocation has no adapter")
	}
	if i.Recipe == "" {
		return errors.New("runner invocation has no recipe")
	}
	return nil
}

// WithDir returns a copy that executes relative to dir.
func (i Invocation) WithDir(dir string) Invocation {
	i.Dir = dir
	return i
}

// WithEnv returns a copy with the supplied environment override.
func (i Invocation) WithEnv(key, value string) Invocation {
	if i.Env == nil {
		i.Env = make(map[string]string)
	} else {
		env := make(map[string]string, len(i.Env)+1)
		for existingKey, existingValue := range i.Env {
			env[existingKey] = existingValue
		}
		i.Env = env
	}
	i.Env[key] = value
	return i
}

// Adapter resolves a structured invocation into a process for any target.
//
// Implementations should be deterministic and side-effect free. Resolution
// does not execute the process.
type Adapter interface {
	Name() string
	Resolve(context.Context, Invocation) (process.Spec, error)
}

// Registry stores runner adapters by stable name.
type Registry struct {
	mu       sync.RWMutex
	adapters map[string]Adapter
}

// NewRegistry constructs an empty adapter registry.
func NewRegistry() *Registry {
	return &Registry{adapters: make(map[string]Adapter)}
}

// Register adds an adapter. Replacing an adapter accidentally is an error.
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

// Resolve finds the requested adapter and resolves the invocation.
func (r *Registry) Resolve(ctx context.Context, invocation Invocation) (process.Spec, error) {
	if err := invocation.Validate(); err != nil {
		return process.Spec{}, err
	}

	r.mu.RLock()
	adapter, ok := r.adapters[invocation.Adapter]
	r.mu.RUnlock()
	if !ok {
		return process.Spec{}, fmt.Errorf("runner adapter %q is not registered", invocation.Adapter)
	}

	spec, err := adapter.Resolve(ctx, invocation)
	if err != nil {
		return process.Spec{}, fmt.Errorf("resolve %s invocation: %w", invocation.Adapter, err)
	}
	return spec, nil
}

// Names returns registered adapter names in stable order.
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
