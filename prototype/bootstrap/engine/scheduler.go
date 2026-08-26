// Package engine schedules validated Taskflow pipelines.
package engine

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/arr/taskflow/event"
	"github.com/arr/taskflow/flow"
	"github.com/arr/taskflow/state"
)

// ExecutionRequest includes dependency manifests required for cache identity.
type ExecutionRequest struct {
	RunID        string
	Pipeline     string
	Step         flow.Step
	Dependencies map[string]state.Step
}

// ExecutionResult is persisted before success or cache-hit events are emitted.
type ExecutionResult struct {
	EnvironmentID   string
	ExecutionDigest string
	CacheHit        bool
	CacheKey        string
	OutputManifest  string
	CleanupError    string
}

// Execution owns one provider reservation.
type Execution interface {
	Run(context.Context) (ExecutionResult, error)
	// Close releases an admitted execution that could not be started. It must
	// be idempotent and is also called after Run.
	Close()
}

// Executor participates in admission so a saturated target does not consume a
// global scheduler slot.
type Executor interface {
	TryAdmit(context.Context, ExecutionRequest) (Execution, bool, error)
	ValidateSuccess(context.Context, flow.Step, state.Step) (bool, error)
}

type Options struct {
	RunID       string
	Resume      bool
	MaxParallel int
	FailFast    bool
}

type Scheduler struct {
	Executor Executor
	State    state.Store
	Events   event.Sink
	Now      func() time.Time
}

type RunError struct {
	RunID     string
	Failed    []string
	Blocked   []string
	Cancelled []string
}

func (e *RunError) Error() string {
	return fmt.Sprintf(
		"run %s unsuccessful: failed=%v blocked=%v cancelled=%v",
		e.RunID, e.Failed, e.Blocked, e.Cancelled,
	)
}

type executionResult struct {
	id         string
	result     ExecutionResult
	startedAt  time.Time
	finishedAt time.Time
	err        error
}

