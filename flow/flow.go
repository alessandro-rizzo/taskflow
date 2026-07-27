// Package flow provides the typed, code-first Taskflow DAG.
package flow

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"path"
	"sort"
	"strings"
	"time"

	"github.com/arr/taskflow/runner"
)

// StepID is a stable node identity inside a pipeline.
type StepID string

// Ref is a pipeline-scoped reference to a previously declared step.
//
// The owner token prevents a reference from one pipeline being accepted by
// another pipeline merely because the string IDs happen to match.
type Ref struct {
	id    StepID
	owner *Builder
}

// ID returns the referenced step identity.
func (r Ref) ID() StepID {
	return r.id
}

// CacheMode controls cache reads and writes for a step.
type CacheMode string

const (
	CacheOff       CacheMode = "off"
	CacheReadOnly  CacheMode = "read-only"
	CacheReadWrite CacheMode = "read-write"
)

// CachePolicy describes a step's cache behavior.
type CachePolicy struct {
	Mode    CacheMode `json:"mode"`
	Version string    `json:"version,omitempty"`
}

// RetryPolicy controls retries after the first attempt.
type RetryPolicy struct {
	MaxRetries     int           `json:"max_retries,omitempty"`
	InitialBackoff time.Duration `json:"initial_backoff,omitempty"`
	MaxBackoff     time.Duration `json:"max_backoff,omitempty"`
	Multiplier     float64       `json:"multiplier,omitempty"`
}

// ToolchainProbe captures actual toolchain identity inside the selected target.
type ToolchainProbe struct {
	Name    string   `json:"name"`
	Program string   `json:"program"`
	Args    []string `json:"args,omitempty"`
}

// Requirements are checked against provider capabilities before admission.
type Requirements struct {
	OS           string `json:"os,omitempty"`
	Architecture string `json:"architecture,omitempty"`
}

// Step is an immutable node returned by Pipeline.
type Step struct {
	ID             StepID            `json:"id"`
	Description    string            `json:"description,omitempty"`
	Run            runner.Invocation `json:"run"`
	Needs          []StepID          `json:"needs,omitempty"`
	Target         string            `json:"target"`
	ExecutionGroup string            `json:"execution_group,omitempty"`
	Requirements   Requirements      `json:"requirements,omitempty"`
	Inputs         []string          `json:"inputs,omitempty"`
	Outputs        []string          `json:"outputs,omitempty"`
	Environment    []string          `json:"environment,omitempty"`
	Toolchains     []ToolchainProbe  `json:"toolchains,omitempty"`
	Cache          CachePolicy       `json:"cache"`
	Retry          RetryPolicy       `json:"retry"`
	Resources      map[string]int64  `json:"resources,omitempty"`
}

// Pipeline is a validated DAG in declaration order.
type Pipeline struct {
	name  string
	steps []Step
	index map[StepID]int
}

func (p *Pipeline) Name() string {
	return p.name
}

func (p *Pipeline) Steps() []Step {
	steps := make([]Step, len(p.steps))
	for index, step := range p.steps {
		steps[index] = cloneStep(step)
	}
	return steps
}

func (p *Pipeline) Step(id StepID) (Step, bool) {
	index, ok := p.index[id]
	if !ok {
		return Step{}, false
	}
	return cloneStep(p.steps[index]), true
}

// StructuralDigest fingerprints resume- and cache-relevant semantics. It is
// independent of descriptions, retry tuning, and declaration order.
func (p *Pipeline) StructuralDigest() (string, error) {
	steps := p.Steps()
	sort.Slice(steps, func(i, j int) bool { return steps[i].ID < steps[j].ID })
	for index := range steps {
		steps[index].Description = ""
		steps[index].Retry = RetryPolicy{}
		sort.Slice(steps[index].Needs, func(i, j int) bool {
			return steps[index].Needs[i] < steps[index].Needs[j]
		})
		sort.Strings(steps[index].Inputs)
		sort.Strings(steps[index].Outputs)
		sort.Strings(steps[index].Environment)
		sort.Slice(steps[index].Toolchains, func(i, j int) bool {
			return steps[index].Toolchains[i].Name < steps[index].Toolchains[j].Name
		})
	}
	return digestValue(struct {
		Schema int    `json:"schema"`
		Name   string `json:"name"`
		Steps  []Step `json:"steps"`
	}{Schema: 1, Name: p.name, Steps: steps})
}

