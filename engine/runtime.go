package engine

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"time"

	"github.com/alessandro-rizzo/taskflow/cache"
	"github.com/alessandro-rizzo/taskflow/flow"
	"github.com/alessandro-rizzo/taskflow/process"
	"github.com/alessandro-rizzo/taskflow/runner"
	"github.com/alessandro-rizzo/taskflow/state"
	"github.com/alessandro-rizzo/taskflow/target"
	"github.com/alessandro-rizzo/taskflow/workspace"
)

type Materializer interface {
	Materialize(context.Context, target.Environment) error
}

// ArchiveMaterializer streams a source snapshot through the target transfer
// contract. It is intentionally simple and provider-neutral.
type ArchiveMaterializer struct {
	Root     string
	Patterns []string
}

func (m ArchiveMaterializer) Materialize(ctx context.Context, environment target.Environment) error {
	reader, writer := io.Pipe()
	defer reader.Close()
	packed := make(chan error, 1)
	go func() {
		err := workspace.Pack(ctx, m.Root, m.Patterns, writer)
		_ = writer.CloseWithError(err)
		packed <- err
	}()
	uploadErr := environment.Upload(ctx, reader)
	_ = reader.Close()
	packErr := <-packed
	return errors.Join(uploadErr, packErr)
}

type RuntimeExecutor struct {
	Runners        *runner.Registry
	Targets        *target.Registry
	Cache          *cache.Coordinator
	Materializer   Materializer
	Stdout         io.Writer
	Stderr         io.Writer
	CleanupTimeout time.Duration
}

func (e *RuntimeExecutor) TryAdmit(
	ctx context.Context,
	request ExecutionRequest,
) (Execution, bool, error) {
	if e.Runners == nil {
		return nil, false, errors.New("runner registry is nil")
	}
	if e.Targets == nil {
		return nil, false, errors.New("target registry is nil")
	}
	resolved, err := e.Runners.Resolve(ctx, request.Step.Run)
	if err != nil {
		return nil, false, err
	}
	provider, err := e.Targets.Provider(request.Step.Target)
	if err != nil {
		return nil, false, err
	}
	capabilities, err := provider.Capabilities(ctx)
	if err != nil {
		return nil, false, fmt.Errorf("target capabilities: %w", err)
	}
	if err := validateCapabilities(request.Step, capabilities); err != nil {
		return nil, false, err
	}
	reservation, admitted, err := provider.TryReserve(ctx, target.AcquireRequest{
		RunID: request.RunID, StepID: string(request.Step.ID),
		ExecutionGroup: request.Step.ExecutionGroup,
		ExclusiveWorkspace: len(request.Step.Outputs) > 0 ||
			request.Step.Cache.Mode != flow.CacheOff,
		Resources: cloneResources(request.Step.Resources),
	})
	if err != nil || !admitted {
		return nil, admitted, err
	}
	return &runtimeExecution{
		executor: e, request: request, resolved: resolved, reservation: reservation,
	}, true, nil
}

func (e *RuntimeExecutor) ValidateSuccess(
	ctx context.Context,
	step flow.Step,
	record state.Step,
) (bool, error) {
	if len(step.Outputs) == 0 {
		return true, nil
	}
	if e.Cache == nil {
		return false, nil
	}
	return e.Cache.Valid(ctx, record.CacheKey, record.OutputManifest)
}

type runtimeExecution struct {
	executor    *RuntimeExecutor
	request     ExecutionRequest
	resolved    runner.Resolved
	reservation target.Reservation
}

