# Peer review response

This bootstrap intentionally changed pre-v1 contracts rather than preserving
the original local-runner shape.

## 1. Execution results and resumable state

`Executor` now participates in non-blocking admission and returns an
`ExecutionResult`. The result carries environment identity, execution digest,
cache hit, cache key, and output manifest. Those fields are committed to
`state.Step`; resume validates the recorded cache entry before retaining a
successful output-producing step. `StepCacheHit` now originates from a real
execution path.

## 2. A remotely falsified target contract

Environments now expose identity, upload, download, execution, and release.
Providers expose capabilities plus resource-aware `TryReserve`. The SSH package
is deliberately crude, but its test performs a real tar upload, remote command,
tar download, manifest-compatible extraction, and cleanup through a fake SSH
transport. Sprite remains the next production provider.

## 3. Honest cache identity

Cache identity is computed after runner resolution. It includes adapter
configuration, the resolved process, pipeline/step identity, input contents,
dependency manifests, explicit cache version, target platform/image, declared
environment values, and declared toolchain probe results. `flow.EnvironmentKeys`
and `flow.Toolchain` make ambient identity explicit.

## 4. Multiple controllers and targets

State is an append-only, revisioned transition journal owned through an
exclusive run lease. The local file store uses an OS file lock and atomic,
fsynced per-transition files. Scheduler admission is non-blocking and provider
specific, so saturated remote capacity does not occupy the global semaphore.
Local and SSH providers account for finite declared resources. Environment
cleanup uses a detached, deadline-bounded context.

## 5. Journal fidelity and event ordering

Every attempt and retry transition is persisted. Retry policy includes
exponential bounded backoff. `cancelled` is distinct from `failed` and `blocked`
in both state and `RunError`. Events are dispatched only after state commit and
the asynchronous ordered dispatcher keeps sinks outside the scheduling loop.

## 6. Resume digest and references

The structural digest excludes descriptions, retry tuning, and declaration
order while the full definition digest records them for diagnostics. A golden
test pins cross-process encoding. `flow.Ref` carries its owning builder, so a
reference cannot cross pipeline definitions even when IDs collide. Workspace
patterns reject absolute paths and parent traversal.

## 7. Driver protocol

The CLI now locates `.taskflow`, fingerprints its sources/module files/platform,
caches the compiled executable, performs a versioned JSON handshake, and then
delegates `list`, `graph`, `run`, and `resume`. An end-to-end test builds and
executes an actual temporary project driver and verifies cache reuse.

## Remaining deliberate gaps

- The SSH provider is not production quality and is not a Sprite substitute.
- Source materialization is per acquisition rather than one immutable snapshot
  per run.
- Driver cache identity does not recursively hash local `replace` dependencies.
- Shared/network journal and object-store implementations are contracts only;
  their distributed lease/CAS behavior still needs an implementation.
- State schema migration is explicit rejection pre-v1; a migration registry is
  required before compatibility is promised.
