// Package command adapts direct executable invocations.
package command

import (
	"context"
	"fmt"

	"github.com/alessandro-rizzo/taskflow/process"
	"github.com/alessandro-rizzo/taskflow/runner"
)

const adapterName = "command"

// Adapter resolves direct commands.
type Adapter struct{}

// New constructs a command adapter.
func New() Adapter {
	return Adapter{}
}

// Name returns the registry name.
func (Adapter) Name() string {
	return adapterName
}

// Run creates a direct command invocation.
func (Adapter) Run(program string, args ...string) runner.Invocation {
	return runner.Invocation{
		Adapter: adapterName,
		Recipe:  program,
		Args:    append([]string(nil), args...),
	}
}

// Resolve converts an invocation to a portable process.
func (Adapter) Resolve(_ context.Context, invocation runner.Invocation) (process.Spec, error) {
	if invocation.Adapter != adapterName {
		return process.Spec{}, fmt.Errorf("command adapter cannot resolve %q", invocation.Adapter)
	}
	return process.Spec{
		Program: invocation.Recipe,
		Args:    append([]string(nil), invocation.Args...),
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