func (s *Scheduler) Run(ctx context.Context, pipeline *flow.Pipeline, options Options) (state.Run, error) {
	if pipeline == nil {
		return state.Run{}, errors.New("pipeline is nil")
	}
	if s.Executor == nil {
		return state.Run{}, errors.New("engine executor is nil")
	}
	if s.State == nil {
		return state.Run{}, errors.New("engine state store is nil")
	}
	if options.MaxParallel <= 0 {
		options.MaxParallel = 1
	}
	now := s.Now
	if now == nil {
		now = time.Now
	}
	invocationStarted := now()
	events := event.NewDispatcher(s.Events)
	defer events.Close()

	runID := options.RunID
	if runID == "" {
		generated, err := newRunID()
		if err != nil {
			return state.Run{}, err
		}
		runID = generated
	}
	lease, err := s.State.Acquire(ctx, runID)
	if err != nil {
		return state.Run{}, fmt.Errorf("acquire run state: %w", err)
	}
	defer lease.Close()

	snapshot, err := s.prepareRun(ctx, lease, pipeline, runID, options, now, events)
	if err != nil {
		return state.Run{}, err
	}
	run := snapshot.Run
	revision := snapshot.Revision
	runContext, cancel := context.WithCancel(ctx)
	defer cancel()

	steps := pipeline.Steps()
	stepByID := make(map[string]flow.Step, len(steps))
	for _, step := range steps {
		stepByID[string(step.ID)] = step
	}
	results := make(chan executionResult, options.MaxParallel)
	retryAt := make(map[string]time.Time)
	running := 0
	failedFast := false
	contextDone := ctx.Done()

	for {
		progress := false
		currentTime := now()
		for _, step := range steps {
			if running >= options.MaxParallel || failedFast {
				break
			}
			if ctx.Err() != nil {
				failedFast = true
				cancel()
				break
			}
			id := string(step.ID)
			record := run.Steps[id]
			if record.Status != state.Pending || currentTime.Before(retryAt[id]) {
				continue
			}
			ready, blocked := dependenciesReady(step, run.Steps)
			if blocked {
				record.Status = state.Blocked
				record.FinishedAt = currentTime
				record.Error = "dependency did not succeed"
				snapshot, err = appendTransition(ctx, lease, revision, state.StepStatus(record, currentTime))
				if err != nil {
					cancel()
					return state.Run{}, err
				}
				run, revision = snapshot.Run, snapshot.Revision
				events.Emit(ctx, event.Event{
					Kind: event.StepBlocked, RunID: run.ID, Pipeline: pipeline.Name(),
					StepID: id, Target: step.Target, Time: currentTime, Message: record.Error,
				})
				progress = true
				continue
			}
			if !ready {
				continue
			}
			execution, admitted, err := s.Executor.TryAdmit(ctx, ExecutionRequest{
				RunID: run.ID, Pipeline: pipeline.Name(), Step: step,
				Dependencies: dependencyRecords(step, run.Steps),
			})
			if err != nil {
				record.Status = state.Failed
				record.Attempts++
				record.StartedAt = currentTime
				record.FinishedAt = currentTime
				record.Error = fmt.Sprintf("admission failed: %v", err)
				snapshot, appendErr := appendTransition(
					context.WithoutCancel(ctx),
					lease,
					revision,
					state.StepStatus(record, currentTime),
				)
				if appendErr != nil {
					cancel()
					drainExecutions(results, running)
					return state.Run{}, errors.Join(
						fmt.Errorf("admit step %s: %w", id, err),
						appendErr,
					)
				}
				run, revision = snapshot.Run, snapshot.Revision
				events.Emit(ctx, event.Event{
					Kind: event.StepFailed, RunID: run.ID, Pipeline: pipeline.Name(),
					StepID: id, Target: step.Target, Attempt: record.Attempts,
					Time: currentTime, Err: errors.New(record.Error),
				})
				if options.FailFast {
					failedFast = true
					cancel()
				}
				progress = true
				continue
			}
			if !admitted {
				continue
			}
			record.Status = state.Running
			record.Attempts++
			record.StartedAt = currentTime
			record.FinishedAt = time.Time{}
			record.Error = ""
			snapshot, err = appendTransition(ctx, lease, revision, state.StepStatus(record, currentTime))
			if err != nil {
				execution.Close()
				cancel()
				drainExecutions(results, running)
				return state.Run{}, err
			}
			run, revision = snapshot.Run, snapshot.Revision
			events.Emit(ctx, event.Event{
				Kind: event.StepStarted, RunID: run.ID, Pipeline: pipeline.Name(),
				StepID: id, Target: step.Target, Attempt: record.Attempts, Time: currentTime,
			})
			running++
			progress = true
			go execute(runContext, execution, id, currentTime, now, results)
		}

		if running == 0 {
			if allTerminal(run) || failedFast {
				break
			}
			if progress {
				continue
			}
			wait := nextRetryDelay(now(), retryAt, run.Steps)
			if wait <= 0 {
				wait = 25 * time.Millisecond
			}
			select {
			case <-contextDone:
				failedFast = true
				cancel()
				contextDone = nil
			case <-time.After(wait):
			}
			continue
		}

		var retryTimer *time.Timer
		var retryReady <-chan time.Time
		if wait := nextRetryDelay(now(), retryAt, run.Steps); wait > 0 {
			retryTimer = time.NewTimer(wait)
			retryReady = retryTimer.C
		}
		select {
		case completed := <-results:
			running--
			id := completed.id
			step := stepByID[id]
			record := run.Steps[id]
			record.FinishedAt = completed.finishedAt
			record.EnvironmentID = completed.result.EnvironmentID
			record.ExecutionDigest = completed.result.ExecutionDigest
			record.CacheHit = completed.result.CacheHit
			record.CacheKey = completed.result.CacheKey
			record.OutputManifest = completed.result.OutputManifest
			record.CleanupError = completed.result.CleanupError
			if completed.err == nil {
				record.Status = state.Succeeded
				record.Error = ""
			} else if errors.Is(completed.err, context.Canceled) {
				record.Status = state.Cancelled
				record.Error = completed.err.Error()
			} else if record.Attempts <= step.Retry.MaxRetries {
				record.Status = state.Pending
				record.Error = completed.err.Error()
				delay := retryDelay(step.Retry, record.Attempts)
				retryAt[id] = now().Add(delay)
			} else {
				record.Status = state.Failed
				record.Error = completed.err.Error()
			}
			// Fail-fast may already have cancelled the run context. Durable
			// completion and cancellation records still have to reach a remote
			// journal.
			snapshot, err = appendTransition(
				context.WithoutCancel(ctx),
				lease,
				revision,
				state.StepStatus(record, completed.finishedAt),
			)
			if err != nil {
				cancel()
				drainExecutions(results, running)
				return state.Run{}, err
			}
			run, revision = snapshot.Run, snapshot.Revision
			duration := completed.finishedAt.Sub(completed.startedAt)
			switch record.Status {
			case state.Succeeded:
				if record.CleanupError != "" {
					events.Emit(ctx, event.Event{
						Kind: event.StepCleanupFailed, RunID: run.ID, Pipeline: pipeline.Name(),
						StepID: id, Target: step.Target, Time: completed.finishedAt,
						Err: errors.New(record.CleanupError),
					})
				}
				if record.CacheHit {
					events.Emit(ctx, event.Event{
						Kind: event.StepCacheHit, RunID: run.ID, Pipeline: pipeline.Name(),
						StepID: id, Target: step.Target, Time: completed.finishedAt,
					})
				}
				events.Emit(ctx, event.Event{
					Kind: event.StepSucceeded, RunID: run.ID, Pipeline: pipeline.Name(),
					StepID: id, Target: step.Target, Attempt: record.Attempts,
					Time: completed.finishedAt, Duration: duration,
				})
			case state.Pending:
				events.Emit(ctx, event.Event{
					Kind: event.StepRetrying, RunID: run.ID, Pipeline: pipeline.Name(),
					StepID: id, Target: step.Target, Attempt: record.Attempts + 1,
					Time: completed.finishedAt, Err: completed.err,
					Message: retryAt[id].Sub(now()).Round(time.Millisecond).String(),
				})
			case state.Cancelled:
				events.Emit(ctx, event.Event{
					Kind: event.StepCancelled, RunID: run.ID, Pipeline: pipeline.Name(),
					StepID: id, Target: step.Target, Attempt: record.Attempts,
					Time: completed.finishedAt, Duration: duration, Err: completed.err,
				})
			case state.Failed:
				events.Emit(ctx, event.Event{
					Kind: event.StepFailed, RunID: run.ID, Pipeline: pipeline.Name(),
					StepID: id, Target: step.Target, Attempt: record.Attempts,
					Time: completed.finishedAt, Duration: duration, Err: completed.err,
				})
				if options.FailFast {
					failedFast = true
					cancel()
				}
			}
		case <-contextDone:
			failedFast = true
			cancel()
			contextDone = nil
		case <-retryReady:
			// Re-enter admission even when unrelated work is still running.
		}
		if retryTimer != nil {
			retryTimer.Stop()
		}
	}

	for id, record := range run.Steps {
		if record.Status != state.Pending && record.Status != state.Running {
			continue
		}
		record.FinishedAt = now()
		if ctx.Err() != nil {
			record.Status = state.Cancelled
			record.Error = ctx.Err().Error()
		} else {
			record.Status = state.Blocked
			record.Error = "run stopped before admission"
		}
		snapshot, err = appendTransition(context.WithoutCancel(ctx), lease, revision, state.StepStatus(record, record.FinishedAt))
		if err != nil {
			return state.Run{}, err
		}
		run, revision = snapshot.Run, snapshot.Revision
		kind := event.StepBlocked
		if record.Status == state.Cancelled {
			kind = event.StepCancelled
		}
		events.Emit(context.WithoutCancel(ctx), event.Event{
			Kind: kind, RunID: run.ID, Pipeline: pipeline.Name(),
			StepID: id, Target: stepByID[id].Target, Time: record.FinishedAt,
			Message: record.Error,
		})
	}

	failed, blocked, cancelled := outcomes(run)
	finalStatus := state.Succeeded
	if len(failed) > 0 || len(blocked) > 0 {
		finalStatus = state.Failed
	} else if len(cancelled) > 0 {
		finalStatus = state.Cancelled
	}
	finishedAt := now()
	snapshot, err = appendTransition(
		context.WithoutCancel(ctx), lease, revision, state.RunStatus(finalStatus, finishedAt),
	)
	if err != nil {
		return state.Run{}, err
	}
	run = snapshot.Run
	finalEvent := event.RunSucceeded
	if finalStatus != state.Succeeded {
		finalEvent = event.RunFailed
	}
	events.Emit(context.WithoutCancel(ctx), event.Event{
		Kind: finalEvent, RunID: run.ID, Pipeline: pipeline.Name(), Time: finishedAt,
		Duration: finishedAt.Sub(invocationStarted),
		Message:  fmt.Sprintf("failed=%d blocked=%d cancelled=%d", len(failed), len(blocked), len(cancelled)),
	})
	if finalStatus != state.Succeeded {
		return state.Clone(run), &RunError{
			RunID: run.ID, Failed: failed, Blocked: blocked, Cancelled: cancelled,
		}
	}
	return state.Clone(run), nil
}