// DefinitionDigest fingerprints the complete authored definition for
// diagnostics. Unlike StructuralDigest, cosmetic and operational tuning changes
// are visible here.
func (p *Pipeline) DefinitionDigest() (string, error) {
	return digestValue(struct {
		Schema int    `json:"schema"`
		Name   string `json:"name"`
		Steps  []Step `json:"steps"`
	}{Schema: 1, Name: p.name, Steps: p.Steps()})
}

// Digest is retained as the semantic digest used by execution.
func (p *Pipeline) Digest() (string, error) {
	return p.StructuralDigest()
}

// Builder collects typed steps and deferred validation errors.
type Builder struct {
	pipeline *Pipeline
	errs     []error
}

func Define(name string, define func(*Builder)) (*Pipeline, error) {
	pipeline := &Pipeline{name: strings.TrimSpace(name), index: make(map[StepID]int)}
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

func MustDefine(name string, define func(*Builder)) *Pipeline {
	pipeline, err := Define(name, define)
	if err != nil {
		panic(err)
	}
	return pipeline
}

// StepOption configures one step with access to its owning builder.
type StepOption func(*Builder, *Step) error

func (b *Builder) Step(id string, invocation runner.Invocation, options ...StepOption) Ref {
	stepID := StepID(strings.TrimSpace(id))
	ref := Ref{id: stepID, owner: b}
	step := Step{
		ID:     stepID,
		Run:    invocation,
		Target: "local",
		Cache:  CachePolicy{Mode: CacheOff},
		Retry: RetryPolicy{
			InitialBackoff: time.Second,
			MaxBackoff:     30 * time.Second,
			Multiplier:     2,
		},
	}

	for _, option := range options {
		if option == nil {
			b.errs = append(b.errs, fmt.Errorf("step %q has a nil option", stepID))
			continue
		}
		if err := option(b, &step); err != nil {
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

func Describe(description string) StepOption {
	return func(_ *Builder, step *Step) error {
		step.Description = strings.TrimSpace(description)
		return nil
	}
}

func Needs(refs ...Ref) StepOption {
	return func(builder *Builder, step *Step) error {
		for _, ref := range refs {
			if ref.id == "" {
				return errors.New("dependency has an empty step ID")
			}
			if ref.owner != builder {
				return fmt.Errorf("dependency %q belongs to another pipeline", ref.id)
			}
			step.Needs = append(step.Needs, ref.id)
		}
		return nil
	}
}

func On(target string) StepOption {
	return func(_ *Builder, step *Step) error {
		target = strings.TrimSpace(target)
		if target == "" {
			return errors.New("target is empty")
		}
		step.Target = target
		return nil
	}
}

// InExecutionGroup requests affinity to one provider-managed workspace.
func InExecutionGroup(group string) StepOption {
	return func(_ *Builder, step *Step) error {
		group = strings.TrimSpace(group)
		if group == "" {
			return errors.New("execution group is empty")
		}
		step.ExecutionGroup = group
		return nil
	}
}

func Requires(osName, architecture string) StepOption {
	return func(_ *Builder, step *Step) error {
		step.Requirements = Requirements{
			OS:           strings.TrimSpace(osName),
			Architecture: strings.TrimSpace(architecture),
		}
		return nil
	}
}

func Inputs(patterns ...string) StepOption {
	return workspacePatterns("input", patterns, func(step *Step, values []string) {
		step.Inputs = append(step.Inputs, values...)
	})
}

func Outputs(patterns ...string) StepOption {
	return workspacePatterns("output", patterns, func(step *Step, values []string) {
		step.Outputs = append(step.Outputs, values...)
	})
}

// EnvironmentKeys declares ambient environment values that affect cache
// identity. Invocation-level explicit environment is always included.
func EnvironmentKeys(keys ...string) StepOption {
	return func(_ *Builder, step *Step) error {
		for _, key := range keys {
			key = strings.TrimSpace(key)
			if key == "" || strings.Contains(key, "=") {
				return fmt.Errorf("invalid environment key %q", key)
			}
			step.Environment = append(step.Environment, key)
		}
		return nil
	}
}

// Toolchain declares a command whose output identifies a toolchain on the
// selected target, for example Toolchain("go", "go", "version").
func Toolchain(name, program string, args ...string) StepOption {
	return func(_ *Builder, step *Step) error {
		name = strings.TrimSpace(name)
		program = strings.TrimSpace(program)
		if name == "" || program == "" {
			return errors.New("toolchain name and program are required")
		}
		step.Toolchains = append(step.Toolchains, ToolchainProbe{
			Name: name, Program: program, Args: append([]string(nil), args...),
		})
		return nil
	}
}

func WithCache(mode CacheMode, version string) StepOption {
	return func(_ *Builder, step *Step) error {
		switch mode {
		case CacheOff, CacheReadOnly, CacheReadWrite:
		default:
			return fmt.Errorf("unknown cache mode %q", mode)
		}
		step.Cache = CachePolicy{Mode: mode, Version: version}
		return nil
	}
}

func Retries(maxRetries int) StepOption {
	return Retry(maxRetries, time.Second, 30*time.Second, 2)
}

func Retry(maxRetries int, initialBackoff, maxBackoff time.Duration, multiplier float64) StepOption {
	return func(_ *Builder, step *Step) error {
		if maxRetries < 0 {
			return errors.New("max retries cannot be negative")
		}
		if initialBackoff < 0 || maxBackoff < 0 || maxBackoff < initialBackoff {
			return errors.New("invalid retry backoff bounds")
		}
		if multiplier < 1 {
			return errors.New("retry multiplier must be at least 1")
		}
		step.Retry = RetryPolicy{
			MaxRetries: maxRetries, InitialBackoff: initialBackoff,
			MaxBackoff: maxBackoff, Multiplier: multiplier,
		}
		return nil
	}
}

func Resource(name string, amount int64) StepOption {
	return func(_ *Builder, step *Step) error {
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
		if strings.Trim(string(step.ID), ".") == "" {
			b.errs = append(b.errs, fmt.Errorf("step ID %q cannot be dot-only", step.ID))
		}
		if step.ExecutionGroup != "" && strings.Trim(step.ExecutionGroup, ".") == "" {
			b.errs = append(b.errs, fmt.Errorf(
				"step %q execution group %q cannot be dot-only",
				step.ID,
				step.ExecutionGroup,
			))
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
		toolchains := make(map[string]struct{}, len(step.Toolchains))
		for _, probe := range step.Toolchains {
			if _, exists := toolchains[probe.Name]; exists {
				b.errs = append(b.errs, fmt.Errorf("step %q repeats toolchain %q", step.ID, probe.Name))
			}
			toolchains[probe.Name] = struct{}{}
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

func workspacePatterns(
	kind string,
	patterns []string,
	set func(*Step, []string),
) StepOption {
	return func(_ *Builder, step *Step) error {
		values := make([]string, 0, len(patterns))
		for _, pattern := range patterns {
			pattern = strings.TrimSpace(strings.ReplaceAll(pattern, "\\", "/"))
			if err := validateWorkspacePattern(pattern); err != nil {
				return fmt.Errorf("%s pattern %q: %w", kind, pattern, err)
			}
			values = append(values, pattern)
		}
		set(step, values)
		return nil
	}
}

func validateWorkspacePattern(pattern string) error {
	if pattern == "" {
		return errors.New("pattern is empty")
	}
	if strings.HasPrefix(pattern, "/") || path.IsAbs(pattern) {
		return errors.New("absolute paths are not allowed")
	}
	for _, segment := range strings.Split(pattern, "/") {
		if segment == ".." {
			return errors.New("workspace escape is not allowed")
		}
	}
	if cleaned := path.Clean(pattern); cleaned == "." || strings.HasPrefix(cleaned, "../") {
		return errors.New("pattern must stay below the workspace")
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

func digestValue(value any) (string, error) {
	encoded, err := json.Marshal(value)
	if err != nil {
		return "", fmt.Errorf("marshal pipeline definition: %w", err)
	}
	sum := sha256.Sum256(encoded)
	return hex.EncodeToString(sum[:]), nil
}

func cloneStep(step Step) Step {
	step.Run.Args = append([]string(nil), step.Run.Args...)
	if step.Run.Env != nil {
		step.Run.Env = cloneMap(step.Run.Env)
	}
	step.Needs = append([]StepID(nil), step.Needs...)
	step.Inputs = append([]string(nil), step.Inputs...)
	step.Outputs = append([]string(nil), step.Outputs...)
	step.Environment = append([]string(nil), step.Environment...)
	step.Toolchains = append([]ToolchainProbe(nil), step.Toolchains...)
	for index := range step.Toolchains {
		step.Toolchains[index].Args = append([]string(nil), step.Toolchains[index].Args...)
	}
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
