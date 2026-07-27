package engine

import (
	"context"
	"errors"
	"fmt"
	"io"

	"github.com/alessandro-rizzo/taskflow/flow"
	"github.com/alessandro-rizzo/taskflow/process"
	"github.com/alessandro-rizzo/taskflow/runner"
	"github.com/alessandro-rizzo/taskflow/target"
)

// RuntimeExecutor resolves runner invocations and executes them on target
// providers. Caching and workspace materialization wrap this executor later.
type RuntimeExecutor struct {
	Runners   *runner.Registry
	Targets   *target.Registry
	Workspace string
	Stdout    io.Writer
	Stderr    io.Writer
}

// Execute implements Executor.
func (e *RuntimeExecutor) Execute(ctx context.Context, runID string, step flow.Step) error {
	if e.Runners == nil {
		return errors.New("runner registry is nil")
	}
	if e.Targets == nil {
		return errors.New("target registry is nil")
	}
	spec, err := e.Runners.Resolve(ctx, step.Run)
	if err != nil {
		return err
	}
	provider, err := e.Targets.Provider(step.Target)
	if err != nil {
		return err
	}
	environment, err := provider.Acquire(ctx, target.AcquireRequest{
		RunID:     runID,
		StepID:    string(step.ID),
		Workspace: e.Workspace,
		Resources: cloneResources(step.Resources),
	})
	if err != nil {
		return fmt.Errorf("acquire %s target: %w", step.Target, err)
	}

	_, executeErr := environment.Exec(ctx, spec, process.IO{
		Stdout: e.Stdout,
		Stderr: e.Stderr,
	})
	releaseErr := environment.Release(ctx, target.Release{Success: executeErr == nil})
	return errors.Join(executeErr, releaseErr)
}

func cloneResources(input map[string]int64) map[string]int64 {
	if input == nil {
		return nil
	}
	output := make(map[string]int64, len(input))
	for name, amount := range input {
		output[name] = amount
	}
	return output
}