func (s *Scheduler) prepareRun(
	ctx context.Context,
	lease state.Lease,
	pipeline *flow.Pipeline,
	runID string,
	options Options,
	now func() time.Time,
	events *event.Dispatcher,
) (state.Snapshot, error) {
	structuralDigest, err := pipeline.StructuralDigest()
	if err != nil {
		return state.Snapshot{}, err
	}
	definitionDigest, err := pipeline.DefinitionDigest()
	if err != nil {
		return state.Snapshot{}, err
	}
	if options.Resume {
		snapshot, err := lease.Load(ctx)
		if err != nil {
			return state.Snapshot{}, fmt.Errorf("load resumable run: %w", err)
		}
		if snapshot.Run.Pipeline != pipeline.Name() ||
			snapshot.Run.StructuralDigest != structuralDigest {
			return state.Snapshot{}, errors.New("cannot resume: pipeline structure is incompatible with saved run")
		}
		steps := pipeline.Steps()
		reset := make(map[string]bool, len(steps))
		for _, step := range steps {
			id := string(step.ID)
			record := snapshot.Run.Steps[id]
			if record.Status != state.Succeeded {
				reset[id] = true
				continue
			}
			keep, validateErr := s.Executor.ValidateSuccess(ctx, step, record)
			if validateErr != nil {
				return state.Snapshot{}, fmt.Errorf("validate saved success %s: %w", id, validateErr)
			}
			reset[id] = !keep
		}
		changed := true
		for changed {
			changed = false
			for _, step := range steps {
				id := string(step.ID)
				if reset[id] {
					continue
				}
				for _, dependency := range step.Needs {
					if reset[string(dependency)] {
						reset[id] = true
						changed = true
						break
					}
				}
			}
		}
		for _, step := range steps {
			id := string(step.ID)
			if !reset[id] {
				continue
			}
			record := snapshot.Run.Steps[id]
			record.Status = state.Pending
			record.Attempts = 0
			record.StartedAt = time.Time{}
			record.FinishedAt = time.Time{}
			record.Error = ""
			record.CacheHit = false
			record.EnvironmentID = ""
			record.ExecutionDigest = ""
			record.CacheKey = ""
			record.OutputManifest = ""
			record.CleanupError = ""
			updated, err := lease.Append(ctx, snapshot.Revision, state.StepStatus(record, now()))
			if err != nil {
				return state.Snapshot{}, fmt.Errorf("journal resume reset: %w", err)
			}
			snapshot = updated
		}
		updated, err := lease.Append(ctx, snapshot.Revision, state.RunStatus(state.Running, now()))
		if err != nil {
			return state.Snapshot{}, fmt.Errorf("journal resumed run: %w", err)
		}
		events.Emit(ctx, event.Event{
			Kind: event.RunResumed, RunID: runID, Pipeline: pipeline.Name(), Time: now(),
		})
		return updated, nil
	}
	if _, err := lease.Load(ctx); err == nil {
		return state.Snapshot{}, fmt.Errorf("run %q already exists; use resume", runID)
	} else if !errors.Is(err, state.ErrNotFound) {
		return state.Snapshot{}, err
	}
	createdAt := now()
	run := state.Run{
		ID: runID, Pipeline: pipeline.Name(),
		StructuralDigest: structuralDigest, DefinitionDigest: definitionDigest,
		Status: state.Running, CreatedAt: createdAt, UpdatedAt: createdAt,
		Steps: make(map[string]state.Step),
	}
	for _, step := range pipeline.Steps() {
		run.Steps[string(step.ID)] = state.Step{
			ID: string(step.ID), Status: state.Pending, Target: step.Target,
		}
	}
	snapshot, err := lease.Append(ctx, 0, state.Created(run, createdAt))
	if err != nil {
		return state.Snapshot{}, fmt.Errorf("journal new run: %w", err)
	}
	events.Emit(ctx, event.Event{
		Kind: event.RunStarted, RunID: runID, Pipeline: pipeline.Name(), Time: createdAt,
	})
	for _, step := range pipeline.Steps() {
		events.Emit(ctx, event.Event{
			Kind: event.StepQueued, RunID: runID, Pipeline: pipeline.Name(),
			StepID: string(step.ID), Target: step.Target, Time: createdAt,
		})
	}
	return snapshot, nil
}

