// Package just adapts Just recipes to Taskflow invocations.
package just

import (
	"context"
	"fmt"

	"github.com/alessandro-rizzo/taskflow/process"
	"github.com/alessandro-rizzo/taskflow/runner"
)

const adapterName = "just"

// Adapter resolves Just recipe names.
type Adapter struct {
	Binary string
}

// New constructs an adapter for the just executable.
func New() Adapter {
	return Adapter{Binary: "just"}
}

// Name returns the registry name.
func (Adapter) Name() string {
	return adapterName
}

// Run creates an invocation of a named Just recipe.
func (Adapter) Run(recipe string, args ...string) runner.Invocation {
	return runner.Invocation{
		Adapter: adapterName,
		Recipe:  recipe,
		Args:    append([]string(nil), args...),
	}
}

// Resolve converts a Just invocation into a portable process.
func (a Adapter) Resolve(_ context.Context, invocation runner.Invocation) (process.Spec, error) {
	if invocation.Adapter != adapterName {
		return process.Spec{}, fmt.Errorf("just adapter cannot resolve %q", invocation.Adapter)
	}
	binary := a.Binary
	if binary == "" {
		binary = "just"
	}
	args := append([]string{invocation.Recipe}, invocation.Args...)
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
