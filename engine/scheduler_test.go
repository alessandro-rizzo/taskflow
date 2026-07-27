package engine_test

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/alessandro-rizzo/taskflow/engine"
	"github.com/alessandro-rizzo/taskflow/flow"
	"github.com/alessandro-rizzo/taskflow/runner/command"
	"github.com/alessandro-rizzo/taskflow/state"
)

func TestSchedulerParallelisesReadySteps(t *testing.T) {
	t.Parallel()

	run := command.New()
	pipeline := flow.MustDefine("parallel", func(p *flow.Builder) {
		p.Step("one", run.Run("true"))
		p.Step("two", run.Run("true"))
		p.Step("three", run.Run("true"))
	})
	executor := &concurrencyExecutor{delay: 40 * time.Millisecond}
	scheduler := engine.Scheduler{
		Executor: executor,
		State:    state.NewMemory(),
	}

	result, err := scheduler.Run(context.Background(), pipeline, engine.Options{
		MaxParallel: 3,
	})
	if err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if result.Status != state.Succeeded {
		t.Fatalf("run status = %q, want %q", result.Status, state.Succeeded)
	}
	if executor.maximum < 2 {
		t.Fatalf("maximum concurrency = %d, want at least 2", executor.maximum)
	}
}

func TestSchedulerResumeSkipsSuccessfulSteps(t *testing.T) {
	t.Parallel()

	run := command.New()
	pipeline := flow.MustDefine("resume", func(p *flow.Builder) {
		first := p.Step("first", run.Run("true"))
		p.Step("second", run.Run("flaky"), flow.Needs(first))
	})
	store := state.NewMemory()
	executor := &flakyExecutor{
		failuresRemaining: map[string]int{"second": 1},
		calls:             make(map[string]int),
	}
	scheduler := engine.Scheduler{Executor: executor, State: store}

	firstRun, err := scheduler.Run(context.Background(), pipeline, engine.Options{
		RunID:       "resume-test",
		MaxParallel: 2,
	})
	if err == nil {
		t.Fatal("first Run() error = nil, want failure")
	}
	if firstRun.Status != state.Failed {
		t.Fatalf("first run status = %q, want %q", firstRun.Status, state.Failed)
	}

	resumed, err := scheduler.Run(context.Background(), pipeline, engine.Options{
		RunID:       "resume-test",
		Resume:      true,
		MaxParallel: 2,
	})
	if err != nil {
		t.Fatalf("resumed Run() error = %v", err)
	}
	if resumed.Status != state.Succeeded {
		t.Fatalf("resumed status = %q, want %q", resumed.Status, state.Succeeded)
	}
	if got, want := executor.calls["first"], 1; got != want {
		t.Fatalf("first calls = %d, want %d", got, want)
	}
	if got, want := executor.calls["second"], 2; got != want {
		t.Fatalf("second calls = %d, want %d", got, want)
	}
}

type concurrencyExecutor struct {
	mu      sync.Mutex
	current int
	maximum int
	delay   time.Duration
}

func (e *concurrencyExecutor) Execute(ctx context.Context, _ string, _ flow.Step) error {
	e.mu.Lock()
	e.current++
	if e.current > e.maximum {
		e.maximum = e.current
	}
	e.mu.Unlock()

	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-time.After(e.delay):
	}

	e.mu.Lock()
	e.current--
	e.mu.Unlock()
	return nil
}

type flakyExecutor struct {
	mu                sync.Mutex
	failuresRemaining map[string]int
	calls             map[string]int
}

func (e *flakyExecutor) Execute(_ context.Context, _ string, step flow.Step) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	id := string(step.ID)
	e.calls[id]++
	if e.failuresRemaining[id] > 0 {
		e.failuresRemaining[id]--
		return errors.New("intentional test failure")
	}
	return nil
}