func execute(
	ctx context.Context,
	execution Execution,
	id string,
	startedAt time.Time,
	now func() time.Time,
	results chan<- executionResult,
) {
	result, err := execution.Run(ctx)
	execution.Close()
	results <- executionResult{
		id: id, result: result, startedAt: startedAt, finishedAt: now(), err: err,
	}
}

func drainExecutions(results <-chan executionResult, running int) {
	for running > 0 {
		<-results
		running--
	}
}

func appendTransition(
	ctx context.Context,
	lease state.Lease,
	revision uint64,
	transition state.Transition,
) (state.Snapshot, error) {
	snapshot, err := lease.Append(ctx, revision, transition)
	if err != nil {
		return state.Snapshot{}, fmt.Errorf("append state transition: %w", err)
	}
	return snapshot, nil
}

func dependenciesReady(step flow.Step, records map[string]state.Step) (bool, bool) {
	for _, dependency := range step.Needs {
		switch records[string(dependency)].Status {
		case state.Succeeded:
		case state.Failed, state.Blocked, state.Cancelled:
			return false, true
		default:
			return false, false
		}
	}
	return true, false
}

func dependencyRecords(step flow.Step, records map[string]state.Step) map[string]state.Step {
	result := make(map[string]state.Step, len(step.Needs))
	for _, dependency := range step.Needs {
		result[string(dependency)] = records[string(dependency)]
	}
	return result
}

