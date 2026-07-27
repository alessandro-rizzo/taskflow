// Package flow provides the typed, code-first Taskflow DAG.
package flow

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"

	"github.com/alessandro-rizzo/taskflow/runner"
)

// StepID is a stable node identity inside a pipeline.
type StepID string

// Ref is a typed reference to a previously declared step.
type Ref struct {
	id StepID
}

// ID returns the referenced step identity.
func (r Ref) ID() StepID {
	return r.id
}

// CacheMode controls cache reads and writes for a step.
type CacheMode string

const (
	// CacheOff disables caching.
	CacheOff CacheMode = "off"
	// CacheReadOnly permits restoration but not publication.
	CacheReadOnly CacheMode = "read-only"
	// CacheReadWrite permits restoration and publication.
	CacheReadWrite CacheMode = "read-write"
)

// CachePolicy describes a step's cache behavior.
type CachePolicy struct {
	Mode    CacheMode `json:"mode"`
	Version string    `json:"version,omitempty"`
}

// Step is an immutable node returned by Pipeline.
type Step struct {
	ID          StepID            `json:"id"`
	Description string            `json:"description,omitempty"`
	Run         runner.Invocation `json:"run"`
	Needs       []StepID          `json:"needs,omitempty"`
	Target      string            `json:"target"`
	Inputs      []string          `json:"inputs,omitempty"`
	Outputs     []string          `json:"outputs,omitempty"`
	Cache       CachePolicy       `json:"cache"`
	MaxRetries  int               `json:"max_retries,omitempty"`
	Resources   map[string]int64  `json:"resources,omitempty"`
}

// Pipeline is a validated DAG in declaration order.
type Pipeline struct {
	name  string
	steps []Step
	index map[StepID]int
}

// Name returns the pipeline name.
func (p *Pipeline) Name() string {
	return p.name
}

// Steps returns a defensive copy in declaration order.
func (p *Pipeline) Steps() []Step {
	steps := make([]Step, len(p.steps))
	for index, step := range p.steps {
		steps[index] = cloneStep(step)
	}
	return steps
}

// Step returns a defensive copy of one node.
func (p *Pipeline) Step(id StepID) (Step, bool) {
	index, ok := p.index[id]
	if !ok {
		return Step{}, false
	}
	return cloneStep(p.steps[index]), true
}

// Digest fingerprints the graph definition, including structured invocations.
func (p *Pipeline) Digest() (string, error) {
	value := struct {
		Name  string `json:"name"`
		Steps []Step `json:"steps"`
	}{
		Name:  p.name,
		Steps: p.Steps(),
	}
	encoded, err := json.Marshal(value)
	if err != nil {
		return "", fmt.Errorf("marshal pipeline definition: %w", err)
	}
	sum := sha256.Sum256(encoded)
	return hex.EncodeToString(sum[:]), nil
}

// Builder collects typed steps and deferred validation errors.
type Builder struct {
	pipeline *Pipeline
	errs     []error
}

// Define constructs and validates a pipeline.
func Define(name string, define func(*Builder)) (*Pipeline, error) {
	pipeline := &Pipeline{
		name:  strings.TrimSpace(name),
		index: make(map[StepID]int),
	}
	builder := &Builder{pipeline: pipeline}
	if define == nil {
		builder.errs = append(builder.errs, errors.New("pipeline definition function is nil"))
	} else {
		define(builder)
	}

	if err := builder.validate(); err != nil {
		return nil, err
	}
	return pipeline, nil
}

// MustDefine is Define for static pipeline declarations.
func MustDefine(name string, define func(*Builder)) *Pipeline {
	pipeline, err := Define(name, define)
	if err != nil {
		panic(err)
	}
	return pipeline
}

// StepOption configures one step.
type StepOption func(*Step) error

// Step declares a node and returns a reference for dependency options.
func (b *Builder) Step(id string, invocation runner.Invocation, options ...StepOption) Ref {
	stepID := StepID(strings.TrimSpace(id))
	ref := Ref{id: stepID}
	step := Step{
		ID:     stepID,
		Run:    invocation,
		Target: "local",
		Cache:  CachePolicy{Mode: CacheOff},
	}

	for _, option := range options {
		if option == nil {
			b.errs = append(b.errs, fmt.Errorf("step %q has a nil option", stepID))
			continue
		}
		if err := option(&step); err != nil {
			b.errs = append(b.errs, fmt.Errorf("step %q: %w", stepID, err))
		}
	}

	if _, exists := b.pipeline.index[stepID]; exists {
		b.errs = append(b.errs, fmt.Errorf("step %q is declared more than once", stepID))
		return ref
	}
	b.pipeline.index[stepID] = len(b.pipeline.steps)
	b.pipeline.steps = append(b.pipeline.steps, cloneStep(step))
	return ref
}

// Describe adds human-readable context.
func Describe(description string) StepOption {
	return func(step *Step) error {
		step.Description = strings.TrimSpace(description)
		return nil
	}
}

// Needs adds prerequisite edges.
func Needs(refs ...Ref) StepOption {
	return func(step *Step) error {
		for _, ref := range refs {
			if ref.id == "" {
				return errors.New("dependency has an empty step ID")
			}
			step.Needs = append(step.Needs, ref.id)
		}
		return nil
	}
}

// On selects a registered target provider.
func On(target string) StepOption {
	return func(step *Step) error {
		target = strings.TrimSpace(target)
		if target == "" {
			return errors.New("target is empty")
		}
		step.Target = target
		return nil
	}
}

