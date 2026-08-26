# Architecture-bootstrap prototype baseline

Status: preserved evidence

Source revision before relocation: `13a191b5253397199ae83b167dc341ca53041237`

Relocation date: 2026-08-26

## Purpose

This baseline records what the isolated prototype demonstrates and, equally
importantly, what it does not demonstrate. The new Taskflow implementation has
no source or API compatibility obligation to this module.

## Reproduction

From the repository root:

```sh
mise trust
mise install
mise exec -- task prototype:check
```

From this directory, trust the relocated standalone configuration once and run:

```sh
mise trust
mise install
mise exec -- task check
```

At relocation, the complete formatting, race-test, and vet gate passed on
macOS/arm64 with Go 1.25.12.

## Demonstrated concepts

- compiled Go pipeline definitions and project-driver handshake;
- graph validation, owned references, and stable structural digests;
- Taskfile, Just, and direct-command invocation adapters;
- parallel DAG scheduling with fail-fast, retry, and resource admission;
- non-blocking provider reservation before potentially slow acquisition;
- local target execution and a deliberately crude SSH-shaped contract spike;
- revisioned append-only run transitions with exclusive run ownership;
- compatible resume that revalidates successful output manifests;
- content-addressed result storage and run-scoped artifacts;
- deterministic workspace archives with path/symlink validation;
- cross-target dependency artifact restoration;
- structured lifecycle events and a line-oriented terminal renderer;
- cancellation with detached, deadline-bounded provider cleanup;
- adversarial tests for artifact restoration, corrupt cache behavior, resume
  invalidation, archive traversal, pipe handling, and process cancellation.

These results are evidence that the concepts are implementable. They are not
evidence that the current interfaces are the right public or distributed
contracts.

## Important limitations

- The public graph surface is low-level: `flow.Step`, `flow.Ref`, explicit
  `Needs`, string path patterns, and functional options.
- There is no typed project-domain value model such as `Artifact[T]`,
  `Service[T]`, `Endpoint[T]`, `Optional[T]`, or `Effect[T]`.
- The driver exposes no agent-oriented operation schema or immutable plan IR.
- Compiled project code runs as an ordinary process rather than inside a
  demonstrated planning security boundary.
- The source materializer captures the live workspace during each acquisition;
  it does not create one immutable run snapshot.
- The runtime acquires and probes an environment before cache lookup can finish.
- `target.Environment` combines reusable capacity, mutable workspace, identity,
  process execution, transfer, and cleanup.
- The local provider shares the checkout and inherits ambient host state; it is
  not a reproducible sandbox.
- The SSH provider is a contract-falsification spike with no production
  reconnection, pooling, credential, or fleet behavior.
- There is no shared daemon, global multi-agent scheduling, namespace lifecycle,
  service stack, endpoint routing, secret policy, or effects model.
- Native macOS/Xcode, simulator, emulator, device, and production remote
  providers are unimplemented.
- Status/cache explanations, crash fault injection, protocol migrations, and
  retention/garbage collection are incomplete.

## Graduation rule

A prototype concept may inform a clean implementation only after the
[risk-first roadmap](../../../docs/roadmap.md) records supporting experiment
evidence and an accepted decision. New production packages must not import this
Go module.
