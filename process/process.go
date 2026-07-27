// Package process defines the portable process request passed from runner
// adapters to execution targets.
package process

import (
	"io"
	"time"
)

// Spec is a target-neutral command description.
//
// Dir is relative to the acquired target workspace. Env contains overrides,
// not a complete environment.
type Spec struct {
	Program string
	Args    []string
	Dir     string
	Env     map[string]string
}

// IO carries process streams without embedding them in the serializable Spec.
type IO struct {
	Stdin  io.Reader
	Stdout io.Writer
	Stderr io.Writer
}

// Result describes a completed process.
type Result struct {
	ExitCode   int
	StartedAt  time.Time
	FinishedAt time.Time
}
