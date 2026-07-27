// Package ssh is a deliberately small remote provider used to falsify
// Taskflow's target, transfer, cleanup, and identity contracts before provider
// SDK integrations are added.
package ssh

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/alessandro-rizzo/taskflow/process"
	"github.com/alessandro-rizzo/taskflow/target"
)

type Config struct {
	Name           string
	Host           string
	User           string
	Root           string
	Binary         string
	OS             string
	Architecture   string
	Image          string
	MaxConcurrency int
	Resources      map[string]int64
	Cleanup        bool
}

type Provider struct {
	config  Config
	mu      sync.Mutex
	running int
	used    map[string]int64
}

func New(config Config) (*Provider, error) {
	if config.Name == "" {
		config.Name = "ssh"
	}
	if config.Host == "" {
		return nil, errors.New("SSH host is required")
	}
	if config.Root == "" || !path.IsAbs(config.Root) || path.Clean(config.Root) == "/" {
		return nil, errors.New("SSH root must be an absolute non-root directory")
	}
	if config.Binary == "" {
		config.Binary = "ssh"
	}
	if config.OS == "" {
		config.OS = "linux"
	}
	if config.Architecture == "" {
		config.Architecture = "arm64"
	}
	if config.MaxConcurrency <= 0 {
		config.MaxConcurrency = 1
	}
	return &Provider{config: config, used: make(map[string]int64)}, nil
}

func (p *Provider) Name() string {
	return p.config.Name
}

func (p *Provider) Capabilities(context.Context) (target.Capabilities, error) {
	return target.Capabilities{
		OS: p.config.OS, Architecture: p.config.Architecture,
		MaxConcurrency: p.config.MaxConcurrency, Resources: cloneResources(p.config.Resources),
		Labels: map[string]string{"transport": "ssh", "host": p.config.Host},
	}, nil
}

func (p *Provider) TryReserve(
	_ context.Context,
	request target.AcquireRequest,
) (target.Reservation, bool, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.running >= p.config.MaxConcurrency ||
		!resourcesAvailable(p.config.Resources, p.used, request.Resources) {
		return nil, false, nil
	}
	p.running++
	addResources(p.used, request.Resources, 1)
	component := request.StepID
	if request.ExecutionGroup != "" {
		component = request.ExecutionGroup
	}
	workspace := path.Join(
		p.config.Root, safeComponent(request.RunID), safeComponent(component),
	)
	return &reservation{
		provider: p, workspace: workspace, stepID: request.StepID,
		resources: cloneResources(request.Resources),
	}, true, nil
}

type reservation struct {
	provider  *Provider
	workspace string
	stepID    string
	resources map[string]int64
	released  bool
}

func (r *reservation) Acquire(ctx context.Context) (target.Environment, error) {
	environment := &environment{
		provider: r.provider, id: r.provider.config.Host + ":" + r.stepID,
		workspace: r.workspace,
	}
	_, err := environment.remote(ctx, "mkdir -p -- "+quote(r.workspace), process.IO{})
	if err != nil {
		return nil, fmt.Errorf("create remote workspace: %w", err)
	}
	return environment, nil
}

func (r *reservation) Release() {
	r.provider.mu.Lock()
	defer r.provider.mu.Unlock()
	if r.released {
		return
	}
	r.released = true
	r.provider.running--
	addResources(r.provider.used, r.resources, -1)
}

type environment struct {
	provider  *Provider
	id        string
	workspace string
}

func (e *environment) ID() string {
	return e.id
}

func (e *environment) Identity(ctx context.Context, request target.IdentityRequest) (target.Identity, error) {
	identity := target.Identity{
		OS: e.provider.config.OS, Architecture: e.provider.config.Architecture,
		Image: e.provider.config.Image, Environment: make(map[string]string),
		Toolchains: make(map[string]string),
	}
	for _, key := range request.Environment {
		if value, exists := request.Overrides[key]; exists {
			identity.Environment[key] = value
			continue
		}
		var output bytes.Buffer
		_, err := e.Exec(ctx, process.Spec{
			Program: "sh", Args: []string{"-c", `printenv "$1" 2>/dev/null || true`, "sh", key},
			Dir: request.Dir,
		}, process.IO{Stdout: &output})
		if err != nil {
			return target.Identity{}, fmt.Errorf("read remote environment %s: %w", key, err)
		}
		identity.Environment[key] = strings.TrimSpace(output.String())
	}
	for _, probe := range request.Toolchains {
		var output bytes.Buffer
		_, err := e.Exec(ctx, process.Spec{
			Program: probe.Program, Args: probe.Args, Dir: request.Dir,
			Env: request.Overrides,
		}, process.IO{Stdout: &output, Stderr: &output})
		if err != nil {
			return target.Identity{}, fmt.Errorf("probe remote toolchain %s: %w", probe.Name, err)
		}
		identity.Toolchains[probe.Name] = strings.TrimSpace(output.String())
	}
	return identity, nil
}

