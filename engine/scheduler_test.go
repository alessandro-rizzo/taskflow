package engine_test

import (
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/arr/taskflow/engine"
	"github.com/arr/taskflow/event"
	"github.com/arr/taskflow/flow"
	"github.com/arr/taskflow/process"
	"github.com/arr/taskflow/runner"
	"github.com/arr/taskflow/runner/command"
	"github.com/arr/taskflow/state"
	"github.com/arr/taskflow/target"
)

func TestSchedulerParallelisesReadySteps(t *testing.T) {
	t.Parallel()
	run := command.New()
	pipeline := flow.MustDefine("parallel", func(p *flow.Builder) {
		p.Step("one", run.Run("true"))
		p.Step("two", run.Run("true"))
		p.Step("three", run.Run("true"))
	})
	executor := newFakeExecutor()
	executor.delay = 40 * time.Millisecond
	scheduler := engine.Scheduler{Executor: executor, State: state.NewMemory()}
	result, err := scheduler.Run(context.Background(), pipeline, engine.Options{MaxParallel: 3})
	if err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if result.Status != state.Succeeded || executor.maximum < 2 {
		t.Fatalf("run=%q maximum=%d, want succeeded and concurrent", result.Status, executor.maximum)
	}
}

func TestSchedulerResumeSkipsValidSuccess(t *testing.T) {
	t.Parallel()
	run := command.New()
	pipeline := flow.MustDefine("resume", func(p *flow.Builder) {
		first := p.Step("first", run.Run("true"))
		p.Step("second", run.Run("flaky"), flow.Needs(first))
	})
	store := state.NewMemory()
	executor := newFakeExecutor()
	executor.failures["second"] = 1
	scheduler := engine.Scheduler{Executor: executor, State: store}
	firstRun, err := scheduler.Run(context.Background(), pipeline, engine.Options{
		RunID: "resume-test", MaxParallel: 2,
	})
	if err == nil || firstRun.Status != state.Failed {
		t.Fatalf("first Run() = %q, %v, want failure", firstRun.Status, err)
	}
	resumed, err := scheduler.Run(context.Background(), pipeline, engine.Options{
		RunID: "resume-test", Resume: true, MaxParallel: 2,
	})
	if err != nil || resumed.Status != state.Succeeded {
		t.Fatalf("resumed Run() = %q, %v", resumed.Status, err)
	}
	if executor.calls["first"] != 1 || executor.calls["second"] != 2 {
		t.Fatalf("calls = %#v, want first=1 second=2", executor.calls)
	}
}

func TestSchedulerResumeTransitivelyInvalidatesDependents(t *testing.T) {
	t.Parallel()
	run := command.New()
	pipeline := flow.MustDefine("transitive-resume", func(p *flow.Builder) {
		first := p.Step("first", run.Run("true"))
		p.Step("second", run.Run("true"), flow.Needs(first))
	})
	store := state.NewMemory()
	executor := newFakeExecutor()
	scheduler := engine.Scheduler{Executor: executor, State: store}
	if _, err := scheduler.Run(
		context.Background(),
		pipeline,
		engine.Options{RunID: "transitive"},
	); err != nil {
		t.Fatal(err)
	}
	executor.invalid["first"] = true
	resumed, err := scheduler.Run(
		context.Background(),
		pipeline,
		engine.Options{RunID: "transitive", Resume: true},
	)
	if err != nil {
		t.Fatal(err)
	}
	if executor.calls["first"] != 2 || executor.calls["second"] != 2 {
		t.Fatalf("calls = %v, want both invalid dependency and dependent re-executed", executor.calls)
	}
	if resumed.Steps["first"].Attempts != 1 || resumed.Steps["second"].Attempts != 1 {
		t.Fatalf("resume attempts = %#v, want retry budgets reset per invocation", resumed.Steps)
	}
}

