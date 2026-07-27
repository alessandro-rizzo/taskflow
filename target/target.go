// Package target defines replaceable execution targets.
package target

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"sync"

	"github.com/alessandro-rizzo/taskflow/process"
)

// Capabilities let the engine reject unsupported placement before execution.
type Capabilities struct {
	OS             string
	Architecture   string
	MaxConcurrency int
	Labels         map[string]string
}

// AcquireRequest describes one execution environment request.
type AcquireRequest struct {
	RunID     string
	StepID    string
	Workspace string
	Resources map[string]int64
}

// Release describes why an environment is being returned.
type Release struct {
	Success bool
}

// Environment is one acquired local or remote execution context.
type Environment interface {
	ID() string
	Exec(context.Context, process.Spec, process.IO) (process.Result, error)
	Release(context.Context, Release) error
}

// Provider acquires execution environments for one stable target name.
//
// Providers may reuse infrastructure internally. The engine does not assume
// that Acquire creates a new VM or that Release destroys one.
type Provider interface {
	Name() string
	Capabilities(context.Context) (Capabilities, error)
	Acquire(context.Context, AcquireRequest) (Environment, error)
}

// Registry stores target providers by stable name.
type Registry struct {
	mu        sync.RWMutex
	providers map[string]Provider
}

// NewRegistry constructs an empty target registry.
func NewRegistry() *Registry {
	return &Registry{providers: make(map[string]Provider)}
}

// Register adds a provider without allowing accidental replacement.
func (r *Registry) Register(provider Provider) error {
	if provider == nil {
		return errors.New("cannot register a nil target provider")
	}
	name := provider.Name()
	if name == "" {
		return errors.New("cannot register a target provider with an empty name")
	}

	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.providers[name]; exists {
		return fmt.Errorf("target provider %q is already registered", name)
	}
	r.providers[name] = provider
	return nil
}

// Provider returns one registered target.
func (r *Registry) Provider(name string) (Provider, error) {
	r.mu.RLock()
	provider, ok := r.providers[name]
	r.mu.RUnlock()
	if !ok {
		return nil, fmt.Errorf("target provider %q is not registered", name)
	}
	return provider, nil
}

// Names returns registered provider names in stable order.
func (r *Registry) Names() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()

	names := make([]string, 0, len(r.providers))
	for name := range r.providers {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}