func (e *environment) Exec(ctx context.Context, spec process.Spec, streams process.IO) (process.Result, error) {
	dir, err := remoteDir(e.workspace, spec.Dir)
	if err != nil {
		return process.Result{}, err
	}
	command := "cd " + quote(dir) + " && "
	if len(spec.Env) > 0 {
		keys := make([]string, 0, len(spec.Env))
		for key := range spec.Env {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		command += "env"
		for _, key := range keys {
			command += " " + quote(key+"="+spec.Env[key])
		}
		command += " "
	}
	command += quote(spec.Program)
	for _, argument := range spec.Args {
		command += " " + quote(argument)
	}
	return e.remote(ctx, command, streams)
}

func (e *environment) Upload(ctx context.Context, source io.Reader) error {
	_, err := e.remote(
		ctx,
		"mkdir -p -- "+quote(e.workspace)+" && tar -xpf - -C "+quote(e.workspace),
		process.IO{Stdin: source},
	)
	return err
}

func (e *environment) Download(ctx context.Context, patterns []string, destination io.Writer) error {
	if len(patterns) == 0 {
		return errors.New("remote download has no patterns")
	}
	expression := make([]string, 0, len(patterns))
	for _, pattern := range patterns {
		findPattern := "./" + strings.ReplaceAll(pattern, "**", "*")
		expression = append(expression, "-path "+quote(findPattern))
	}
	command := "cd " + quote(e.workspace) +
		" && find . -mindepth 1 \\( " + strings.Join(expression, " -o ") +
		" \\) -print0 | tar -cpf - --null -T -"
	_, err := e.remote(ctx, command, process.IO{Stdout: destination})
	return err
}

func (e *environment) Release(ctx context.Context, _ target.Release) error {
	if !e.provider.config.Cleanup {
		return nil
	}
	_, err := e.remote(ctx, "rm -rf -- "+quote(e.workspace), process.IO{})
	return err
}

func (e *environment) remote(
	ctx context.Context,
	remoteCommand string,
	streams process.IO,
) (process.Result, error) {
	destination := e.provider.config.Host
	if e.provider.config.User != "" {
		destination = e.provider.config.User + "@" + destination
	}
	command := exec.CommandContext(ctx, e.provider.config.Binary, destination, remoteCommand)
	command.Env = os.Environ()
	command.Stdin = streams.Stdin
	command.Stdout = writerOrDiscard(streams.Stdout)
	command.Stderr = writerOrDiscard(streams.Stderr)
	result := process.Result{StartedAt: time.Now()}
	err := command.Run()
	result.FinishedAt = time.Now()
	if err == nil {
		return result, nil
	}
	var exitError *exec.ExitError
	if errors.As(err, &exitError) {
		result.ExitCode = exitError.ExitCode()
	}
	return result, fmt.Errorf("SSH command failed: %w", err)
}

func remoteDir(root, relative string) (string, error) {
	if relative == "" {
		return root, nil
	}
	if path.IsAbs(relative) {
		return "", errors.New("remote process directory must be workspace-relative")
	}
	resolved := path.Clean(path.Join(root, relative))
	if resolved != root && !strings.HasPrefix(resolved, root+"/") {
		return "", errors.New("remote process directory escapes workspace")
	}
	return resolved, nil
}

func quote(value string) string {
	return "'" + strings.ReplaceAll(value, "'", "'\"'\"'") + "'"
}

func safeComponent(value string) string {
	if value != "" && strings.Trim(value, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-") == "" {
		return value
	}
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:8])
}

func cloneResources(input map[string]int64) map[string]int64 {
	output := make(map[string]int64, len(input))
	for name, amount := range input {
		output[name] = amount
	}
	return output
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

func writerOrDiscard(writer io.Writer) io.Writer {
	if writer == nil {
		return io.Discard
	}
	return writer
}
