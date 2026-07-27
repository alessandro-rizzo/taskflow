package engine_test

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"sync"
	"testing"

	"github.com/alessandro-rizzo/taskflow/cache"
	cachefile "github.com/alessandro-rizzo/taskflow/cache/file"
	"github.com/alessandro-rizzo/taskflow/engine"
	"github.com/alessandro-rizzo/taskflow/event"
	"github.com/alessandro-rizzo/taskflow/flow"
	"github.com/alessandro-rizzo/taskflow/runner"
	"github.com/alessandro-rizzo/taskflow/runner/command"
	"github.com/alessandro-rizzo/taskflow/state"
	"github.com/alessandro-rizzo/taskflow/target"
	"github.com/alessandro-rizzo/taskflow/target/local"
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