func TestSchedulerResumeRejectsStructuralChangeButAllowsDescriptionChange(t *testing.T) {
	t.Parallel()
	run := command.New()
	original := flow.MustDefine("resume", func(p *flow.Builder) {
		p.Step("test", run.Run("true"), flow.Describe("before"))
	})
	store := state.NewMemory()
	executor := newFakeExecutor()
	scheduler := engine.Scheduler{Executor: executor, State: store}
	if _, err := scheduler.Run(context.Background(), original, engine.Options{RunID: "digest"}); err != nil {
		t.Fatalf("initial Run() error = %v", err)
	}
	cosmetic := flow.MustDefine("resume", func(p *flow.Builder) {
		p.Step("test", run.Run("true"), flow.Describe("after"))
	})
	if _, err := scheduler.Run(context.Background(), cosmetic, engine.Options{
		RunID: "digest", Resume: true,
	}); err != nil {
		t.Fatalf("cosmetic resume error = %v", err)
	}
	changed := flow.MustDefine("resume", func(p *flow.Builder) {
		p.Step("test", run.Run("false"))
	})
	if _, err := scheduler.Run(context.Background(), changed, engine.Options{
		RunID: "digest", Resume: true,
	}); err == nil {
		t.Fatal("structurally changed resume error = nil")
	}
}

func TestSchedulerFailFastCancelsRunningAndBlocksPending(t *testing.T) {
	t.Parallel()
	run := command.New()
	pipeline := flow.MustDefine("fail-fast", func(p *flow.Builder) {
		failing := p.Step("failing", run.Run("false"))
		p.Step("dependent", run.Run("true"), flow.Needs(failing))
		p.Step("slow", run.Run("sleep"))
	})
	executor := newFakeExecutor()
	executor.failures["failing"] = 1
	executor.block["slow"] = true
	scheduler := engine.Scheduler{Executor: executor, State: state.NewMemory()}
	result, err := scheduler.Run(context.Background(), pipeline, engine.Options{
		RunID: "fail-fast", MaxParallel: 2, FailFast: true,
	})
	if err == nil {
		t.Fatal("Run() error = nil")
	}
	if result.Steps["failing"].Status != state.Failed ||
		result.Steps["dependent"].Status != state.Blocked ||
		result.Steps["slow"].Status != state.Cancelled {
		t.Fatalf("unexpected statuses: %#v", result.Steps)
	}
}

func TestSchedulerPersistsExternalCancellation(t *testing.T) {
	t.Parallel()
	run := command.New()
	pipeline := flow.MustDefine("cancel", func(p *flow.Builder) {
		p.Step("slow", run.Run("sleep"))
	})
	executor := newFakeExecutor()
	executor.block["slow"] = true
	scheduler := engine.Scheduler{Executor: executor, State: state.NewMemory()}
	ctx, cancel := context.WithCancel(context.Background())
	finished := make(chan struct {
		run state.Run
		err error
	}, 1)
	go func() {
		result, err := scheduler.Run(ctx, pipeline, engine.Options{RunID: "cancel"})
		finished <- struct {
			run state.Run
			err error
		}{run: result, err: err}
	}()
	deadline := time.After(time.Second)
	for {
		executor.mu.Lock()
		started := executor.calls["slow"] > 0
		executor.mu.Unlock()
		if started {
			break
		}
		select {
		case <-deadline:
			t.Fatal("slow execution did not start")
		case <-time.After(time.Millisecond):
		}
	}
	cancel()
	result := <-finished
	if result.err == nil ||
		result.run.Status != state.Cancelled ||
		result.run.Steps["slow"].Status != state.Cancelled {
		t.Fatalf("cancelled run = %#v, error %v", result.run, result.err)
	}
}

