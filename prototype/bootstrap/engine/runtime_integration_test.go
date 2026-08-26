package engine_test

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"sync"
	"testing"

	"github.com/arr/taskflow/cache"
	cachefile "github.com/arr/taskflow/cache/file"
	"github.com/arr/taskflow/engine"
	"github.com/arr/taskflow/event"
	"github.com/arr/taskflow/flow"
	"github.com/arr/taskflow/runner"
	"github.com/arr/taskflow/runner/command"
	"github.com/arr/taskflow/state"
	"github.com/arr/taskflow/target"
	"github.com/arr/taskflow/target/local"
	"github.com/arr/taskflow/target/ssh"
)

func TestRuntimeCacheHitRestoresOutputWithoutExecuting(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "input.txt"), []byte("input"), 0o600); err != nil {
		t.Fatal(err)
	}
	direct := command.New()
	pipeline := flow.MustDefine("cached", func(p *flow.Builder) {
		p.Step(
			"build",
			direct.Run("sh", "-c", "printf x >> calls.txt; printf output > result.txt"),
			flow.Inputs("input.txt"),
			flow.Outputs("result.txt"),
			flow.WithCache(flow.CacheReadWrite, "v1"),
		)
	})
	runners := runner.NewRegistry()
	if err := runners.Register(direct); err != nil {
		t.Fatal(err)
	}
	targets := target.NewRegistry()
	if err := targets.Register(local.New(root)); err != nil {
		t.Fatal(err)
	}
	coordinator := &cache.Coordinator{
		Store: cachefile.New(filepath.Join(t.TempDir(), "cache")), WorkspaceRoot: root,
	}
	executor := &engine.RuntimeExecutor{
		Runners: runners, Targets: targets, Cache: coordinator,
		Stdout: io.Discard, Stderr: io.Discard,
	}
	var mu sync.Mutex
	var kinds []event.Kind
	sink := event.SinkFunc(func(_ context.Context, value event.Event) {
		mu.Lock()
		kinds = append(kinds, value.Kind)
		mu.Unlock()
	})
	scheduler := engine.Scheduler{Executor: executor, State: state.NewMemory(), Events: sink}
	if _, err := scheduler.Run(ctx, pipeline, engine.Options{RunID: "first"}); err != nil {
		t.Fatalf("first Run() error = %v", err)
	}
	if err := os.Remove(filepath.Join(root, "result.txt")); err != nil {
		t.Fatal(err)
	}
	second, err := scheduler.Run(ctx, pipeline, engine.Options{RunID: "second"})
	if err != nil {
		t.Fatalf("second Run() error = %v", err)
	}
	if !second.Steps["build"].CacheHit || second.Steps["build"].OutputManifest == "" {
		t.Fatalf("second step = %#v, want persisted cache hit and manifest", second.Steps["build"])
	}
	calls, err := os.ReadFile(filepath.Join(root, "calls.txt"))
	if err != nil {
		t.Fatal(err)
	}
	if string(calls) != "x" {
		t.Fatalf("command executions = %q, want one", calls)
	}
	output, err := os.ReadFile(filepath.Join(root, "result.txt"))
	if err != nil {
		t.Fatal(err)
	}
	if string(output) != "output" {
		t.Fatalf("restored output = %q", output)
	}
	mu.Lock()
	defer mu.Unlock()
	found := false
	for _, kind := range kinds {
		if kind == event.StepCacheHit {
			found = true
		}
	}
	if !found {
		t.Fatalf("events = %v, want StepCacheHit", kinds)
	}
}

func TestRuntimeTransfersDependencyArtifactsAcrossTargets(t *testing.T) {
	ctx := context.Background()
	fakeSSH := filepath.Join(t.TempDir(), "ssh")
	if err := os.WriteFile(
		fakeSSH,
		[]byte("#!/bin/sh\nshift\nexec /bin/sh -c \"$1\"\n"),
		0o700,
	); err != nil {
		t.Fatal(err)
	}
	buildRoot := t.TempDir()
	packageRoot := t.TempDir()
	buildTarget, err := ssh.New(ssh.Config{
		Name: "build-target", Host: "fixture", Root: filepath.ToSlash(buildRoot),
		Binary: fakeSSH, MaxConcurrency: 1,
	})
	if err != nil {
		t.Fatal(err)
	}
	packageTarget, err := ssh.New(ssh.Config{
		Name: "package-target", Host: "fixture", Root: filepath.ToSlash(packageRoot),
		Binary: fakeSSH, MaxConcurrency: 1,
	})
	if err != nil {
		t.Fatal(err)
	}
	direct := command.New()
	pipeline := flow.MustDefine("cross-target", func(p *flow.Builder) {
		build := p.Step(
			"build",
			direct.Run("sh", "-c", "printf artifact > artifact.txt"),
			flow.On("build-target"),
			flow.Outputs("artifact.txt"),
		)
		p.Step(
			"package",
			direct.Run("sh", "-c", "cat artifact.txt > package.txt"),
			flow.Needs(build),
			flow.On("package-target"),
			flow.Outputs("package.txt"),
		)
	})
	runners := runner.NewRegistry()
	if err := runners.Register(direct); err != nil {
		t.Fatal(err)
	}
	targets := target.NewRegistry()
	if err := targets.Register(buildTarget); err != nil {
		t.Fatal(err)
	}
	if err := targets.Register(packageTarget); err != nil {
		t.Fatal(err)
	}
	executor := &engine.RuntimeExecutor{
		Runners: runners,
		Targets: targets,
		Cache: &cache.Coordinator{
			Store:         cachefile.New(filepath.Join(t.TempDir(), "artifacts")),
			WorkspaceRoot: t.TempDir(),
		},
		Stdout: io.Discard,
		Stderr: io.Discard,
	}
	scheduler := engine.Scheduler{Executor: executor, State: state.NewMemory()}
	result, err := scheduler.Run(ctx, pipeline, engine.Options{
		RunID: "cross-target", MaxParallel: 2,
	})
	if err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	for _, id := range []string{"build", "package"} {
		if result.Steps[id].OutputManifest == "" || result.Steps[id].CacheKey == "" {
			t.Fatalf("step %s has no persisted run artifact: %#v", id, result.Steps[id])
		}
	}
	packaged, err := os.ReadFile(
		filepath.Join(packageRoot, "cross-target", "package", "package.txt"),
	)
	if err != nil {
		t.Fatal(err)
	}
	if string(packaged) != "artifact" {
		t.Fatalf("cross-target package = %q", packaged)
	}
}
