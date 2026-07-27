// Package target defines replaceable execution targets.
package target

import (
	"context"
	"errors"
	"fmt"
	"io"
	"sort"
	"sync"

	"github.com/alessandro-rizzo/taskflow/process"
)

type Capabilities struct {
	OS             string
	Architecture   string
	MaxConcurrency int
	Resources      map[string]int64
	Labels         map[string]string
}

type AcquireRequest struct {
	RunID          string
	StepID         string
	ExecutionGroup string
	Resources      map[string]int64
}

type Release struct {
	Success bool
}

type Probe struct {
	Name    string
	Program string
	Args    []string
}

type IdentityRequest struct {
	Dir         string
	Environment []string
	Overrides   map[string]string
	Toolchains  []Probe
}

// Identity contains the target facts used in a cache key.
type Identity struct {
	OS           string            `json:"os"`
	Architecture string            `json:"architecture"`
	Image        string            `json:"image,omitempty"`
	Environment  map[string]string `json:"environment,omitempty"`
	Toolchains   map[string]string `json:"toolchains,omitempty"`
}

type Environment interface {
	ID() string
	Identity(context.Context, IdentityRequest) (Identity, error)
	Exec(context.Context, process.Spec, process.IO) (process.Result, error)
	// Upload extracts a deterministic tar stream at the workspace root.
	Upload(context.Context, io.Reader) error
	// Download writes a deterministic tar stream containing matched paths.
	Download(context.Context, []string, io.Writer) error
	Release(context.Context, Release) error
}

// Reservation holds provider capacity without provisioning infrastructure.
// Acquire may perform slow network work after the scheduler has admitted it.
type Reservation interface {
	Acquire(context.Context) (Environment, error)
	Release()
}

type Provider interface {
	Name() string
	Capabilities(context.Context) (Capabilities, error)
	TryReserve(context.Context, AcquireRequest) (Reservation, bool, error)
}

type Registry struct {
	mu        sync.RWMutex
	providers map[string]Provider
}

func NewRegistry() *Registry {
	return &Registry{providers: make(map[string]Provider)}
}

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

func (r *Registry) Provider(name string) (Provider, error) {
	r.mu.RLock()
	provider, ok := r.providers[name]
	r.mu.RUnlock()
	if !ok {
		return nil, fmt.Errorf("target provider %q is not registered", name)
	}
	return provider, nil
}

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
