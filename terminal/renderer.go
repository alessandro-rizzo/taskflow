// Package terminal renders Taskflow events as readable, line-oriented output.
package terminal

import (
	"context"
	"fmt"
	"io"
	"sync"

	"github.com/alessandro-rizzo/taskflow/event"
)

// Verbosity controls which events are rendered.
type Verbosity int

const (
	Quiet Verbosity = iota
	Normal
	Verbose
)

// Renderer is a concurrency-safe event sink. It intentionally does not redraw
// the screen or require a TTY.
type Renderer struct {
	mu        sync.Mutex
	writer    io.Writer
	verbosity Verbosity
}

// New constructs a renderer.
func New(writer io.Writer, verbosity Verbosity) *Renderer {
	return &Renderer{writer: writer, verbosity: verbosity}
}

// Emit renders one lifecycle transition.
func (r *Renderer) Emit(_ context.Context, value event.Event) {
	if r.writer == nil || !r.visible(value.Kind) {
		return
	}
	r.mu.Lock()
	defer r.mu.Unlock()

	switch value.Kind {
	case event.RunStarted:
		fmt.Fprintf(r.writer, "taskflow: run %s (%s)\n", value.RunID, value.Pipeline)
	case event.RunResumed:
		fmt.Fprintf(r.writer, "taskflow: resume %s (%s)\n", value.RunID, value.Pipeline)
	case event.StepStarted:
		fmt.Fprintf(r.writer, "→ %-24s [%s] attempt %d\n", value.StepID, value.Target, value.Attempt)
	case event.StepRetrying:
		fmt.Fprintf(r.writer, "↻ %-24s [%s] attempt %d: %v\n", value.StepID, value.Target, value.Attempt, value.Err)
	case event.StepSucceeded:
		fmt.Fprintf(r.writer, "✓ %-24s %s\n", value.StepID, value.Duration.Round(1e6))
	case event.StepFailed:
		fmt.Fprintf(r.writer, "✗ %-24s %s: %v\n", value.StepID, value.Duration.Round(1e6), value.Err)
	case event.StepBlocked:
		fmt.Fprintf(r.writer, "• %-24s blocked: %s\n", value.StepID, value.Message)
	case event.StepCacheHit:
		fmt.Fprintf(r.writer, "◆ %-24s cache hit\n", value.StepID)
	case event.RunSucceeded:
		fmt.Fprintf(r.writer, "taskflow: ✓ succeeded in %s\n", value.Duration.Round(1e6))
	case event.RunFailed:
		fmt.Fprintf(r.writer, "taskflow: ✗ failed in %s (%s)\n", value.Duration.Round(1e6), value.Message)
	}
}

func (r *Renderer) visible(kind event.Kind) bool {
	switch r.verbosity {
	case Quiet:
		return kind == event.StepFailed || kind == event.RunFailed
	case Normal:
		return kind != event.StepQueued
	default:
		return true
	}
}
