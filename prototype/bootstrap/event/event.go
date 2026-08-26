// Package event defines Taskflow's stable, line-oriented execution event stream.
package event

import (
	"context"
	"sync"
	"time"
)

// Kind identifies a run or step lifecycle transition.
type Kind string

const (
	RunStarted        Kind = "run.started"
	RunResumed        Kind = "run.resumed"
	RunSucceeded      Kind = "run.succeeded"
	RunFailed         Kind = "run.failed"
	StepQueued        Kind = "step.queued"
	StepStarted       Kind = "step.started"
	StepRetrying      Kind = "step.retrying"
	StepSucceeded     Kind = "step.succeeded"
	StepFailed        Kind = "step.failed"
	StepCancelled     Kind = "step.cancelled"
	StepBlocked       Kind = "step.blocked"
	StepCacheHit      Kind = "step.cache_hit"
	StepCleanupFailed Kind = "step.cleanup_failed"
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

// Dispatcher decouples scheduling from potentially slow event consumers while
// preserving event order. Close flushes the unbounded in-memory queue.
type Dispatcher struct {
	sink   Sink
	mu     sync.Mutex
	cond   *sync.Cond
	queue  []queuedEvent
	closed bool
	done   chan struct{}
}

type queuedEvent struct {
	ctx   context.Context
	event Event
}

// NewDispatcher starts an asynchronous ordered dispatcher.
func NewDispatcher(sink Sink) *Dispatcher {
	if sink == nil {
		sink = Nop{}
	}
	dispatcher := &Dispatcher{sink: sink, done: make(chan struct{})}
	dispatcher.cond = sync.NewCond(&dispatcher.mu)
	go dispatcher.run()
	return dispatcher
}

// Emit enqueues without invoking the downstream sink on the scheduler path.
func (d *Dispatcher) Emit(ctx context.Context, value Event) {
	d.mu.Lock()
	if !d.closed {
		d.queue = append(d.queue, queuedEvent{ctx: ctx, event: value})
		d.cond.Signal()
	}
	d.mu.Unlock()
}

// Close flushes queued events and waits for the consumer.
func (d *Dispatcher) Close() {
	d.mu.Lock()
	d.closed = true
	d.cond.Signal()
	d.mu.Unlock()
	<-d.done
}

func (d *Dispatcher) run() {
	defer close(d.done)
	for {
		d.mu.Lock()
		for len(d.queue) == 0 && !d.closed {
			d.cond.Wait()
		}
		if len(d.queue) == 0 && d.closed {
			d.mu.Unlock()
			return
		}
		next := d.queue[0]
		d.queue[0] = queuedEvent{}
		d.queue = d.queue[1:]
		d.mu.Unlock()
		d.sink.Emit(next.ctx, next.event)
	}
}
