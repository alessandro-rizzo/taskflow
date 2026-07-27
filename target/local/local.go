// Package local executes steps as child processes on the controller.
package local

import (
	"bytes"
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
	"sync"
	"time"

	"github.com/alessandro-rizzo/taskflow/process"
	"github.com/alessandro-rizzo/taskflow/target"
	"github.com/alessandro-rizzo/taskflow/workspace"
)

type Provider struct {
	Root        string
	mu          sync.Mutex
	maxParallel int
	running     int
	exclusive   bool
	resources   map[string]int64
	used        map[string]int64
}

func New(root string) *Provider {
	size := runtime.NumCPU()
	if size < 1 {
		size = 1
	}
	return &Provider{
		Root: root, maxParallel: size,
		resources: map[string]int64{"cpu": int64(runtime.NumCPU())},
		used:      make(map[string]int64),
	}
}

func (*Provider) Name() string {
	return "local"
}

func (p *Provider) Capabilities(context.Context) (target.Capabilities, error) {
	return target.Capabilities{
		OS: runtime.GOOS, Architecture: runtime.GOARCH,
		MaxConcurrency: p.maxParallel,
		Resources:      cloneResources(p.resources),
	}, nil
}

func (p *Provider) TryReserve(_ context.Context, request target.AcquireRequest) (target.Reservation, bool, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.running >= p.maxParallel || p.exclusive ||
		(request.ExclusiveWorkspace && p.running > 0) ||
		!resourcesAvailable(p.resources, p.used, request.Resources) {
		return nil, false, nil
	}
	p.running++
	p.exclusive = request.ExclusiveWorkspace
	addResources(p.used, request.Resources, 1)
	return &reservation{provider: p, request: request}, true, nil
}

type reservation struct {
	provider *Provider
	request  target.AcquireRequest
	once     bool
}

func (r *reservation) Acquire(context.Context) (target.Environment, error) {
	root := r.provider.Root
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
	return &environment{id: "local:" + r.request.StepID, root: root}, nil
}

func (r *reservation) Release() {
	r.provider.mu.Lock()
	defer r.provider.mu.Unlock()
	if r.once {
		return
	}
	r.once = true
	r.provider.running--
	if r.request.ExclusiveWorkspace {
		r.provider.exclusive = false
	}
	addResources(r.provider.used, r.request.Resources, -1)
}

type environment struct {
	id   string
	root string
}

func (e *environment) ID() string {
	return e.id
}

func (e *environment) Identity(ctx context.Context, request target.IdentityRequest) (target.Identity, error) {
	identity := target.Identity{
		OS: runtime.GOOS, Architecture: runtime.GOARCH, Image: "local",
		Environment: make(map[string]string),
		Toolchains:  make(map[string]string),
	}
	merged := mergeEnvMap(os.Environ(), request.Overrides)
	for _, key := range request.Environment {
		identity.Environment[key] = merged[key]
	}
	for _, probe := range request.Toolchains {
		var output bytes.Buffer
		_, err := e.Exec(ctx, process.Spec{
			Program: probe.Program, Args: probe.Args, Dir: request.Dir,
			Env: request.Overrides,
		}, process.IO{Stdout: &output, Stderr: &output})
		if err != nil {
			return target.Identity{}, fmt.Errorf("probe toolchain %s: %w", probe.Name, err)
		}
		identity.Toolchains[probe.Name] = strings.TrimSpace(output.String())
	}
	return identity, nil
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

func (e *environment) Upload(ctx context.Context, source io.Reader) error {
	return workspace.Extract(ctx, e.root, source)
}

func (e *environment) Download(ctx context.Context, patterns []string, destination io.Writer) error {
	return workspace.Pack(ctx, e.root, patterns, destination)
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
	values := mergeEnvMap(base, overrides)
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

func mergeEnvMap(base []string, overrides map[string]string) map[string]string {
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
	return values
}

func writerOrDiscard(writer io.Writer) io.Writer {
	if writer == nil {
		return io.Discard
	}
	return writer
}

func resourcesAvailable(total, used, requested map[string]int64) bool {
	for name, amount := range requested {
		if used[name]+amount > total[name] {
			return false
		}
	}
	return true
}

func addResources(used, requested map[string]int64, direction int64) {
	for name, amount := range requested {
		used[name] += direction * amount
	}
}

func cloneResources(input map[string]int64) map[string]int64 {
	output := make(map[string]int64, len(input))
	for name, amount := range input {
		output[name] = amount
	}
	return output
}