func allTerminal(run state.Run) bool {
	for _, step := range run.Steps {
		if step.Status == state.Pending || step.Status == state.Running {
			return false
		}
	}
	return true
}

func outcomes(run state.Run) (failed, blocked, cancelled []string) {
	for id, record := range run.Steps {
		switch record.Status {
		case state.Failed:
			failed = append(failed, id)
		case state.Blocked:
			blocked = append(blocked, id)
		case state.Cancelled:
			cancelled = append(cancelled, id)
		}
	}
	sort.Strings(failed)
	sort.Strings(blocked)
	sort.Strings(cancelled)
	return
}

func retryDelay(policy flow.RetryPolicy, attempt int) time.Duration {
	delay := policy.InitialBackoff
	for current := 1; current < attempt; current++ {
		delay = time.Duration(float64(delay) * policy.Multiplier)
		if policy.MaxBackoff > 0 && delay >= policy.MaxBackoff {
			return policy.MaxBackoff
		}
	}
	return delay
}

func nextRetryDelay(now time.Time, retryAt map[string]time.Time, records map[string]state.Step) time.Duration {
	var earliest time.Time
	for id, at := range retryAt {
		if records[id].Status != state.Pending || !at.After(now) {
			continue
		}
		if earliest.IsZero() || at.Before(earliest) {
			earliest = at
		}
	}
	if earliest.IsZero() {
		return 0
	}
	return earliest.Sub(now)
}

func newRunID() (string, error) {
	var random [8]byte
	if _, err := rand.Read(random[:]); err != nil {
		return "", fmt.Errorf("generate run ID: %w", err)
	}
	return time.Now().UTC().Format("20060102T150405Z") + "-" + hex.EncodeToString(random[:]), nil
}
