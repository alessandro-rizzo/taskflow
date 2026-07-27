// Package taskfile adapts Go Task tasks to Taskflow invocations.
package taskfile

import (
	"context"
	"fmt"

	"github.com/alessandro-rizzo/taskflow/process"
	"github.com/alessandro-rizzo/taskflow/runner"
)

const adapterName = "taskfile"

// Adapter resolves Task task names.
type Adapter struct {
	Binary string
}

// New constructs an adapter for the task executable.
func New() Adapter {
	return Adapter{Binary: "task"}
}

// Name returns the registry name.
func (Adapter) Name() string {
	return adapterName
}

// Run creates an invocation of a named Task task. Extra arguments are passed
// after Task's argument separator.
func (Adapter) Run(task string, args ...string) runner.Invocation {
	return runner.Invocation{
		Adapter: adapterName,
		Recipe:  task,
		Args:    append([]string(nil), args...),
	}
}

// Resolve converts a Task invocation into a portable process.
func (a Adapter) Resolve(_ context.Context, invocation runner.Invocation) (process.Spec, error) {
	if invocation.Adapter != adapterName {
		return process.Spec{}, fmt.Errorf("taskfile adapter cannot resolve %q", invocation.Adapter)
	}
	binary := a.Binary
	if binary == "" {
		binary = "task"
	}
	args := []string{invocation.Recipe}
	if len(invocation.Args) > 0 {
		args = append(args, "--")
		args = append(args, invocation.Args...)
	}
	return process.Spec{
		Program: binary,
		Args:    args,
		Dir:     invocation.Dir,
		Env:     cloneMap(invocation.Env),
	}, nil
}

func cloneMap(input map[string]string) map[string]string {
	if input == nil {
		return nil
	}
	output := make(map[string]string, len(input))
	for key, value := range input {
		output[key] = value
	}
	return output
}