func TestSchedulerPersistsEveryRetryAttempt(t *testing.T) {
	t.Parallel()
	run := command.New()
	pipeline := flow.MustDefine("retry", func(p *flow.Builder) {
		p.Step(
			"flaky",
			run.Run("flaky"),
			flow.Retry(1, time.Millisecond, time.Millisecond, 1),
		)
	})
	executor := newFakeExecutor()
	executor.failures["flaky"] = 1
	store := &recordingStore{Store: state.NewMemory()}
	scheduler := engine.Scheduler{Executor: executor, State: store}
	result, err := scheduler.Run(context.Background(), pipeline, engine.Options{RunID: "retry"})
	if err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if result.Steps["flaky"].Attempts != 2 {
		t.Fatalf("attempts = %d, want 2", result.Steps["flaky"].Attempts)
	}
	store.mu.Lock()
	defer store.mu.Unlock()
	var statuses []state.Status
	for _, transition := range store.transitions {
		if transition.Step != nil && transition.Step.ID == "flaky" {
			statuses = append(statuses, transition.Step.Status)
		}
	}
	want := []state.Status{state.Running, state.Pending, state.Running, state.Succeeded}
	if !slices.Equal(statuses, want) {
		t.Fatalf("journaled statuses = %v, want %v", statuses, want)
	}
}

func TestSchedulerWakesRetryWhileUnrelatedStepRuns(t *testing.T) {
	t.Parallel()
	run := command.New()
	pipeline := flow.MustDefine("retry-timer", func(p *flow.Builder) {
		p.Step(
			"flaky",
			run.Run("flaky"),
			flow.Retry(1, 20*time.Millisecond, 20*time.Millisecond, 1),
		)
		p.Step("slow", run.Run("slow"))
	})
	executor := &retryTimerExecutor{started: time.Now()}
	scheduler := engine.Scheduler{Executor: executor, State: state.NewMemory()}
	if _, err := scheduler.Run(context.Background(), pipeline, engine.Options{
		RunID: "retry-timer", MaxParallel: 2,
	}); err != nil {
		t.Fatal(err)
	}
	executor.mu.Lock()
	secondAttempt := executor.secondAttempt
	executor.mu.Unlock()
	if secondAttempt <= 0 || secondAttempt >= 150*time.Millisecond {
		t.Fatalf("second retry started after %s, want before unrelated 250ms step completed", secondAttempt)
	}
}

func TestSchedulerPersistsAdmissionFailureAndFinalRunStatus(t *testing.T) {
	t.Parallel()
	run := command.New()
	pipeline := flow.MustDefine("admission-failure", func(p *flow.Builder) {
		p.Step("unsupported", run.Run("true"))
	})
	scheduler := engine.Scheduler{
		Executor: admissionFailureExecutor{},
		State:    state.NewMemory(),
	}
	result, err := scheduler.Run(context.Background(), pipeline, engine.Options{
		RunID: "admission-failure",
	})
	if err == nil {
		t.Fatal("Run() error = nil")
	}
	if result.Status != state.Failed ||
		result.Steps["unsupported"].Status != state.Failed ||
		!strings.Contains(result.Steps["unsupported"].Error, "admission failed") {
		t.Fatalf("result = %#v, want durable admission failure", result)
	}
}

func TestSchedulerDoesNotEmitSuccessBeforeJournalCommit(t *testing.T) {
	t.Parallel()
	run := command.New()
	pipeline := flow.MustDefine("journal", func(p *flow.Builder) {
		p.Step("test", run.Run("true"))
	})
	var mu sync.Mutex
	var events []event.Kind
	sink := event.SinkFunc(func(_ context.Context, value event.Event) {
		mu.Lock()
		events = append(events, value.Kind)
		mu.Unlock()
	})
	store := &failingStore{Store: state.NewMemory(), failExpectedRevision: 2}
	scheduler := engine.Scheduler{
		Executor: newFakeExecutor(),
		State:    store,
		Events:   sink,
	}
	if _, err := scheduler.Run(context.Background(), pipeline, engine.Options{RunID: "journal"}); err == nil {
		t.Fatal("Run() error = nil, want journal failure")
	}
	mu.Lock()
	defer mu.Unlock()
	for _, kind := range events {
		if kind == event.StepSucceeded {
			t.Fatalf("events = %v, contained success before failed journal commit", events)
		}
	}
}

