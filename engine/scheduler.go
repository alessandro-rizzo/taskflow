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

	"github.com/alessandro-rizzo/taskflow/event"
	"github.com/alessandro-rizzo/taskflow/flow"
	"github.com/alessandro-rizzo/taskflow/state"
)

// Executor runs one fully resolved flow step.
type Executor interface {
	Execute(context.Context, string, flow.Step) error
}

// Options controls one pipeline run.
type Options struct {
	RunID       string
	Resume      bool
	MaxParallel int
	FailFast    bool
}

// Scheduler runs dependency-ready steps in parallel and journals transitions.
type Scheduler struct {
	Executor Executor
	State    state.Store
	Events   event.Sink
	Now      func() time.Time
}

// RunError reports an unsuccessful pipeline while preserving its run ID.
type RunError struct {
	RunID  string
	Failed []string
}

func (e *RunError) Error() string {
	return fmt.Sprintf("run %s failed: %v", e.RunID, e.Failed)
}

type executionResult struct {
	id         string
	attempts   int
	startedAt  time.Time
	finishedAt time.Time
	err        error
}

// Run executes or resumes a pipeline.
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
	if s.Events == nil {
		s.Events = event.Nop{}
	}
	if s.Now == nil {
		s.Now = time.Now
	}

	digest, err := pipeline.Digest()
	if err != nil {
		return state.Run{}, err
	}

	run, err := s.prepareRun(ctx, pipeline, digest, options)
	if err != nil {
		return state.Run{}, err
	}
	if err := s.State.Save(ctx, run); err != nil {
		return state.Run{}, fmt.Errorf("save initial run state: %w", err)
	}

	runContext, cancel := context.WithCancel(ctx)
	defer cancel()
	results := make(chan executionResult, options.MaxParallel)
	steps := pipeline.Steps()
	stepByID := make(map[string]flow.Step, len(steps))
	for _, step := range steps {
		stepByID[string(step.ID)] = step
	}

	running := 0
	failedFast := false
	for {
		progress := false

		for _, step := range steps {
			if running >= options.MaxParallel || failedFast {
				break
			}
			record := run.Steps[string(step.ID)]
			if record.Status != state.Pending {
				continue
			}
			ready, blocked := dependenciesReady(step, run.Steps)
			if blocked {
				record.Status = state.Blocked
				record.FinishedAt = s.Now()
				record.Error = "dependency failed"
				run.Steps[string(step.ID)] = record
				run.UpdatedAt = s.Now()
				s.Events.Emit(ctx, event.Event{
					Kind:     event.StepBlocked,
					RunID:    run.ID,
					Pipeline: pipeline.Name(),
					StepID:   string(step.ID),
					Target:   step.Target,
					Time:     record.FinishedAt,
					Message:  record.Error,
				})
				progress = true
				continue
			}
			if !ready {
				continue
			}

			record.Status = state.Running
			record.Attempts++
			record.StartedAt = s.Now()
			record.Error = ""
			run.Steps[string(step.ID)] = record
			run.UpdatedAt = s.Now()
			if err := s.State.Save(ctx, run); err != nil {
				cancel()
				return state.Run{}, fmt.Errorf("save running step state: %w", err)
			}
			s.Events.Emit(ctx, event.Event{
				Kind:     event.StepStarted,
				RunID:    run.ID,
				Pipeline: pipeline.Name(),
				StepID:   string(step.ID),
				Target:   step.Target,
				Attempt:  record.Attempts,
				Time:     record.StartedAt,
			})

			running++
			progress = true
			go s.execute(runContext, run.ID, step, record.Attempts, results)
		}

		if running == 0 {
			if !progress {
				break
			}
			continue
		}

		result := <-results
		running--
		record := run.Steps[result.id]
		record.Attempts = result.attempts
		record.StartedAt = result.startedAt
		record.FinishedAt = result.finishedAt
		if result.err != nil {
			record.Status = state.Failed
			record.Error = result.err.Error()
			if options.FailFast {
				failedFast = true
				cancel()
			}
			s.Events.Emit(ctx, event.Event{
				Kind:     event.StepFailed,
				RunID:    run.ID,
				Pipeline: pipeline.Name(),
				StepID:   result.id,
				Target:   stepByID[result.id].Target,
				Attempt:  result.attempts,
				Time:     result.finishedAt,
				Duration: result.finishedAt.Sub(result.startedAt),
				Err:      result.err,
			})
		} else {
			record.Status = state.Succeeded
			record.Error = ""
			s.Events.Emit(ctx, event.Event{
				Kind:     event.StepSucceeded,
				RunID:    run.ID,
				Pipeline: pipeline.Name(),
				StepID:   result.id,
				Target:   stepByID[result.id].Target,
				Attempt:  result.attempts,
				Time:     result.finishedAt,
				Duration: result.finishedAt.Sub(result.startedAt),
			})
		}
		run.Steps[result.id] = record
		run.UpdatedAt = s.Now()
		if err := s.State.Save(ctx, run); err != nil {
			cancel()
			return state.Run{}, fmt.Errorf("save completed step state: %w", err)
		}
	}

	for id, record := range run.Steps {
		if record.Status == state.Pending || record.Status == state.Running {
			record.Status = state.Blocked
			record.FinishedAt = s.Now()
			if failedFast {
				record.Error = "run stopped after failure"
			} else {
				record.Error = "dependency did not succeed"
			}
			run.Steps[id] = record
			s.Events.Emit(ctx, event.Event{
				Kind:     event.StepBlocked,
				RunID:    run.ID,
				Pipeline: pipeline.Name(),
				StepID:   id,
				Target:   stepByID[id].Target,
				Time:     record.FinishedAt,
				Message:  record.Error,
			})
		}
	}

	failed := unsuccessfulSteps(run)
	run.UpdatedAt = s.Now()
	if len(failed) == 0 {
		run.Status = state.Succeeded
		s.Events.Emit(ctx, event.Event{
			Kind:     event.RunSucceeded,
			RunID:    run.ID,
			Pipeline: pipeline.Name(),
			Time:     run.UpdatedAt,
			Duration: run.UpdatedAt.Sub(run.CreatedAt),
		})
	} else {
		run.Status = state.Failed
		s.Events.Emit(ctx, event.Event{
			Kind:     event.RunFailed,
			RunID:    run.ID,
			Pipeline: pipeline.Name(),
			Time:     run.UpdatedAt,
			Duration: run.UpdatedAt.Sub(run.CreatedAt),
			Message:  fmt.Sprintf("%d step(s) unsuccessful", len(failed)),
		})
	}
	if err := s.State.Save(ctx, run); err != nil {
		return state.Run{}, fmt.Errorf("save final run state: %w", err)
	}
	if len(failed) > 0 {
		return state.Clone(run), &RunError{RunID: run.ID, Failed: failed}
	}
	return state.Clone(run), nil
}