// Inputs declares files that participate in the cache key.
func Inputs(patterns ...string) StepOption {
	return func(step *Step) error {
		step.Inputs = append(step.Inputs, patterns...)
		return nil
	}
}

// Outputs declares files restored or captured by caching and artifact transfer.
func Outputs(patterns ...string) StepOption {
	return func(step *Step) error {
		step.Outputs = append(step.Outputs, patterns...)
		return nil
	}
}

// WithCache configures cache behavior and an explicit invalidation version.
func WithCache(mode CacheMode, version string) StepOption {
	return func(step *Step) error {
		switch mode {
		case CacheOff, CacheReadOnly, CacheReadWrite:
		default:
			return fmt.Errorf("unknown cache mode %q", mode)
		}
		step.Cache = CachePolicy{Mode: mode, Version: version}
		return nil
	}
}

// Retries configures retries after the first attempt.
func Retries(maxRetries int) StepOption {
	return func(step *Step) error {
		if maxRetries < 0 {
			return errors.New("max retries cannot be negative")
		}
		step.MaxRetries = maxRetries
		return nil
	}
}

// Resource requests a finite named target resource.
func Resource(name string, amount int64) StepOption {
	return func(step *Step) error {
		name = strings.TrimSpace(name)
		if name == "" {
			return errors.New("resource name is empty")
		}
		if amount <= 0 {
			return errors.New("resource amount must be positive")
		}
		if step.Resources == nil {
			step.Resources = make(map[string]int64)
		}
		step.Resources[name] = amount
		return nil
	}
}

func (b *Builder) validate() error {
	if b.pipeline.name == "" {
		b.errs = append(b.errs, errors.New("pipeline name is empty"))
	}
	if len(b.pipeline.steps) == 0 {
		b.errs = append(b.errs, errors.New("pipeline has no steps"))
	}

	for _, step := range b.pipeline.steps {
		if step.ID == "" {
			b.errs = append(b.errs, errors.New("step ID is empty"))
		}
		if err := step.Run.Validate(); err != nil {
			b.errs = append(b.errs, fmt.Errorf("step %q: %w", step.ID, err))
		}
		seenNeeds := make(map[StepID]struct{}, len(step.Needs))
		for _, dependency := range step.Needs {
			if dependency == step.ID {
				b.errs = append(b.errs, fmt.Errorf("step %q depends on itself", step.ID))
			}
			if _, ok := b.pipeline.index[dependency]; !ok {
				b.errs = append(b.errs, fmt.Errorf("step %q depends on unknown step %q", step.ID, dependency))
			}
			if _, duplicate := seenNeeds[dependency]; duplicate {
				b.errs = append(b.errs, fmt.Errorf("step %q repeats dependency %q", step.ID, dependency))
			}
			seenNeeds[dependency] = struct{}{}
		}
		if step.Cache.Mode != CacheOff && len(step.Outputs) == 0 {
			b.errs = append(b.errs, fmt.Errorf("step %q enables caching without outputs", step.ID))
		}
	}

	if len(b.errs) == 0 {
		if err := validateAcyclic(b.pipeline); err != nil {
			b.errs = append(b.errs, err)
		}
	}
	if len(b.errs) > 0 {
		return errors.Join(b.errs...)
	}
	return nil
}

func validateAcyclic(pipeline *Pipeline) error {
	inDegree := make(map[StepID]int, len(pipeline.steps))
	dependents := make(map[StepID][]StepID, len(pipeline.steps))
	for _, step := range pipeline.steps {
		inDegree[step.ID] = len(step.Needs)
		for _, dependency := range step.Needs {
			dependents[dependency] = append(dependents[dependency], step.ID)
		}
	}

	queue := make([]StepID, 0, len(pipeline.steps))
	for _, step := range pipeline.steps {
		if inDegree[step.ID] == 0 {
			queue = append(queue, step.ID)
		}
	}
	visited := 0
	for len(queue) > 0 {
		current := queue[0]
		queue = queue[1:]
		visited++
		for _, dependent := range dependents[current] {
			inDegree[dependent]--
			if inDegree[dependent] == 0 {
				queue = append(queue, dependent)
			}
		}
	}
	if visited == len(pipeline.steps) {
		return nil
	}

	cyclic := make([]string, 0)
	for id, degree := range inDegree {
		if degree > 0 {
			cyclic = append(cyclic, string(id))
		}
	}
	sort.Strings(cyclic)
	return fmt.Errorf("pipeline contains a dependency cycle involving %s", strings.Join(cyclic, ", "))
}

func cloneStep(step Step) Step {
	step.Run.Args = append([]string(nil), step.Run.Args...)
	if step.Run.Env != nil {
		step.Run.Env = cloneMap(step.Run.Env)
	}
	step.Needs = append([]StepID(nil), step.Needs...)
	step.Inputs = append([]string(nil), step.Inputs...)
	step.Outputs = append([]string(nil), step.Outputs...)
	if step.Resources != nil {
		resources := make(map[string]int64, len(step.Resources))
		for name, amount := range step.Resources {
			resources[name] = amount
		}
		step.Resources = resources
	}
	return step
}

func cloneMap(input map[string]string) map[string]string {
	output := make(map[string]string, len(input))
	for key, value := range input {
		output[key] = value
	}
	return output
}
