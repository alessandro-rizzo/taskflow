// Package event defines Taskflow's stable, line-oriented execution event stream.
package event

import (
	"context"
	"time"
)

// Kind identifies a run or step lifecycle transition.
type Kind string

const (
	RunStarted    Kind = "run.started"
	RunResumed    Kind = "run.resumed"
	RunSucceeded  Kind = "run.succeeded"
	RunFailed     Kind = "run.failed"
	StepQueued    Kind = "step.queued"
	StepStarted   Kind = "step.started"
	StepRetrying  Kind = "step.retrying"
	StepSucceeded Kind = "step.succeeded"
	StepFailed    Kind = "step.failed"
	StepBlocked   Kind = "step.blocked"
	StepCacheHit  Kind = "step.cache_hit"
)

// Event is intentionally transport-neutral so renderers and telemetry adapters
// can consume the same stream.
type Event struct {
	Kind     Kind
	RunID    string
	Pipeline string
	StepID   string
	Target   string
	Attempt  int
	Message  string
	Time     time.Time
	Duration time.Duration
	Err      error
}

// Sink consumes lifecycle events. Implementations must be safe for concurrent
// calls because independent steps may emit output in parallel.
type Sink interface {
	Emit(context.Context, Event)
}

// SinkFunc adapts a function to Sink.
type SinkFunc func(context.Context, Event)

// Emit implements Sink.
func (f SinkFunc) Emit(ctx context.Context, event Event) {
	f(ctx, event)
}

// Nop discards all events.
type Nop struct{}

// Emit implements Sink.
func (Nop) Emit(context.Context, Event) {}