func TestSchedulerSkipsSaturatedTargetWithoutConsumingGlobalSlot(t *testing.T) {
	t.Parallel()
	run := command.New()
	pipeline := flow.MustDefine("admission", func(p *flow.Builder) {
		p.Step("remote", run.Run("true"), flow.On("remote"))
		p.Step("local", run.Run("true"))
	})
	executor := &admissionExecutor{}
	scheduler := engine.Scheduler{Executor: executor, State: state.NewMemory()}
	result, err := scheduler.Run(context.Background(), pipeline, engine.Options{
		RunID: "admission", MaxParallel: 1,
	})
	if err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if result.Status != state.Succeeded || executor.order[0] != "local" {
		t.Fatalf("status=%s order=%v, want local admitted before remote", result.Status, executor.order)
	}
}

func TestRuntimeReleaseUsesDetachedCleanupContext(t *testing.T) {
	t.Parallel()
	direct := command.New()
	pipeline := flow.MustDefine("cleanup", func(p *flow.Builder) {
		p.Step("cancelled", direct.Run("true"))
	})
	step, _ := pipeline.Step("cancelled")
	runners := runner.NewRegistry()
	if err := runners.Register(direct); err != nil {
		t.Fatal(err)
	}
	provider := &cleanupProvider{releaseContext: make(chan error, 1)}
	targets := target.NewRegistry()
	if err := targets.Register(provider); err != nil {
		t.Fatal(err)
	}
	executor := engine.RuntimeExecutor{Runners: runners, Targets: targets}
	execution, admitted, err := executor.TryAdmit(context.Background(), engine.ExecutionRequest{
		RunID: "run", Step: step,
	})
	if err != nil || !admitted {
		t.Fatalf("TryAdmit() = %v, %v", admitted, err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := execution.Run(ctx); !errors.Is(err, context.Canceled) {
		t.Fatalf("Run() error = %v, want context.Canceled", err)
	}
	if releaseErr := <-provider.releaseContext; releaseErr != nil {
		t.Fatalf("cleanup context error = %v, want nil", releaseErr)
	}
}

func TestRuntimeCleanupFailureDoesNotFailCompletedWork(t *testing.T) {
	t.Parallel()
	direct := command.New()
	pipeline := flow.MustDefine("cleanup-warning", func(p *flow.Builder) {
		p.Step("complete", direct.Run("true"))
	})
	step, _ := pipeline.Step("complete")
	runners := runner.NewRegistry()
	if err := runners.Register(direct); err != nil {
		t.Fatal(err)
	}
	provider := &cleanupProvider{
		releaseContext: make(chan error, 1),
		releaseErr:     errors.New("remote cleanup failed"),
	}
	targets := target.NewRegistry()
	if err := targets.Register(provider); err != nil {
		t.Fatal(err)
	}
	executor := engine.RuntimeExecutor{Runners: runners, Targets: targets}
	execution, admitted, err := executor.TryAdmit(context.Background(), engine.ExecutionRequest{
		RunID: "run", Pipeline: "cleanup-warning", Step: step,
	})
	if err != nil || !admitted {
		t.Fatalf("TryAdmit() = %v, %v", admitted, err)
	}
	result, err := execution.Run(context.Background())
	execution.Close()
	if err != nil {
		t.Fatalf("Run() error = %v, want successful work with cleanup warning", err)
	}
	if result.CleanupError != "remote cleanup failed" {
		t.Fatalf("CleanupError = %q", result.CleanupError)
	}
}

func TestArchiveMaterializerDoesNotDeadlockWhenUploadReturnsEarly(t *testing.T) {
	t.Parallel()
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "input"), make([]byte, 1024*1024), 0o600); err != nil {
		t.Fatal(err)
	}
	materializer := engine.ArchiveMaterializer{Root: root, Patterns: []string{"input"}}
	finished := make(chan error, 1)
	go func() {
		finished <- materializer.Materialize(context.Background(), cleanupEnvironment{})
	}()
	select {
	case err := <-finished:
		if err == nil {
			t.Fatal("Materialize() error = nil, want closed upload stream")
		}
	case <-time.After(time.Second):
		t.Fatal("Materialize() deadlocked after Upload returned early")
	}
}