func (e *runtimeExecution) Run(ctx context.Context) (result ExecutionResult, returnedErr error) {
	environment, err := e.reservation.Acquire(ctx)
	if err != nil {
		return result, fmt.Errorf("acquire %s target: %w", e.request.Step.Target, err)
	}
	result.EnvironmentID = environment.ID()
	success := false
	defer func() {
		timeout := e.executor.CleanupTimeout
		if timeout <= 0 {
			timeout = 30 * time.Second
		}
		cleanupCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), timeout)
		defer cancel()
		releaseErr := environment.Release(cleanupCtx, target.Release{Success: success})
		if releaseErr == nil {
			return
		}
		if success {
			result.CleanupError = releaseErr.Error()
			return
		}
		returnedErr = errors.Join(returnedErr, releaseErr)
	}()

	if e.executor.Materializer != nil {
		if err := e.executor.Materializer.Materialize(ctx, environment); err != nil {
			return result, fmt.Errorf("materialize workspace: %w", err)
		}
	}
	probes := make([]target.Probe, 0, len(e.resolved.Toolchains)+len(e.request.Step.Toolchains))
	for _, probe := range e.resolved.Toolchains {
		probes = append(probes, target.Probe{
			Name: probe.Name, Program: probe.Program, Args: append([]string(nil), probe.Args...),
		})
	}
	for _, probe := range e.request.Step.Toolchains {
		probes = append(probes, target.Probe{
			Name: probe.Name, Program: probe.Program, Args: append([]string(nil), probe.Args...),
		})
	}
	environmentIdentity, err := environment.Identity(ctx, target.IdentityRequest{
		Dir: e.resolved.Process.Dir, Environment: e.request.Step.Environment,
		Overrides: e.resolved.Process.Env, Toolchains: probes,
	})
	if err != nil {
		return result, fmt.Errorf("identify target environment: %w", err)
	}
	executionDigest, err := cacheExecutionDigest(e.resolved, environmentIdentity)
	if err != nil {
		return result, err
	}
	result.ExecutionDigest = executionDigest
	needsArtifactStore := e.request.Step.Cache.Mode != flow.CacheOff ||
		len(e.request.Step.Outputs) > 0
	for _, dependency := range e.request.Dependencies {
		needsArtifactStore = needsArtifactStore || dependency.OutputManifest != ""
	}
	if needsArtifactStore && e.executor.Cache == nil {
		return result, errors.New("caching and transferable artifacts require a cache coordinator")
	}

	var cacheIdentity cache.Identity
	if e.request.Step.Cache.Mode != flow.CacheOff {
		dependencyManifests := make(map[string]string, len(e.request.Dependencies))
		for id, dependency := range e.request.Dependencies {
			dependencyManifests[id] = dependency.OutputManifest
		}
		cacheIdentity, err = e.executor.Cache.ComputeIdentity(
			ctx,
			e.request.Pipeline,
			e.request.Step,
			e.resolved,
			environmentIdentity,
			dependencyManifests,
		)
		if err != nil {
			return result, err
		}
		result.CacheKey = string(cacheIdentity.Key)
		result.ExecutionDigest = cacheIdentity.ExecutionDigest
		entry, hit, err := e.executor.Cache.Restore(ctx, cacheIdentity.Key, environment)
		if err != nil {
			return result, err
		}
		if hit {
			result.CacheHit = true
			result.OutputManifest = entry.Manifest
			success = true
			return result, nil
		}
	}
	for _, dependencyID := range e.request.Step.Needs {
		dependency := e.request.Dependencies[string(dependencyID)]
		if dependency.OutputManifest == "" {
			continue
		}
		if dependency.CacheKey == "" {
			return result, fmt.Errorf(
				"dependency %s has outputs but no restorable artifact key",
				dependencyID,
			)
		}
		if err := e.executor.Cache.RestoreExpected(
			ctx,
			cache.Key(dependency.CacheKey),
			dependency.OutputManifest,
			environment,
		); err != nil {
			return result, fmt.Errorf("restore dependency %s: %w", dependencyID, err)
		}
	}
	_, err = environment.Exec(ctx, e.resolved.Process, process.IO{
		Stdout: e.executor.Stdout, Stderr: e.executor.Stderr,
	})
	if err != nil {
		return result, err
	}
	if len(e.request.Step.Outputs) > 0 {
		outputKey := cacheIdentity.Key
		if e.request.Step.Cache.Mode != flow.CacheReadWrite {
			outputKey = cache.RunArtifactKey(
				e.request.RunID,
				e.request.Pipeline,
				e.request.Step.ID,
				result.ExecutionDigest,
			)
		}
		entry, err := e.executor.Cache.Publish(
			ctx, outputKey, environment, e.request.Step.Outputs,
		)
		if err != nil {
			return result, err
		}
		result.CacheKey = string(outputKey)
		result.OutputManifest = entry.Manifest
	}
	success = true
	return result, nil
}

func (e *runtimeExecution) Close() {
	e.reservation.Release()
}

func validateCapabilities(step flow.Step, capabilities target.Capabilities) error {
	if step.Requirements.OS != "" && step.Requirements.OS != capabilities.OS {
		return fmt.Errorf("target %q OS is %q, need %q", step.Target, capabilities.OS, step.Requirements.OS)
	}
	if step.Requirements.Architecture != "" &&
		step.Requirements.Architecture != capabilities.Architecture {
		return fmt.Errorf(
			"target %q architecture is %q, need %q",
			step.Target, capabilities.Architecture, step.Requirements.Architecture,
		)
	}
	for name, amount := range step.Resources {
		available, ok := capabilities.Resources[name]
		if !ok || amount > available {
			return fmt.Errorf("target %q cannot satisfy resource %s=%d", step.Target, name, amount)
		}
	}
	if capabilities.MaxConcurrency <= 0 {
		return fmt.Errorf("target %q reports no execution capacity", step.Target)
	}
	return nil
}

func cacheExecutionDigest(resolved runner.Resolved, identity target.Identity) (string, error) {
	encoded, err := json.Marshal(struct {
		Resolved runner.Resolved `json:"resolved"`
		Identity target.Identity `json:"identity"`
	}{Resolved: resolved, Identity: identity})
	if err != nil {
		return "", fmt.Errorf("encode execution digest: %w", err)
	}
	return string(cache.NewKey(encoded)), nil
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