func (s *Scheduler) prepareRun(
	ctx context.Context,
	pipeline *flow.Pipeline,
	digest string,
	options Options,
) (state.Run, error) {
	if options.Resume {
		if options.RunID == "" {
			return state.Run{}, errors.New("resume requires a run ID")
		}
		run, err := s.State.Load(ctx, options.RunID)
		if err != nil {
			return state.Run{}, fmt.Errorf("load resumable run: %w", err)
		}
		if run.Pipeline != pipeline.Name() || run.PipelineDigest != digest {
			return state.Run{}, errors.New("cannot resume: pipeline definition is incompatible with saved run")
		}
		for id, record := range run.Steps {
			if record.Status != state.Succeeded {
				record.Status = state.Pending
				record.StartedAt = time.Time{}
				record.FinishedAt = time.Time{}
				record.Error = ""
				run.Steps[id] = record
			}
		}
		run.Status = state.Running
		run.UpdatedAt = s.Now()
		s.Events.Emit(ctx, event.Event{
			Kind:     event.RunResumed,
			RunID:    run.ID,
			Pipeline: pipeline.Name(),
			Time:     run.UpdatedAt,
		})
		return run, nil
	}

	runID := options.RunID
	if runID == "" {
		generated, err := newRunID()
		if err != nil {
			return state.Run{}, err
		}
		runID = generated
	}
	now := s.Now()
	run := state.Run{
		ID:             runID,
		Pipeline:       pipeline.Name(),
		PipelineDigest: digest,
		Status:         state.Running,
		CreatedAt:      now,
		UpdatedAt:      now,
		Steps:          make(map[string]state.Step),
	}
	for _, step := range pipeline.Steps() {
		run.Steps[string(step.ID)] = state.Step{
			ID:     string(step.ID),
			Status: state.Pending,
			Target: step.Target,
		}
	}
	s.Events.Emit(ctx, event.Event{
		Kind:     event.RunStarted,
		RunID:    run.ID,
		Pipeline: pipeline.Name(),
		Time:     now,
	})
	return run, nil
}

func (s *Scheduler) execute(
	ctx context.Context,
	runID string,
	step flow.Step,
	firstAttempt int,
	results chan<- executionResult,
) {
	startedAt := s.Now()
	attempts := firstAttempt
	var err error
	for {
		err = s.Executor.Execute(ctx, runID, step)
		if err == nil || attempts > step.MaxRetries {
			break
		}
		attempts++
		s.Events.Emit(ctx, event.Event{
			Kind:    event.StepRetrying,
			RunID:   runID,
			StepID:  string(step.ID),
			Target:  step.Target,
			Attempt: attempts,
			Time:    s.Now(),
			Err:     err,
		})
	}
	results <- executionResult{
		id:         string(step.ID),
		attempts:   attempts,
		startedAt:  startedAt,
		finishedAt: s.Now(),
		err:        err,
	}
}

func dependenciesReady(step flow.Step, records map[string]state.Step) (ready bool, blocked bool) {
	for _, dependency := range step.Needs {
		record := records[string(dependency)]
		switch record.Status {
		case state.Succeeded:
			continue
		case state.Failed, state.Blocked:
			return false, true
		default:
			return false, false
		}
	}
	return true, false
}

func unsuccessfulSteps(run state.Run) []string {
	failed := make([]string, 0)
	for id, record := range run.Steps {
		if record.Status != state.Succeeded {
			failed = append(failed, id)
		}
	}
	sort.Strings(failed)
	return failed
}

func newRunID() (string, error) {
	var random [8]byte
	if _, err := rand.Read(random[:]); err != nil {
		return "", fmt.Errorf("generate run ID: %w", err)
	}
	return time.Now().UTC().Format("20060102T150405Z") + "-" + hex.EncodeToString(random[:]), nil
}