type fakeExecutor struct {
	mu       sync.Mutex
	current  int
	maximum  int
	delay    time.Duration
	failures map[string]int
	block    map[string]bool
	calls    map[string]int
	invalid  map[string]bool
}

func newFakeExecutor() *fakeExecutor {
	return &fakeExecutor{
		failures: make(map[string]int), block: make(map[string]bool),
		calls: make(map[string]int), invalid: make(map[string]bool),
	}
}

func (e *fakeExecutor) TryAdmit(
	_ context.Context,
	request engine.ExecutionRequest,
) (engine.Execution, bool, error) {
	return fakeExecution{executor: e, step: request.Step}, true, nil
}

func (e *fakeExecutor) ValidateSuccess(_ context.Context, step flow.Step, _ state.Step) (bool, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	return !e.invalid[string(step.ID)], nil
}

type fakeExecution struct {
	executor *fakeExecutor
	step     flow.Step
}

func (fakeExecution) Close() {}

type failingStore struct {
	state.Store
	failExpectedRevision uint64
}

type recordingStore struct {
	state.Store
	mu          sync.Mutex
	transitions []state.Transition
}

func (s *recordingStore) Acquire(ctx context.Context, id string) (state.Lease, error) {
	lease, err := s.Store.Acquire(ctx, id)
	if err != nil {
		return nil, err
	}
	return &recordingLease{Lease: lease, store: s}, nil
}

type recordingLease struct {
	state.Lease
	store *recordingStore
}

func (l *recordingLease) Append(
	ctx context.Context,
	expected uint64,
	transition state.Transition,
) (state.Snapshot, error) {
	snapshot, err := l.Lease.Append(ctx, expected, transition)
	if err == nil {
		l.store.mu.Lock()
		l.store.transitions = append(l.store.transitions, transition)
		l.store.mu.Unlock()
	}
	return snapshot, err
}

func (s *failingStore) Acquire(ctx context.Context, id string) (state.Lease, error) {
	lease, err := s.Store.Acquire(ctx, id)
	if err != nil {
		return nil, err
	}
	return &failingLease{Lease: lease, failExpectedRevision: s.failExpectedRevision}, nil
}

type failingLease struct {
	state.Lease
	failExpectedRevision uint64
}

func (l *failingLease) Append(
	ctx context.Context,
	expected uint64,
	transition state.Transition,
) (state.Snapshot, error) {
	if expected == l.failExpectedRevision {
		return state.Snapshot{}, errors.New("intentional journal failure")
	}
	return l.Lease.Append(ctx, expected, transition)
}

type admissionExecutor struct {
	mu        sync.Mutex
	localDone bool
	order     []string
}

func (e *admissionExecutor) TryAdmit(
	_ context.Context,
	request engine.ExecutionRequest,
) (engine.Execution, bool, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	if request.Step.Target == "remote" && !e.localDone {
		return nil, false, nil
	}
	return admissionExecution{executor: e, id: string(request.Step.ID)}, true, nil
}

func (*admissionExecutor) ValidateSuccess(context.Context, flow.Step, state.Step) (bool, error) {
	return true, nil
}

type admissionExecution struct {
	executor *admissionExecutor
	id       string
}

func (admissionExecution) Close() {}

func (e admissionExecution) Run(context.Context) (engine.ExecutionResult, error) {
	e.executor.mu.Lock()
	e.executor.order = append(e.executor.order, e.id)
	if e.id == "local" {
		e.executor.localDone = true
	}
	e.executor.mu.Unlock()
	return engine.ExecutionResult{}, nil
}

type cleanupProvider struct {
	releaseContext chan error
	releaseErr     error
}

func (*cleanupProvider) Name() string {
	return "local"
}

func (*cleanupProvider) Capabilities(context.Context) (target.Capabilities, error) {
	return target.Capabilities{OS: "test", Architecture: "test", MaxConcurrency: 1}, nil
}

func (p *cleanupProvider) TryReserve(
	context.Context,
	target.AcquireRequest,
) (target.Reservation, bool, error) {
	return cleanupReservation{provider: p}, true, nil
}

type cleanupReservation struct {
	provider *cleanupProvider
}

func (r cleanupReservation) Acquire(context.Context) (target.Environment, error) {
	return cleanupEnvironment{provider: r.provider}, nil
}

func (cleanupReservation) Release() {}

type cleanupEnvironment struct {
	provider *cleanupProvider
}

type retryTimerExecutor struct {
	mu            sync.Mutex
	attempts      int
	started       time.Time
	secondAttempt time.Duration
}

func (e *retryTimerExecutor) TryAdmit(
	_ context.Context,
	request engine.ExecutionRequest,
) (engine.Execution, bool, error) {
	return retryTimerExecution{executor: e, id: string(request.Step.ID)}, true, nil
}

func (*retryTimerExecutor) ValidateSuccess(context.Context, flow.Step, state.Step) (bool, error) {
	return true, nil
}

type retryTimerExecution struct {
	executor *retryTimerExecutor
	id       string
}

func (retryTimerExecution) Close() {}

func (e retryTimerExecution) Run(context.Context) (engine.ExecutionResult, error) {
	if e.id == "slow" {
		time.Sleep(250 * time.Millisecond)
		return engine.ExecutionResult{}, nil
	}
	e.executor.mu.Lock()
	e.executor.attempts++
	attempt := e.executor.attempts
	if attempt == 2 {
		e.executor.secondAttempt = time.Since(e.executor.started)
	}
	e.executor.mu.Unlock()
	if attempt == 1 {
		return engine.ExecutionResult{}, errors.New("retry me")
	}
	return engine.ExecutionResult{}, nil
}

type admissionFailureExecutor struct{}

func (admissionFailureExecutor) TryAdmit(
	context.Context,
	engine.ExecutionRequest,
) (engine.Execution, bool, error) {
	return nil, false, errors.New("unsupported target")
}

func (admissionFailureExecutor) ValidateSuccess(
	context.Context,
	flow.Step,
	state.Step,
) (bool, error) {
	return true, nil
}

func (cleanupEnvironment) ID() string {
	return "cleanup"
}

func (cleanupEnvironment) Identity(context.Context, target.IdentityRequest) (target.Identity, error) {
	return target.Identity{OS: "test", Architecture: "test"}, nil
}

func (cleanupEnvironment) Exec(ctx context.Context, _ process.Spec, _ process.IO) (process.Result, error) {
	return process.Result{}, ctx.Err()
}

func (cleanupEnvironment) Upload(context.Context, io.Reader) error {
	return nil
}

func (cleanupEnvironment) Download(
	context.Context,
	[]string,
	io.Writer,
) error {
	return nil
}

func (e cleanupEnvironment) Release(ctx context.Context, _ target.Release) error {
	e.provider.releaseContext <- ctx.Err()
	return e.provider.releaseErr
}

func (e fakeExecution) Run(ctx context.Context) (engine.ExecutionResult, error) {
	id := string(e.step.ID)
	e.executor.mu.Lock()
	e.executor.calls[id]++
	e.executor.current++
	if e.executor.current > e.executor.maximum {
		e.executor.maximum = e.executor.current
	}
	fail := e.executor.failures[id] > 0
	if fail {
		e.executor.failures[id]--
	}
	block := e.executor.block[id]
	delay := e.executor.delay
	e.executor.mu.Unlock()
	defer func() {
		e.executor.mu.Lock()
		e.executor.current--
		e.executor.mu.Unlock()
	}()
	if block {
		<-ctx.Done()
		return engine.ExecutionResult{}, ctx.Err()
	}
	select {
	case <-ctx.Done():
		return engine.ExecutionResult{}, ctx.Err()
	case <-time.After(delay):
	}
	if fail {
		return engine.ExecutionResult{}, errors.New("intentional failure")
	}
	return engine.ExecutionResult{}, nil
}
