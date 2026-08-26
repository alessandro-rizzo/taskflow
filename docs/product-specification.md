# Taskflow product specification

Status: proposed

Version: 0.1

Date: 2026-08-26

## 1. Executive summary

Taskflow is a code-first execution system for typed, reproducible project
workflows across local, remote, container, virtual-machine, macOS, simulator,
and device targets.

Its intended product position is:

> Dagger gives developers and agents typed container capabilities. Taskflow
> gives them typed project capabilities, executed on the native infrastructure
> each project operation actually requires.

Taskflow should feel like a small project SDK, not an infrastructure language.
An author should be able to express operations such as `Backend.Check()`,
`IOS.Build()`, or `E2E.Test(stack)` while reusable modules hide source
selection, target placement, toolchain identity, caches, service wiring,
resource leases, retries, and cleanup.

The system should be particularly effective for coding agents. Each agent gets
an isolated namespace and immutable source snapshot, can launch multiple
pipelines concurrently, can reproduce a complete application stack for its
worktree, and consumes a machine-readable API for discovery, planning,
execution, status, logs, and cancellation. A shared `taskflowd` daemon
arbitrates finite local and remote capacity so that independent agents do not
turn the developer's laptop into a bottleneck.

Taskflow does not require a container for reproducibility. It instead requires
the properties containers often provide: an immutable source snapshot, a
pinned execution profile, a clean per-node sandbox, an explicit environment,
controlled capabilities, declared inputs and outputs, and verified artifact
identity. The sandbox may be a Linux namespace, an overlay filesystem, an APFS
clone, a warm immutable VM, or a provider-specific native workspace. Isolation
strength is explicit rather than inferred from the word “container.”

The isolated architecture-bootstrap prototype demonstrates a low-level graph,
scheduler, durable journal, cache coordinator, compiled driver, runner
adapters, and target-provider contract. The new implementation starts from a
clean foundation and treats those results as evidence rather than API or code
compatibility constraints. Typed project values, conditional IR, immutable
source snapshots, `taskflowd`, worktree namespaces, reusable worker pools,
native providers, and the APIs shown below are proposed and are not implemented
yet.

## 2. Product intent

### 2.1 Problem

Modern repositories combine several kinds of automation:

- fast local formatting and linting;
- language-specific builds and tests;
- databases, queues, APIs, and browser tests;
- Linux-only security and packaging tools;
- macOS/Xcode builds and iOS simulators;
- Android emulators and physical devices;
- signing, publishing, and deployment effects;
- local Git hooks and remote CI events;
- concurrent work by humans and coding agents.

Task runners make individual commands convenient, while hosted CI products
coordinate remote jobs and container-oriented engines improve isolation and
caching. None of these alone gives Taskflow's intended combination:

1. a concise, typed project API;
2. durable, cache-aware DAG execution;
3. per-node placement across heterogeneous native targets;
4. lightweight reproducibility without requiring a new container for every
   node;
5. full-stack isolation for concurrent worktrees and agents;
6. one graph that works from a terminal, Git hook, agent, and CI trigger.

### 2.2 Product thesis

The authoring model should describe project values and capabilities, not
machines. The execution model should map those values to immutable artifacts,
leased services, and policy-approved effects on suitable targets.

This has four consequences:

- Types must continue through the graph. Returning a path or status string
  prematurely loses composition, identity, and discoverability.
- Reproducibility is a property of an execution contract, not of containers
  alone.
- Remote execution is a placement decision on a node, not a different pipeline
  language.
- Agents need a stable schema and lifecycle API in addition to compile-time Go
  types.

### 2.3 Goals

- Make the common pipeline definition shorter and more natural than the
  equivalent YAML workflow.
- Preserve ordinary Go functions, packages, generics, refactoring, tests, and
  editor support.
- Infer dependencies from typed values in normal usage.
- Make every planned node, condition, capability, cache decision, and placement
  explainable before it runs.
- Reuse immutable results and warm infrastructure without sharing mutable
  project state between agents.
- Make cache hits independent of worker provisioning wherever identity is known
  in advance.
- Support local execution, remote Linux, immutable VMs, native macOS/Xcode,
  simulators, emulators, and eventually physical devices.
- Keep Taskfile and Just useful as migration-friendly leaf recipe adapters.
- Keep Lefthook useful as the Git hook installer and trigger front door.
- Fail closed for secrets, signing, deployment, privileged targets, and
  undeclared external effects.

### 2.4 Non-goals

- Reimplementing GitHub Actions' YAML or expression language.
- Reimplementing Taskfile's templates, includes, watch mode, variables, and
  shell-recipe ergonomics.
- Treating every native target as if it were an OCI container.
- Becoming a general-purpose Kubernetes abstraction.
- Making arbitrary external effects cacheable.
- Sharing mutable databases, workspaces, simulator state, or credentials
  between unrelated agent namespaces.
- Promising byte-for-byte output determinism when an operation inherently uses
  timestamps, notarization, remote signing, or another nondeterministic
  authority. Taskflow should still record reproducible inputs and provenance.
- Requiring a hosted Taskflow control plane before local and self-hosted use is
  excellent.

## 3. Users and primary use cases

### 3.1 Developer

The developer wants one fast command locally, understandable output, automatic
reuse of prior work, and confidence that the same graph can use remote capacity
when needed.

Examples:

```sh
taskflow run check
taskflow run ios-test --device 'iPhone 17 Pro'
taskflow plan release --arg channel=beta
taskflow resume 01K3...
```

### 3.2 Coding agent

The agent needs to discover operations without reading arbitrary source,
validate arguments, inspect a plan, launch work asynchronously, stream
structured events, and clean up reliably. Multiple agents should be able to do
this concurrently.

```sh
taskflow api --json
taskflow describe e2e --json
taskflow plan e2e --arg platform=ios --workspace /worktrees/agent-7 --json
taskflow run e2e --arg platform=ios --workspace /worktrees/agent-7 --detach --json
taskflow watch 01K3... --jsonl
taskflow status 01K3... --json
taskflow cancel 01K3... --json
```

### 3.3 Module author

The module author encodes complexity once: toolchain profile, source patterns,
outputs, caches, services, resource needs, and target compatibility. Callers
receive a small typed API.

### 3.4 Infrastructure owner

Initially this may be the same developer. They configure local capacity,
remote Linux workers, macOS VM pools, simulator inventories, secrets, quotas,
network policies, and retention. Project code can request these capabilities
but cannot grant them to itself.

## 4. Product principles

### 4.1 Typed values, not merely typed configuration

`flow.Step` is already a Go type, but its routine inputs and outputs are strings.
The higher-level product API should pass typed graph values:

```text
Source -> Artifact[BackendBinary] -> Service[API] -> Report[E2E]
```

Each arrow establishes a dependency, identity relationship, and capability
boundary. The engine can plan it, cache it, authorize it, and explain it.

### 4.2 Progressive disclosure

The default API should expose project concepts. Infrastructure details belong
in reusable modules and profiles. The low-level kernel remains available when
an author genuinely needs it.

```text
project operation -> reusable module -> execution kernel
   concise             configurable       explicit
```

### 4.3 One graph everywhere

Human CLI, agent CLI, Git hooks, pull requests, scheduled runs, and remote CI
must call the same operation definition. Triggers may supply different source
views and parameters, but they must not duplicate graph semantics.

### 4.4 One owner per dependency edge

A dependency is either opaque inside a Taskfile/Just leaf or visible to
Taskflow. Once an edge needs independent placement, caching, retries, resume,
conditions, or observability, Taskflow owns it and the invoked leaf recipe must
not execute it again.

### 4.5 Immutable inputs, disposable state, reusable capacity

Taskflow should avoid provisioning a container or VM for every node. Workers
and base images are reusable and warm. A node receives a disposable sandbox
materialized from immutable inputs, and only declared outputs leave it.

### 4.6 Explainability is part of correctness

A cache hit, skip, placement, denial, retry, or resume decision must have a
machine-readable reason. “Nothing happened” is not sufficient behavior for
either a human or an agent.

## 5. Main abstractions

### 5.1 Project

A `Project` is the compiled, versioned API exposed by a repository. It contains
named operations, reusable modules, profiles, trigger mappings, and metadata.
It is not a running process or a source checkout.

### 5.2 Operation and pipeline

An `Operation` is a public typed entry point such as `check`, `e2e`, or
`release`. Calling an operation with typed arguments produces a pipeline plan.
A `Pipeline` is the resulting immutable DAG plus its conditions, placement
requirements, source identity, and policy requests.

This distinction permits one operation to produce different concrete graphs
for an iOS or Android parameter without making graph construction depend on
ambient host state.

### 5.3 Node

A `Node` is the smallest independently schedulable unit. It has:

- a stable structural identity;
- typed input handles and typed output declarations;
- an execution profile and placement constraints;
- a serializable condition;
- resource and concurrency requirements;
- cache, retry, timeout, and effect policies;
- an executable runner invocation;
- no hidden Taskflow-level dependency edges.

The prototype's `flow.Step` is a useful comparison representation. The new
`Node` model may reuse its proven semantics, but it is not required to lower to
or remain compatible with that type.

### 5.4 Source and source view

`Source` is an immutable content-addressed tree. `SourceView` defines which
repository state becomes that tree:

- `Worktree`: tracked and selected untracked working files;
- `GitIndex`: the staged snapshot used by pre-commit;
- `GitRange`: commits/files being pushed or reviewed;
- `Commit`: an exact repository commit;
- `Tree`: an already materialized CAS tree.

The source view is part of run identity. A pre-commit pipeline must test the
staged index rather than accidentally testing unrelated unstaged edits.

### 5.5 Tree and artifact

`Tree` is an immutable filesystem value. `Artifact[T]` is an immutable output
with a project/domain type marker and a verified manifest.

Examples:

```go
type BackendBinary struct{}
type IOSApp struct{}
type SignedIOSApp struct{}

var backend flow.Artifact[BackendBinary]
var app flow.Artifact[IOSApp]
```

The marker prevents an iOS archive from being passed where an Android bundle
is expected. The underlying artifact handle contains its producer, manifest,
media type, metadata schema, and retention class.

### 5.6 Check and report

`Check` is a typed pass/fail result whose diagnostics remain inspectable.
`Report[T]` is a structured result such as unit tests, coverage, static
analysis, benchmarks, or an accessibility audit.

Checks are not represented only by process exit codes. A check can aggregate
child checks, expose diagnostics to an agent, and still retain artifact links.

### 5.7 Service and endpoint

`Service[T]` is a lazy, leased, health-checked process or group of processes.
`Endpoint[T]` is a typed capability to connect to it. A consumer receives an
endpoint rather than guessing a host port.

```go
type API struct{}
type Postgres struct{}

var database flow.Service[Postgres]
var endpoint flow.Endpoint[API]
```

Services start when first required, remain alive according to a lease/session
policy, and stop automatically. Endpoint allocation is namespace-aware, which
avoids fixed-port collisions between agents.

### 5.8 Stack

`Stack[T]` is a typed collection of related services, endpoints, volumes, and
cleanup leases. It is the primary abstraction for reproducing an application's
runtime environment per worktree.

A stack may span targets. For example, PostgreSQL and an API may run on remote
Linux while an iOS simulator test consumes the API endpoint from a macOS VM.

### 5.9 Secret

`Secret` is an opaque capability reference. Its value is resolved by the daemon
only after policy approval and delivered only to the authorized sandbox. The
value is not exposed in the plan, graph, cache manifest, journal, or module API.

The secret's version identity may participate in a cache key when an operation
explicitly declares that semantic dependency, without including the secret
value itself.

### 5.10 Effect

`Effect[T]` represents an external mutation such as deployment, publication,
signing, notification, or database migration. Effects are uncacheable by
default, require explicit policy, record idempotency and provenance, and are
visually distinct in plans.

### 5.11 Optional

`Optional[T]` represents a typed value that may not exist because its producing
branch was skipped. Conditional execution must not produce a normal artifact
handle that later fails mysteriously.

```go
var maybeRelease flow.Optional[flow.Artifact[SignedIOSApp]]
```

Consumers must use an operation such as `Map`, `Require`, or `OrElse`, making
the missing case explicit.

### 5.12 Execution profile

An `ExecutionProfile` is an immutable, content-addressed declaration of the
environment required by a node. It can identify:

- OS and architecture;
- base image, VM image, snapshot, or native host class;
- toolchain builds and system packages;
- environment policy;
- sandbox and isolation level;
- network and clock policy;
- required worker features;
- compatibility and profile schema versions.

Profiles are known before target acquisition. A worker attests the actual
profile on admission; mismatch is an error, not a silent cache-key change.

### 5.13 Worker and sandbox

A `Worker` is reusable execution capacity: the local host, a remote machine, a
warm VM, or a device host. A `Sandbox` is the disposable node workspace created
on a worker from immutable source and dependency artifacts.

This split replaces the current `target.Environment` concept, which combines
capacity, workspace, identity, execution, transfer, and cleanup.

### 5.14 Placement group and session

A placement group expresses affinity: several nodes should use the same worker
class or worker when beneficial. A session expresses intentional mutable
lifetime: a simulator, server, or stateful tool must persist across nodes.

Affinity alone must not imply shared mutable state. This distinction avoids
turning performance hints into undeclared semantic dependencies.

### 5.15 Namespace and lease

Every run belongs to a namespace, normally derived from project, worktree, and
agent identity. A namespace owns mutable stacks, volumes, endpoint mappings,
device/simulator leases, and temporary credentials. Leases have owners,
heartbeats, deadlines, TTLs, and cleanup behavior.

Only immutable CAS objects, immutable images, and explicitly safe tool caches
may be shared across namespaces.

## 6. Proposed authoring experience

The APIs in this section are illustrative. Their purpose is to define the
desired ergonomics and type relationships; their exact Go signatures require a
prototype before becoming public contracts.

### 6.1 Project entry point

```go
package main

import (
    "github.com/arr/taskflow/flow"
    "myproject/automation/app"
)

func main() {
    flow.Main(flow.Project("myproject",
        flow.Expose("check", app.Check),
        flow.Expose("e2e", app.E2E),
        flow.Expose("release", app.Release),
    ))
}
```

The operation signatures become the public schema. Documentation, defaults,
enums, validation, permissions, and examples should be expressible through Go
types and lightweight annotations rather than a parallel YAML definition.

### 6.2 Concise project operations

```go
type E2EInput struct {
    Platform app.Platform `flow:"default=ios"`
}

func Check(ctx flow.Context) flow.Check {
    src := ctx.Source()
    return flow.All(
        app.Backend.Check(src),
        app.Mobile.Check(src),
    )
}

func E2E(ctx flow.Context, in E2EInput) flow.Report[app.E2E] {
    src := ctx.Source()
    stack := app.TestStack(src)
    return app.Mobile.E2E(src, in.Platform, stack.API())
}
```

The visible code says what the project does. The module can hide that the API
runs on Linux, iOS tests require a macOS VM and simulator lease, source is
filtered, reports are collected, and the stack is cleaned up.

### 6.3 Reusable typed module

```go
package backend

type Module struct {
    Go flow.Module[GoToolchain]
}

func (m Module) Build(src flow.Source) flow.Artifact[BackendBinary] {
    return m.Go.Build(src.Dir("backend"), flow.GoBuild{
        Package: "./cmd/api",
        Output:  "bin/api",
    })
}

func (m Module) Check(src flow.Source) flow.Check {
    code := src.Select(
        "backend/**/*.go",
        "backend/go.mod",
        "backend/go.sum",
    )
    return flow.All(
        m.Go.Test(code),
        m.Go.Vet(code),
    )
}
```

The language module defines pinned Go profile identity, module caches, network
rules for dependency resolution, result artifacts, and report parsers. The
project module chooses only project semantics.

### 6.4 Low-level escape hatch

Not every tool deserves a dedicated module immediately. The typed facade can
lower to the current invocation model:

```go
func LicenseCheck(ctx flow.Context, src flow.Source) flow.Check {
    return flow.Task[flow.Check](ctx, "license-check",
        command.Run("./scripts/check-licenses"),
        flow.Uses(src.Select("go.mod", "go.sum", "LICENSE")),
        flow.Profile(profiles.LinuxTools),
        flow.Cache(flow.ReadWrite, "v1"),
    )
}
```

This is intentionally more explicit. Most project code should use a domain or
tool module instead.

### 6.5 Taskfile migration

```go
func BackendTests(ctx flow.Context, src flow.Source) flow.Report[GoTests] {
    return flow.Task[flow.Report[GoTests]](ctx, "backend-tests",
        taskfile.Run("be:test:leaf"),
        flow.Uses(src.Select("backend/**")),
        flow.Produces("backend/build/test-results/**"),
        flow.Profile(profiles.LinuxGo),
    )
}
```

`be:test:leaf` must not also invoke dependencies that Taskflow has modeled as
nodes. Aggregate Task tasks can remain opaque during initial adoption; they are
split only when Taskflow-level behavior is valuable.

### 6.6 Typed services and native mobile tests

```go
func MobileE2E(
    ctx flow.Context,
    src flow.Source,
) flow.Report[MobileE2E] {
    stack := app.TestStack(src)
    build := app.IOS.Build(src)

    return app.IOS.Test(build,
        flow.Device(ios.Simulator{
            Runtime: "iOS 20",
            Model:   "iPhone 17 Pro",
        }),
        flow.Connect(stack.API()),
    )
}
```

The typed `Endpoint[API]` makes network wiring explicit. The scheduler may
place the stack on remote Linux and the test on a macOS worker, allocate a
private route, create or reset a simulator, and tear everything down when the
namespace lease ends.

### 6.7 Conditional release

```go
func Release(
    ctx flow.Context,
    in ReleaseInput,
) flow.Optional[flow.Effect[PublishedRelease]] {
    app := mobile.Archive(ctx.Source())

    return flow.When(
        flow.AllOf(
            flow.Branch("main"),
            flow.Event(flow.Push, flow.Manual),
            flow.Input(in.Publish),
        ),
        func() flow.Effect[PublishedRelease] {
            signed := mobile.Sign(app, flow.Secret("app-store-signing"))
            return mobile.Publish(signed, in.Channel)
        },
    )
}
```

`flow.When` builds a conditional branch and returns an optional typed value.
The callback is graph construction, not arbitrary condition evaluation; the
predicate itself compiles to serializable condition IR.

### 6.8 Failure handling and cleanup

```go
tests := app.E2E(ctx.Source(), stack.API())

flow.When(flow.Failed(tests), func() flow.Effect[Notification] {
    return notify.Agent(tests.Diagnostics())
})

flow.Finally(stack, func() flow.Check {
    return stack.CollectDiagnostics()
})
```

Normal typed dependencies are success-only. `Failed` observes an outcome.
`Finally` is an engine-managed, bounded cleanup/finalization region that still
runs during cancellation but cannot run indefinitely.

## 7. Typed schema and agent API

Compile-time Go typing is necessary but insufficient for agents. The compiled
project driver must emit a versioned, machine-readable schema without running
the pipeline.

### 7.1 Discovery

`taskflow api --json` returns:

- project and protocol versions;
- operations and descriptions;
- argument names, scalar types, enums, defaults, validation, and examples;
- typed result shapes;
- requested capability classes;
- whether an operation may produce effects;
- deprecation and compatibility metadata.

Illustrative response:

```json
{
  "schema": 1,
  "project": "myproject",
  "operations": [{
    "name": "e2e",
    "arguments": [{
      "name": "platform",
      "type": "Platform",
      "enum": ["ios", "android"],
      "default": "ios"
    }],
    "returns": "Report[MobileE2E]",
    "effects": false
  }]
}
```

### 7.2 Planning

`taskflow plan` resolves the source view, validates inputs, expands the graph,
evaluates planning conditions, calculates known cache identities, performs
policy preflight, and reports unresolved runtime decisions. It must not acquire
a worker or reveal a secret.

A node in the plan includes:

- stable node ID and display label;
- typed inputs and outputs;
- dependencies and conditional dependencies;
- condition IR and current evaluation with evidence;
- execution profile digest and placement requirements;
- resource, service, session, and concurrency requirements;
- cache eligibility, key readiness, and explanation;
- requested network, secret, device, and effect capabilities;
- whether execution can be local, remote, or either.

### 7.3 Run lifecycle

Commands return stable handles and structured errors:

```text
run -> {run_id, namespace_id, plan_digest, status, watch_cursor}
watch -> ordered JSONL events with monotonic sequence numbers
status -> durable run/node/service/lease snapshot
cancel -> accepted cancellation and cleanup deadline
resume -> compatibility decision and reset explanation
```

Agents should never need to scrape terminal animation or infer success from a
missing process. Human output and JSON output are separate renderers of the
same event stream.

### 7.4 Idempotency and attachment

Run creation accepts an idempotency key. If an authorized caller requests an
identical project, source, operation, arguments, and plan while it is already
running, policy may attach the caller to the existing run. Completed work is
normally reused at node/artifact level through the result cache rather than by
pretending a historical run is a new run.

## 8. Conditions and triggers

Taskflow should separate three concepts that are often conflated in CI YAML.

### 8.1 Triggers

Triggers decide whether to create a run and which source view and event facts
it receives.

Initial triggers:

- manual CLI;
- coding agent;
- Git hook via Lefthook;
- push and pull request adapter;
- scheduled/cron adapter;
- generic signed webhook.

Triggers produce normalized typed facts such as event kind, repository, ref,
commit, changed paths, actor, trust class, and requested operation. Raw event
payloads remain available only through a typed, versioned adapter.

### 8.2 Planning conditions

Planning conditions depend only on immutable known facts:

- branch, tag, or event kind;
- changed paths in the selected source view;
- operation arguments;
- repository or trust class;
- declared feature flags.

They can be evaluated before provisioning and should prune work early.

### 8.3 Outcome conditions

Outcome conditions depend on durable node state:

- `Succeeded(value)`;
- `Failed(value)`;
- `Cancelled(value)`;
- `Skipped(value)`;
- `Completed(value)` or `After(value)`.

A normal typed data dependency implies `Succeeded`. `After` waits for terminal
state without asserting success.

### 8.4 Serializable condition IR

Conditions use typed constructors but compile to a small IR:

```json
{
  "op": "all",
  "args": [
    {"op": "branch", "matches": "main"},
    {"op": "changed", "patterns": ["mobile/**"]},
    {"op": "input", "name": "publish", "equals": true}
  ]
}
```

Arbitrary closures, shell commands, current time, and undeclared host reads are
not condition primitives. This makes plans portable, digests stable, and
resume deterministic.

### 8.5 Three-valued evaluation

A condition evaluates to `true`, `false`, or `unknown` with evidence.

- `true`: run when dependencies permit;
- `false`: persist `skipped` and its reason;
- `unknown`: run by default for ordinary validation work, because an unsafe
  skip is worse than extra work.

Effects may choose a stricter policy: unknown authorization or release
conditions fail closed rather than run.

### 8.6 Skip semantics

`skipped` is a distinct durable state, not success. Aggregation and downstream
conditions can decide whether a skip is acceptable. A conditional producer
returns `Optional[T]`, preventing absent outputs from masquerading as normal
artifacts.

### 8.7 Concurrency conditions

Taskflow supports serializable concurrency keys and policies:

```go
flow.Concurrency(
    flow.Key("deploy", flow.InputRef("environment")),
    flow.QueueNewest,
)
```

Policies may queue all, keep only the newest pending run, or cancel superseded
runs. Destructive effects should generally queue rather than silently replace
an active operation.

## 9. System architecture

### 9.1 Component model

```text
human / agent / hook / CI event
              |
              v
       CLI and trigger adapters
              |
              v
  sandboxed compiled project driver
        | schema + plan IR
        v
          taskflowd control plane
  +-----------------------------------+
  | planner and policy engine         |
  | durable scheduler and run journal |
  | namespace, lease, service manager |
  | cache and artifact coordinator    |
  | provider and worker manager       |
  | event/log stream                  |
  +-----------------------------------+
       |          |          |
       v          v          v
 local worker  Linux pool  macOS/device pool
       |          |          |
       +---- disposable sandboxes ----+
                       |
                       v
             artifacts, reports, effects
```

### 9.2 Project driver

ADR 0001 remains: pipeline definitions are compiled Go. The generic CLI hashes
and caches the repository's `.taskflow` driver and communicates through a
versioned protocol.

For agent-first execution, the driver is a planning component, not a privileged
daemon extension. It must run in a restricted planning sandbox because compiled
Go project code is arbitrary code. It receives source metadata and declared
arguments, emits schema/plan IR, and receives no daemon credentials, target
credentials, signing secrets, or unrestricted filesystem access.

The daemon never loads project Go code into its own process.

### 9.3 Planner

The planner:

1. validates operation arguments;
2. resolves an immutable source snapshot;
3. expands typed values into kernel nodes;
4. infers edges from value handles;
5. validates explicit edges and detects cycles;
6. evaluates planning conditions;
7. resolves execution profile digests;
8. computes cache keys that are ready before execution;
9. requests policy authorization;
10. persists an immutable plan and plan digest.

The plan is the boundary between unprivileged project intent and privileged
execution.

### 9.4 Durable scheduler

The prototype proved the value of an explicit scheduler state machine. The new
shared scheduler should retain that semantic property while being implemented
cleanly around the accepted plan IR. It owns graph state but remains unaware of
Taskfile syntax or provider internals.

Required states include:

```text
pending -> ready -> admitted -> running -> succeeded
   |         |          |          |          |
   |         |          |          |          +-> cleanup warning
   |         |          |          +-> retry_wait -> ready
   |         |          +-> capacity_wait
   |         +-> skipped
   +-> blocked / cancelled / failed
```

Every eligibility-changing transition is durable before downstream work is
scheduled. Provider saturation consumes no global execution slot.

### 9.5 Global scheduling

`taskflowd` arbitrates all runs rather than letting each CLI enforce an
independent `--max-parallel` value. It accounts for:

- CPU, memory, disk, GPU, and provider capacity;
- scarce simulators, emulators, devices, and signing slots;
- per-project, namespace, agent, and trust-class quotas;
- fair sharing and starvation prevention;
- placement affinity and stateful sessions;
- concurrency keys and supersession policies.

An interactive local check may receive latency preference without permanently
starving background agent runs.

### 9.6 State store

The prototype's revisioned append-only transition journal is retained as a
correctness model, not necessarily as reused code. A shared implementation must
provide:

- exclusive run ownership or distributed compare-and-swap;
- monotonic revisions and event sequence numbers;
- atomic transition visibility;
- schema-version rejection or explicit migration;
- recoverable service and lease state;
- auditable policy and effect decisions.

SQLite is a reasonable first daemon store for one machine. A networked store
is needed only when multiple controllers must schedule the same fleet.

### 9.7 Provider manager

Providers publish locally cached capability and capacity snapshots. Admission
is non-blocking. Slow discovery, VM creation, or device probing happens outside
the scheduler's critical path.

Provider-specific concerns remain in provider packages. A universal bag of
options would weaken validation and make cache identity ambiguous.

## 10. Reproducibility without mandatory containers

### 10.1 Definition

For Taskflow, a reproducible node has enough declared and verified identity to
answer:

1. What immutable source and dependency artifacts entered it?
2. What implementation and arguments ran?
3. What execution profile supplied tools and system behavior?
4. What environment, secrets, network, clock, and capabilities were visible?
5. What outputs and diagnostics were produced?
6. Can the same contract be reconstructed or a compatible cache result be
   trusted?

A container image can answer part of question 3 and help enforce questions 1
and 4. It does not by itself pin source, forbid network, sanitize environment,
declare outputs, remove timestamps, or make external services deterministic.

### 10.2 Reproducibility levels

Taskflow should label the effective contract rather than claim universal
hermeticity:

| Level | Guarantee |
| --- | --- |
| `observed` | Runs in a mutable workspace; relevant target/tool versions are probed and recorded. This resembles the current local mode. |
| `isolated` | Immutable source, clean sandbox, declared inputs/outputs, sanitized environment, and no cross-run mutable workspace. |
| `reproducible` | `isolated` plus pinned execution profile, controlled capabilities, dependency locks, and verified artifact provenance. |
| `hermetic` | `reproducible` plus no undeclared network/host access, fully declared tools/dependencies, and controlled nondeterministic inputs such as time and randomness. |

The plan and result report the requested and attained level. A provider must
not silently downgrade it.

### 10.3 Immutable source snapshot

The controller snapshots the selected source view once into a Merkle tree/CAS.
Every node sees the same logical tree, filtered by declared selection. Remote
workers receive missing blobs only. The source cannot change under a running
pipeline even if the developer edits the worktree.

This replaces the prototype behavior of capturing a live workspace during each
target acquisition.

### 10.4 Pinned execution profiles

Examples:

- Linux root filesystem or OCI image by digest;
- macOS VM base image by digest plus OS build, Xcode build, SDK inventory, and
  runner version;
- native local profile with exact toolchain lock and an explicit lower
  reproducibility level;
- Android emulator system image and emulator build;
- physical device model, OS build, provisioning class, and reset policy.

A logical profile name such as `macos-xcode-20` resolves to an immutable digest
in the plan. Mutating what the name points to produces a new digest.

### 10.5 Disposable sandboxes on warm workers

Provisioning performance comes from reusing capacity while discarding semantic
state:

- Linux: namespaces plus overlayfs, bubblewrap, or a provider sandbox rooted in
  an immutable filesystem;
- macOS: a warm clean VM with APFS copy-on-write workspaces or fast VM snapshot
  reset;
- remote bare metal: provider-managed workspace clones with filesystem and
  process isolation;
- simulator/emulator: reset or clone from a known state and bind it to a
  session lease.

Booting a VM is a pool-management event, not a normal node event. A worker can
execute many isolated nodes sequentially or concurrently if its isolation and
resources permit.

### 10.6 Controlled ambient inputs

Each sandbox starts with a minimal deterministic environment. Locale, timezone,
home directory, temporary paths, umask, proxy settings, and inherited variables
are profile-controlled. A node explicitly requests additional environment keys.

Network defaults should be profile-specific:

- build/test profiles prefer denied or allowlisted egress;
- dependency-fetch nodes may use locked registries and publish immutable
  dependency artifacts;
- services use explicit typed endpoints;
- deployment effects use policy-approved destinations.

Time, randomness, hardware features, and host sockets are declared capabilities
when they can affect correctness.

### 10.7 Cache identity

The proposed cache key includes:

```text
cache schema version
project + operation + node structural identity
resolved runner implementation and arguments
typed input artifact/tree manifests
source selection and content digest
dependency artifact manifests
execution profile digest
sandbox policy digest
declared environment identities
declared secret version identities, when applicable
network/service dependency identities
declared output schema
explicit module/user cache version
```

Descriptions, retry counts, log verbosity, and target instance IDs do not alter
result identity unless they change execution semantics.

### 10.8 Cache before provisioning

The prototype runtime acquires and probes an environment before it can finish
the cache key. The new architecture resolves the immutable execution profile in
the plan, so the cache coordinator can look up a result before reserving or
provisioning a worker.

Execution sequence:

```text
resolve plan and profile digest
          |
          v
compute result cache key
     | hit          | miss
     v              v
return artifact   reserve worker
handles           attest profile
                  create sandbox
                  execute and publish
```

If a worker cannot attest the planned profile, the node fails placement and the
worker is quarantined or refreshed. Its unexpected identity must not quietly
turn a planned cache hit into a miss.

### 10.9 Three different caches

Taskflow must not conflate:

1. **Result cache:** immutable, content-addressed node outputs safe to reuse
   across compatible runs.
2. **Tool cache:** mutable performance state such as Go build cache, Gradle
   cache, or package download cache. It is namespaced by profile/tool identity,
   may be poisoned, and never proves node success.
3. **Warm provider state:** booted VMs, downloaded base images, ready
   simulators, or provider checkpoints. It reduces startup latency but has no
   semantic authority.

### 10.10 Provenance

Every artifact records source digest, plan/node digest, profile digest, input
manifests, producer run, timestamp, and attained reproducibility level. Effects
record the exact artifact and policy decision they consumed.

Signed or notarized artifacts may differ byte-for-byte across invocations. The
provenance should distinguish deterministic build content from the authorized
nondeterministic signing/notarization envelope.

## 11. Target and sandbox architecture

### 11.1 Proposed provider contract shape

```go
type Provider interface {
    Name() string
    Profiles(context.Context) ([]ExecutionProfile, error)
    Capabilities(context.Context) (Capabilities, error)
    TryReserve(context.Context, Request) (Reservation, bool, error)
}

type Reservation interface {
    AcquireWorker(context.Context) (Worker, error)
    Release()
}

type Worker interface {
    Attest(context.Context, ProfileDigest) (Attestation, error)
    CreateSandbox(context.Context, SandboxSpec) (Sandbox, error)
    Release(context.Context) error
}

type Sandbox interface {
    Exec(context.Context, process.Spec, process.IO) (process.Result, error)
    Export(context.Context, OutputSpec) (flow.Tree, error)
    Destroy(context.Context) error
}
```

The exact interface may differ, but profile identity, reusable capacity, and
disposable workspace must be separate concepts.

### 11.2 Local provider

Local remains the lowest-latency path. It should offer explicit modes:

- `workspace`: current ergonomic live-checkout behavior, reported as
  `observed`;
- `sandbox`: immutable source plus isolated local workspace;
- `host`: intentional access to host capabilities for trusted effects.

The default should move toward `sandbox` once performance and compatibility are
proven. A user can opt into `workspace` for an interactive command that truly
needs it.

### 11.3 Remote Linux provider

The first production remote provider should validate:

- profile resolution before acquisition;
- source/CAS delta transfer;
- warm worker reuse and disposable sandboxes;
- log streaming and cancellation;
- network and secret injection;
- result publication and cache-before-provision behavior;
- reconnection and orphan cleanup.

Fly Sprites, a VM pool, or another provider can implement this contract. The
provider choice should not change project modules.

### 11.4 macOS and Xcode provider

Native Apple builds require macOS and licensed Xcode installations; a Linux
container engine is not an adequate abstraction. A Tart/Orchard-style provider
can use:

- immutable OCI-distributed macOS base images;
- warm VMs restored from clean snapshots;
- APFS copy-on-write node workspaces;
- exact macOS, Xcode, SDK, simulator runtime, and runner attestation;
- explicit simulator/session leases;
- host-level capacity and cleanup managed outside pipeline code.

The target profile identifies the VM image, while the sandbox identifies the
disposable workspace and simulator state. Multiple nodes can share a declared
session without sharing an undeclared checkout.

### 11.5 Android emulators and physical devices

Devices are finite resources, not ordinary CPU slots. Providers expose typed
capabilities and reset guarantees. A device lease includes model, OS/API level,
state policy, connection path, exclusivity, health, and cleanup.

Tests that require a physical device may attain `reproducible` provenance but
not full hermeticity because hardware behavior is an explicit external input.

### 11.6 Per-node remote placement

Placement is attached to the node through profiles and requirements, not to the
entire pipeline. A graph can therefore execute:

```text
Linux compile -----> immutable API binary -----+
                                              |
Linux stack -------> Endpoint[API] ------------+--> macOS iOS test
                                              |
Android build -----> Artifact[APK] ------------+--> device test
```

Typed handles ensure that every cross-target dependency is transferred or
routed explicitly.

## 12. Agent-first execution and worktree isolation

### 12.1 Shared daemon

A persistent per-user `taskflowd` is the default control plane. It avoids
starting a scheduler per CLI and owns:

- all run and node state;
- global capacity and fair scheduling;
- worker and VM pools;
- artifact CAS and retention;
- service, endpoint, port, volume, simulator, and device leases;
- secret and policy mediation;
- structured logs and event cursors;
- TTL cleanup after crashed or abandoned agents.

The daemon can run entirely on the developer machine while dispatching work to
remote providers.

### 12.2 Namespace model

A default namespace key is derived from:

```text
user / project identity / worktree identity / agent identity
```

It owns:

- immutable source snapshots and pipeline runs;
- private service stacks and mutable volumes;
- endpoint names and host-port mappings;
- simulator, emulator, and device leases;
- temporary credentials and effect approvals;
- cleanup and retention policy.

Worktree paths are never assumed to be globally unique identity. Repository
identity plus source snapshot and a generated namespace ID are durable.

### 12.3 Sharing rules

Safe to share:

- immutable source blobs and trees;
- immutable result artifacts;
- pinned base images;
- read-only dependency stores;
- appropriately partitioned tool caches;
- idle worker capacity.

Not safe to share by default:

- writable application workspaces;
- databases and Redis keyspaces;
- fixed host ports;
- simulator/emulator mutable state;
- signing key material;
- deployment credentials;
- long-running development servers.

### 12.4 Full-stack per agent

An agent requests a typed stack, not a hand-authored Compose project name and
port range. Taskflow allocates namespace-specific names, volumes, endpoints,
routes, and leases. The stack starts lazily and can be retained briefly for
iterative test runs under a TTL.

If a source change does not affect the stack definition or image artifacts,
Taskflow may reuse immutable service images and restart a private stack quickly.
It must not attach the agent to another namespace's mutable database merely
because definitions match.

### 12.5 Agent permissions

Agent-authored pipeline code may request capabilities but cannot authorize
itself. Policy can distinguish:

- trusted repository code versus uncommitted agent modifications;
- read-only checks versus effects;
- ordinary secrets versus signing/deployment secrets;
- local sandbox, remote pool, macOS, device, and production access;
- network destinations and resource quotas.

Plans show denied or approval-required capabilities before execution.

### 12.6 Agent ergonomics requirements

- Every command has stable JSON output and structured error codes.
- Discovery does not require executing a pipeline.
- Planning does not provision infrastructure.
- Runs can detach and survive the initiating process.
- Logs can resume from a cursor.
- Cancellation is idempotent and includes cleanup state.
- Artifact and report handles are fetchable through declared APIs.
- The system reports whether work ran, hit cache, attached, queued, skipped, or
  was denied.
- Namespaces have TTLs and explicit retain/release controls.

## 13. Services, networks, and state

### 13.1 Lazy service graph

A service definition is part of the graph but is not started until a consumer
becomes runnable. Health checks are typed configuration, and readiness is a
durable service transition rather than an arbitrary sleep in a test script.

### 13.2 Endpoint routing

The service manager resolves typed endpoints into target-specific connection
details:

- local Unix socket or loopback port;
- namespace-private remote network name;
- authenticated tunnel between Linux and macOS workers;
- temporary developer preview URL when explicitly requested.

Consumers receive injected connection data. Canonical service identity does not
depend on whichever host port happened to be available.

### 13.3 Stateful sessions

Mutable state is permitted only through explicit session values. Examples:

- database volume retained for one stack lease;
- booted simulator reused across build/install/test nodes;
- development server retained while an agent iterates;
- Xcode derived-data cache partitioned by profile and project.

Sessions are never result cache entries. They have ownership, reset guarantees,
and expiry.

### 13.4 Cleanup

Cleanup runs on a cancellation-detached, deadline-bounded context. The engine
persists cleanup progress. A successful node followed by cleanup failure stays
successful but produces a warning and orphan record for the reaper. Effects may
define stricter cleanup/finalization semantics.

## 14. Caching, artifacts, resume, and retries

### 14.1 Result cache versus run state

Run state answers what happened in one run. The result cache answers whether an
equivalent node already produced reusable outputs. They remain separate.

### 14.2 Declared outputs

Only declared outputs cross node or target boundaries. Output collection
creates deterministic archives or Merkle trees, validates paths and symlinks,
records a manifest, and publishes atomically. A downstream node materializes
the precise dependency handle rather than a previous node's whole workspace.

### 14.3 Cache-off artifacts

An uncacheable node may still publish a run-scoped immutable artifact so that
downstream remote nodes and resume work correctly. It is not eligible for
cross-run result reuse.

### 14.4 Cache explanation

For every cacheable node, `plan` and `status` identify:

- the key components already known;
- why the key is incomplete, if applicable;
- hit, miss, bypass, or corrupt-entry outcome;
- which identity component changed from a comparable prior result;
- whether policy disallowed reuse.

### 14.5 Resume

Resume uses the persisted plan and structural digest. A previously successful
node remains successful only if its required output manifests remain valid.
Running, failed, blocked, or lost nodes reset to pending; successful dependents
reset transitively when necessary.

The future typed plan must include conditions, profiles, value schemas, and
effect identities in structural compatibility. Cosmetic descriptions and retry
tuning remain outside structural identity where safe.

### 14.6 Retries

Retries are node-level and durable. The scheduler persists attempt count and
backoff. By default:

- checks may retry only explicitly classified transient failures;
- sandbox/transport failures can use provider policy;
- effects do not retry unless they declare an idempotency key and safe retry
  contract;
- Cloud or provider APIs returning an uncertain outcome require reconciliation
  before another mutation.

## 15. Security model

### 15.1 Trust boundaries

The system separates:

1. project planning code;
2. daemon control plane;
3. provider credentials and fleet APIs;
4. sandboxed task code;
5. secret stores;
6. external effect targets;
7. artifact and state storage.

The compiled driver and executed commands are project code, not automatically
trusted merely because they are typed.

### 15.2 Planning safety

Agent-first mode evaluates the project driver without privileged credentials in
a restricted sandbox. The daemon validates plan IR limits, schemas, paths,
resource requests, and capability requests. It signs or binds the accepted plan
digest to the run.

### 15.3 Secrets

- Secret values never enter authored definitions or serialized plans.
- The daemon resolves a secret only after node authorization.
- Providers receive the minimum secret set for one sandbox.
- Delivery prefers ephemeral memory-backed files or provider-native secret
  injection.
- Logs are redacted before persistence and streaming.
- Cache and artifact content is scanned or constrained to prevent accidental
  secret publication.

### 15.4 Network

Network is a capability with direction and destination policy. Untrusted pull
request or agent code cannot request arbitrary internal access. Service
endpoints are authorized independently from Internet egress.

### 15.5 Effects and supply chain

Effects bind exact input artifact manifests, source and plan digests, actor,
policy decision, target environment, and idempotency key. Signing and publishing
should occur on trusted profiles, and attestations should be exportable in
standard provenance formats where practical.

### 15.6 Resource abuse

The daemon applies quotas, timeouts, output limits, log limits, namespace TTLs,
and provider-specific budgets. Agents cannot create infinite services or retain
scarce devices indefinitely.

## 16. Taskfile, Just, and Lefthook integration

### 16.1 Taskfile and Just

Taskflow should absorb their orchestration role incrementally, not reimplement
their recipe languages.

Taskflow owns:

- typed edges and values;
- target placement and remote transfer;
- result caching and artifacts;
- retries, resume, conditions, and services;
- agent discovery and global scheduling.

Taskfile/Just may continue to own:

- convenient shell command recipes;
- local variables and templating;
- includes and task aliases;
- developer-only helper commands;
- opaque aggregates that have not yet been migrated.

Migration rule: when a nested recipe needs Taskflow visibility or independent
behavior, move that edge into Taskflow and make the recipe a dependency-free
leaf.

### 16.2 Lefthook

Lefthook remains responsible for installing and invoking Git hooks. Taskflow
owns the pipeline and conditions:

```text
Git hook -> Lefthook -> taskflow trigger git:pre-commit -> taskflowd
```

Minimal configuration:

```yaml
pre-commit:
  jobs:
    - name: taskflow
      run: taskflow trigger git:pre-commit
```

Taskflow receives the event-specific source view. Conditions such as changed
paths or branch rules live in Taskflow so a manual run, agent run, and hook run
cannot silently select different validation logic.

Useful Lefthook ideas to retain in Taskflow's trigger model include fast no-op
behavior, staged/pushed file views, branch/rebase/merge facts, globs and
excludes, tags, local hook configuration, and fail-on-generated-changes checks.

## 17. Observability and user experience

### 17.1 Terminal

The terminal remains the primary human UI. Output is line-oriented and works
without a full-screen renderer.

- `quiet`: failures and final result;
- `normal`: node start/finish and summary;
- `verbose`: placement, cache, retries, service lifecycle, and commands;
- `trace`: scheduler, transfer, policy, and provider diagnostics.

### 17.2 Structured events

Every event follows the durable transition that made it true and includes run,
namespace, plan, node/service/lease identity, sequence number, time, and typed
payload. Slow telemetry consumers stay off the scheduling path.

### 17.3 Explain commands

```sh
taskflow explain cache RUN_ID NODE
taskflow explain skip RUN_ID NODE
taskflow explain placement RUN_ID NODE
taskflow explain resume RUN_ID
taskflow explain policy RUN_ID NODE
```

Each supports human and JSON renderers.

### 17.4 Future visualization

A web or terminal graph viewer may consume the same plan and event APIs later.
It is not required for the initial agent-first daemon, but the protocol must not
assume a terminal is the only client.

## 18. Module and extension model

### 18.1 Language strategy

Decision:

> Taskflow's engine, daemon, CLI, workers, providers, and first authoring SDK
> are implemented in Go. Project schema, plan IR, condition IR, daemon RPC,
> worker protocol, events, and artifact manifests are language-neutral
> versioned contracts.

This extends rather than replaces ADR 0001. Compiled Go remains the first and
default pipeline-authoring experience. The daemon must nevertheless execute an
accepted plan rather than depend directly on Go types or load project Go code
into its process.

```text
Go project SDK ---------+
                       |
future TypeScript SDK --+--> project schema + plan IR --> taskflowd
                       |
future SDK ------------+
```

Go is the strongest current choice for the operational core because Taskflow
needs:

- small native binaries without a separately installed runtime;
- efficient long-running daemon and worker processes;
- concurrency for scheduling, leases, process supervision, and log streaming;
- mature filesystem, process, archive, HTTP, RPC, SSH, and observability
  support;
- straightforward Linux and macOS distribution;
- fast builds for cached project drivers;
- one language shared by the prototype evidence and the initial public SDK.

The principal risk is authoring ergonomics, not engine capability. Go lacks
some features that make embedded DSLs especially concise: algebraic data types,
function overloading, decorators, rich compile-time reflection, and
Kotlin-style builders. A low-level API dominated by generic parameters and
functional options would be type-safe without feeling natural.

Taskflow mitigates this by making ordinary project operations small and moving
infrastructure options into reusable modules:

```go
func Check(ctx flow.Context) flow.Check {
    return flow.All(
        app.Backend.Check(ctx.Source()),
        app.Mobile.Check(ctx.Source()),
    )
}
```

The first typed API prototype must therefore validate Go as an authoring
language using real operations, not merely prove that generic handles compile.
It should measure:

- how much low-level option configuration leaks into project code;
- whether `Artifact[T]`, `Optional[T]`, `Service[T]`, and `Effect[T]` compose
  naturally;
- whether operation schemas can be produced reliably and explained clearly;
- whether agents can generate, inspect, and modify definitions successfully;
- whether project-driver compilation is effectively invisible;
- whether diagnostics point back to understandable authored code.

If those tests fail, the correct response is not to rewrite the scheduler. The
Go engine should remain while another SDK, most plausibly TypeScript, emits the
same language-neutral plan IR.

Alternative choices have different strengths:

| Language | Operational core | Pipeline authoring | Primary tradeoff for Taskflow |
| --- | --- | --- | --- |
| Go | Excellent | Good if modules hide infrastructure | Embedded DSL can become option-heavy |
| Rust | Excellent | Moderate to difficult | Higher implementation complexity without a clear orchestration benefit |
| TypeScript | Moderate | Excellent | Runtime/toolchain dependency and weaker native binary deployment |
| Kotlin | Good | Excellent | JVM distribution, memory, and startup cost |
| Python | Moderate | Approachable | Weaker static contracts and environment reproducibility |
| Starlark | Good for deterministic planning | Moderate | Creates a bespoke workflow language and ecosystem |

No second authoring SDK should be started until the Go vertical slice has
stabilized operation schema, value semantics, and plan IR. Multiple SDKs before
that point would multiply ambiguity rather than improve accessibility.

### 18.2 Go modules

Extensions remain ordinary versioned Go modules linked into the project
driver. A module can provide typed operations, profiles, runner adapters,
provider configuration types, report parsers, and schemas.

### 18.3 Module design requirements

A public module should:

- expose domain values rather than raw paths where possible;
- provide machine-readable descriptions and examples;
- make required capabilities explicit;
- pin or accept an explicit execution profile;
- declare source selections and outputs;
- avoid ambient environment reads during graph construction;
- version output schemas and cache semantics;
- mark effects and secrets explicitly;
- provide plan-level validation without acquiring a worker.

### 18.4 Kernel API

The isolated prototype packages provide useful evidence about boundaries:

- `flow`: kernel DAG, validation, and structural identity;
- `runner`: structured invocation resolution;
- `target`: provider admission and execution lifecycle;
- `engine`: durable scheduling and runtime;
- `state`: journal/lease contract;
- `cache` and `workspace`: identity, CAS, and safe transfer;
- `driver`: compiled project protocol;
- `event` and `terminal`: lifecycle stream and presentation.

Proposed packages can grow around them:

```text
api/             typed Project, Operation, and schema model
value/           Source, Tree, Artifact, Check, Report, Optional
condition/       typed predicates and serializable IR
plan/            immutable plan IR and lowering to flow.Step
profile/         execution and sandbox profiles
service/         Service, Endpoint, Stack, session lifecycle
policy/          capability requests and authorization decisions
daemon/          RPC API, global scheduling, namespaces, leases
worker/          Worker and Sandbox contracts
provider/...     local, Linux, Sprite, Orchard, device implementations
```

Package names are provisional. New product code must not import the isolated
prototype. Boundaries are reimplemented only after the risk-first roadmap's
experiments and decision gates validate them.

### 18.5 Protocol versioning

Project schema, plan IR, daemon RPC, state journal, cache key, artifact manifest,
provider contract, and event stream require independent versions. Before v1,
incompatible versions should fail clearly rather than silently downgrade.

## 19. Product requirements

### 19.1 Authoring and types

- **TYPE-1:** Public operations use typed arguments and return typed graph
  values.
- **TYPE-2:** Passing a produced value infers a dependency edge.
- **TYPE-3:** Conditional producers return optional values.
- **TYPE-4:** Effects, secrets, services, endpoints, artifacts, and reports are
  distinct types.
- **TYPE-5:** The low-level kernel remains available without being required for
  ordinary project operations.
- **TYPE-6:** The Go SDK lowers to a language-neutral project schema and plan IR;
  Go-specific runtime values do not cross the daemon execution boundary.

### 19.2 Discovery and planning

- **PLAN-1:** Projects emit a versioned operation schema as JSON.
- **PLAN-2:** Planning performs no worker acquisition or secret resolution.
- **PLAN-3:** Plans are immutable, digestible, serializable, and explainable.
- **PLAN-4:** Conditions compile to IR and never depend on undeclared ambient
  state.
- **PLAN-5:** Policy preflight identifies denied and approval-required
  capabilities.

### 19.3 Execution and placement

- **EXEC-1:** Placement is per node.
- **EXEC-2:** Provider saturation does not consume a global execution slot.
- **EXEC-3:** Workers and disposable sandboxes are separate lifecycles.
- **EXEC-4:** Profile identity is known before provisioning and attested at
  execution.
- **EXEC-5:** Services, sessions, and scarce devices use durable leases.

### 19.4 Reproducibility and caching

- **REP-1:** Every run uses one immutable source snapshot.
- **REP-2:** The requested and attained reproducibility levels are reported.
- **REP-3:** Cache identity includes semantic execution profile and all declared
  typed inputs.
- **REP-4:** Ready cache hits return before worker reservation.
- **REP-5:** Result, tool, and warm-provider caches are distinct.
- **REP-6:** Artifact provenance is queryable and digest verified.

### 19.5 Agents and concurrency

- **AGENT-1:** Discovery, plan, run, watch, status, cancel, and resume have stable
  JSON interfaces.
- **AGENT-2:** Runs detach from the initiating agent process.
- **AGENT-3:** `taskflowd` globally schedules concurrent agents and providers.
- **AGENT-4:** Mutable state is isolated per namespace/worktree by default.
- **AGENT-5:** Abandoned namespace resources are reclaimed by TTL and a durable
  reaper.
- **AGENT-6:** Agent-authored code cannot grant itself secrets, effects, targets,
  or network access.

### 19.6 Durability and security

- **DUR-1:** Every scheduling transition is durable before it enables more
  work.
- **DUR-2:** Resume validates structural compatibility and artifact presence.
- **DUR-3:** Cancellation triggers bounded cleanup and records orphans.
- **SEC-1:** Planning code does not execute in the daemon trust boundary.
- **SEC-2:** Secrets are never serialized into plan, state, cache, or logs.
- **SEC-3:** Effects bind exact inputs, actor, authorization, and idempotency.

## 20. Comparison with existing products

This comparison describes product architecture, not a claim that one tool is
universally better. Taskflow is much earlier than the compared projects; most
of the differentiating Taskflow features in this document remain proposed.

### 20.1 Summary matrix

| Dimension | Taskflow direction | Dagger | Cloudflare CI SDK | GitHub Actions | Bazel | Taskfile / Lefthook |
| --- | --- | --- | --- | --- | --- | --- |
| Authoring | Go-first typed project operations; language-neutral plan IR | Typed modules in supported SDKs | TypeScript classes/API | YAML plus expression language and actions | BUILD/Starlark rules and macros | YAML recipes / hook config |
| Composition unit | Project artifact, report, service, endpoint, stack, effect | Directory, File, Container, Service, Secret, custom object | Durable runner result and sandbox/workspace state | Workflow, job, step, output, artifact | Target, rule, action, artifact, provider | Task/command and hook job |
| Execution substrate | Per-node local, native, VM, remote, simulator, device | Container-oriented Dagger engine/runner | Cloudflare Workflows and Sandbox | Hosted or self-hosted runners | Local/remote sandboxed build actions | Current host process |
| Reproducibility | Explicit profile + immutable source + disposable sandbox; container optional | Strong explicit host boundary and container execution | Fresh managed sandboxes and durable Cloudflare platform | Depends heavily on actions, runner images, and workflow discipline | Strong hermetic build/toolchain model when rules comply | Primarily recipe-level up-to-date checks and host state |
| Cache | Typed artifacts and planned profile identity; cache before provision is proposed | Content-addressed incremental execution | SDK-managed cache/backups on Cloudflare services | Action/tool/artifact caches configured by workflow | Fine-grained local/remote action cache | Source/generate checks; no distributed typed result graph |
| Native Apple/mobile | First-class design goal through macOS/device providers | Outside normal container execution model | Linux Sandbox focus | macOS hosted/self-hosted runners and third-party actions | Possible through specialized Apple rules/toolchains | Native commands, but no cross-host scheduler |
| Durable resume | Existing Taskflow journal; daemon expansion proposed | Re-evaluation benefits from cache; workflow run state differs by deployment | Cloudflare Workflows durable steps | Hosted workflow/job retry and rerun semantics | Incremental action graph/cache, not general workflow resume | No durable distributed run state |
| Agent interface | Typed schema + plan + async JSON lifecycle proposed | Strong schema-discoverable typed API | TypeScript API; Cloudflare-native integration | Large ecosystem and APIs, but YAML/string contexts | Queryable build graph, rule expertise required | Simple CLI, limited typed discovery |
| Adoption | Keep recipes, progressively expose edges | Pipeline/module rewrite around Dagger values | Commit to Cloudflare runtime and services | Add workflow YAML and actions | Model builds in Bazel rules/BUILD files | Lowest initial migration cost |

### 20.2 Dagger

Dagger is the closest inspiration for Taskflow's typed composition. Its type
system deliberately makes `Directory`, `File`, `Container`, `Service`,
`Secret`, and custom objects discoverable and composable. Its sandbox denies
implicit host access, and just-in-time services and content-addressed execution
give it a coherent developer experience.

Taskflow should copy the principle that the graph continues through typed
values and that agents can discover the same schema as humans. It should not
copy the assumption that the universal execution value is a container.

Taskflow's intended advantages:

- first-class native macOS, Xcode, simulator, emulator, and device placement;
- per-node heterogeneous targets in one graph;
- migration-friendly Taskfile/Just leaves;
- durable run journal and explicit resume semantics;
- reusable warm VMs/native workers with disposable lightweight sandboxes;
- per-worktree stack isolation and global local/remote scheduling for agents;
- typed project-domain APIs rather than requiring callers to assemble
  container operations.

Dagger's current advantages:

- a real, mature typed module and discovery experience;
- strong sandbox semantics and explicit host capability passing;
- integrated content-addressed execution, services, secrets, tracing, and
  interactive debugging;
- a functioning ecosystem and remote runner story;
- product polish Taskflow has not yet earned.

Taskflow should prove that native profiles and sandboxes can be as explainable
as Dagger containers. Without immutable source, pinned profiles, and enforced
capabilities, “native flexibility” would simply be weaker reproducibility.

### 20.3 Cloudflare CI SDK

Cloudflare CI is a TypeScript CI engine built specifically on Cloudflare
Workers, Workflows, and Sandbox. It benefits from durable Workflow steps,
automatic retry/state persistence, managed sandbox execution, and Cloudflare
storage/integration. Sandbox directory backups provide point-in-time snapshots
and copy-on-write restoration.

Ideas Taskflow should adopt:

- cache lookup before creating a sandbox;
- durable step state and idempotency awareness;
- lightweight snapshot handles between stages;
- platform-native observability and lifecycle APIs;
- clear separation of the package authoring API from deployable application
  integration.

Taskflow's intended differences:

- provider-neutral and self-hosted rather than Cloudflare-specific;
- typed project artifacts and declared outputs rather than treating the entire
  workspace snapshot as the main composition value;
- native macOS/mobile/device targets in addition to Linux sandboxes;
- a shared local daemon and worktree namespace model for coding agents;
- execution profiles and attestation spanning VM and native providers.

Cloudflare CI is attractive when the desired operating environment is already
Cloudflare. Taskflow accepts more infrastructure complexity in exchange for
heterogeneous native placement and local-first control.

### 20.4 GitHub Actions

GitHub Actions provides a comprehensive event model, job/step conditions,
matrices, concurrency groups, environments, permissions, hosted and self-hosted
runners, artifacts, caches, and a vast action ecosystem. It is the familiarity
baseline for trigger and `if` semantics.

Taskflow should learn from:

- the distinction between workflow triggers and job/step conditions;
- normalized event contexts;
- status functions such as success, failure, cancellation, and always;
- matrix expansion and concurrency groups;
- protected environments and scoped permissions;
- ecosystem-friendly trigger/status integrations.

Taskflow should differ by using typed condition constructors and plan IR rather
than string expressions, typed optional outputs rather than implicit missing
job outputs, and engine-managed bounded `Finally` rather than a broad
unconditional escape hatch. It should also make source, execution profile, and
cache identity visible as first-class values.

GitHub Actions remains the stronger hosted CI product and integration hub.
Taskflow can complement it: a small GitHub workflow may trigger the same
Taskflow project operation used locally and by agents.

### 20.5 Bazel

Bazel is the strongest comparison for hermetic build actions, precise declared
inputs, toolchain/platform modeling, sandboxing, fine-grained caching, and
remote execution. Its remote execution protocol enables consistent distributed
actions and shared output reuse.

Taskflow should learn from:

- tools and toolchains as declared inputs;
- execution versus target platforms;
- action-level hermeticity and sandbox enforcement;
- content-addressed remote execution and caching;
- graph queries and deterministic analysis;
- treating writes to source and ambient host tools as correctness hazards.

Taskflow is not intended to replace Bazel as a build system. Bazel models a
fine-grained build universe through language rules, BUILD targets, providers,
and toolchains. Taskflow coordinates coarser project operations, services,
native test infrastructure, effects, and incremental migration from existing
commands.

For a large codebase willing to model all build actions, Bazel should offer
stronger hermeticity and finer incremental reuse. For a mixed repository that
needs Go, Gradle, Xcode, simulators, databases, security scanners, and release
operations without first creating a rule ecosystem, Taskflow aims for a lower
adoption cost and broader workflow model. Taskflow can also invoke Bazel as a
leaf and pass its outputs as typed artifacts.

### 20.6 Taskfile and Just

Taskfile and Just are excellent recipe front ends. They are concise, familiar,
and well suited to local commands. Taskfile supports dependencies, parallel
dependencies, platform filters, variables, includes, and source/generated-file
up-to-date checks.

Taskflow adds value when a recipe needs durable run state, result artifacts,
remote/native placement, cross-target transfer, global resource scheduling,
typed composition, services, or agent discovery. Absorbing those orchestration
responsibilities does not justify rebuilding Taskfile's recipe language.

### 20.7 Lefthook

Lefthook is a fast and useful Git-hook manager with branch/state conditions,
file selection, globs, parallel jobs, tags, local overrides, and hook-specific
file views. Taskflow should integrate with it rather than compete with hook
installation and Git ergonomics.

The important boundary is that Lefthook triggers the operation while Taskflow
owns its graph and conditions. This prevents local hooks from drifting away
from agent and CI behavior.

## 21. Incremental development roadmap

The canonical delivery plan is the [risk-first roadmap](roadmap.md). It starts
from a clean implementation, isolates the architecture bootstrap as a
prototype, and tests the highest-impact uncertainties before initializing the
new production module. The phases below are a product-level synopsis; the
detailed roadmap's experiments, gates, branches, and stop criteria take
precedence.

### Phase 0: isolate evidence and reduce architectural uncertainty

Objective: preserve the prototype as reproducible evidence, then test the
authoring model, language-neutral plan, planning trust boundary, lightweight
isolation, cache identity, daemon economics, and native macOS feasibility
before selecting the new foundation.

Deliverables:

- review this specification against three representative workflows;
- run the roadmap's bounded Risk Lab experiments and record branch decisions;
- add ADRs for typed values, plan IR, worker/sandbox split, reproducibility
  levels, daemon trust boundary, language-neutral protocol boundaries, and
  namespaces;
- document which prototype results are proven evidence and which assumptions
  remain unproven;
- define benchmarks for no-op plan, cache hit, local sandbox startup, warm VM
  sandbox startup, and agent concurrency;
- create threat-model and failure-model documents.

Exit criteria:

- all exposure-20 risks have a decision or bounded mitigation;
- open decisions and non-goals are accepted;
- no new production module or public API is initialized prematurely.

### Phase 1: typed values and operation schema prototype

Objective: implement the semantic model selected by the risk gate and validate
that the concise API is genuinely easier for humans and agents.

Deliverables:

- prototype `Artifact[T]`, `Check`, `Report[T]`, `Optional[T]`, and `Effect[T]`;
- infer dependencies from value handles;
- register typed operations and arguments;
- implement `taskflow api --json`, `describe --json`, and `plan --json`;
- produce immutable, language-neutral plan IR and a plan digest;
- keep targets, services, and conditions minimal in the first prototype;
- dogfood `check`, one artifact-producing pipeline, and one typed service
  consumer.

Exit criteria:

- an agent can discover, validate, plan, and run the dogfood operation without
  reading `.taskflow` source;
- Go compilation catches incompatible artifact types;
- the generated graph covers the prototype's representative check semantics
  without importing prototype code;
- common project code is materially shorter than direct `flow.Step` usage;
- a small language-agnostic fixture can consume the emitted schema and plan
  without interpreting Go-specific values.

### Phase 2: immutable source and cache-before-provision local execution

Objective: establish the reproducibility foundation and improve cache latency.

Deliverables:

- `SourceView` and one immutable per-run Merkle/CAS snapshot;
- source selection represented as typed tree handles;
- execution profile declarations and digests;
- local worker/sandbox split;
- clean copy-on-write or efficiently materialized local sandbox;
- sanitized environment and explicit host capability escape hatch;
- compute cache identity before target reservation when all inputs are known;
- provenance records and cache explanation;
- compare `workspace` versus `sandbox` performance.

Exit criteria:

- editing the worktree after run creation cannot change a node's source;
- a ready cache hit acquires no execution environment;
- two concurrent local runs do not share output workspaces;
- attained reproducibility level and any downgrade are visible;
- local sandbox overhead is acceptable for routine checks.

### Phase 3: `taskflowd` and asynchronous lifecycle

Objective: remove individual CLI processes as the ownership and scheduling
bottleneck.

Deliverables:

- per-user daemon with authenticated local RPC;
- SQLite-backed runs, transitions, plans, namespaces, and leases;
- detach, status, watch cursor, cancel, and resume JSON APIs;
- global CPU/memory scheduling and fairness;
- daemon-owned artifact CAS and retention;
- crash recovery, orphan detection, and reaper;
- restricted project-driver planning execution;
- compatibility negotiation between CLI, driver, and daemon.

Exit criteria:

- a run survives CLI and agent termination;
- multiple agents cannot collectively exceed configured local resources;
- log streaming resumes without gaps from a cursor;
- daemon restart reconstructs runs and cleanup obligations;
- project planning code receives no daemon privilege.

### Phase 4: conditions, triggers, and worktree namespaces

Objective: make the same operation safe and predictable from hooks, agents,
and CI.

Deliverables:

- trigger, planning-condition, and outcome-condition IR;
- `skipped` state and typed optional outputs;
- three-valued condition evaluation and explanations;
- bounded `Finally` semantics;
- worktree/agent namespace derivation and TTL;
- Lefthook bridge with `GitIndex` and `GitRange` source views;
- generic push/pull-request adapter;
- concurrency keys and queue/cancel policies.

Exit criteria:

- pre-commit validates the staged snapshot;
- manual, hook, and agent calls select the same graph for the same normalized
  facts;
- no skipped producer exposes a normal artifact;
- abandoned namespaces are reclaimed safely.

### Phase 5: typed services and per-agent stacks

Objective: reproduce a full isolated application stack for each worktree.

Deliverables:

- `Service[T]`, `Endpoint[T]`, `Stack[T]`, health checks, and session leases;
- namespace-private service names, volumes, networks, and port allocation;
- lazy startup and automatic bounded teardown;
- endpoint injection into consuming nodes;
- retain/release and TTL controls for iterative agents;
- integration-test stack dogfood with database, cache, and API.

Exit criteria:

- two agents run identical stacks concurrently without port or data collision;
- an agent never parses a host port from logs;
- stack lifecycle survives caller disconnect and is reclaimed on expiry;
- immutable service build results are shared while mutable data is not.

### Phase 6: production remote Linux execution

Objective: move parallel work off the local host while preserving the same
plan and cache semantics.

Deliverables:

- production worker protocol and first Linux provider;
- warm pool, immutable profiles, disposable Linux sandboxes;
- CAS delta transfer and artifact publication;
- attestation, secret injection, network policy, cancellation, and reconnection;
- remote capacity discovery outside scheduler path;
- provider outage and orphan fault-injection tests;
- optional remote cache/object storage backend.

Exit criteria:

- cache hits do not wake or create remote workers;
- a failed pipeline resumes on another compatible worker without repeating
  valid successful work;
- source and artifact digests are verified across transfer;
- local and remote results have equivalent declared identity.

### Phase 7: native macOS and mobile targets

Objective: prove that the architecture supports high-value native work that
container-first systems handle awkwardly.

Deliverables:

- Orchard/Tart-style macOS provider;
- immutable VM profile distribution and attestation;
- warm VM pool and APFS copy-on-write node workspaces;
- Xcode/SDK/simulator profile identity;
- simulator session and finite-resource scheduling;
- Android emulator provider or capability;
- physical-device contract spike;
- cross-target typed endpoint routing.

Exit criteria:

- an iOS build/test pipeline runs remotely without changing project API;
- Linux services feed native mobile tests through typed endpoints;
- simulator state is isolated per namespace and reliably reset;
- warm-path provisioning latency is measured and does not dominate common
  nodes;
- provenance records exact native toolchain and device/simulator identity.

### Phase 8: hardening and ecosystem

Objective: prepare stable contracts and broader adoption.

Deliverables:

- schema and protocol migration registries;
- policy configuration and approval workflows;
- secret redaction and artifact leak defenses;
- quotas, cost controls, garbage collection, and retention policies;
- OpenTelemetry export and CI status integrations;
- reusable language/project modules;
- GitHub Actions bridge invoking Taskflow operations;
- shell completion, diagnostic bundles, and performance regression tests;
- compatibility and release policy for public providers/modules.

Exit criteria:

- security and failure-model reviews have no unresolved critical findings;
- upgrades preserve or explicitly migrate durable state and artifacts;
- third-party modules/providers can target a documented stable contract;
- real multi-agent and native-mobile workloads meet published latency and
  reliability budgets.

## 22. Success measures

Initial product metrics should emphasize correctness and developer latency, not
only total throughput.

### 22.1 Usability

- Time for a new developer or agent to discover and run the correct operation.
- Lines and concepts required for a common project operation.
- Percentage of operations callable without low-level `flow.Step` options.
- Plan validation failures caught before worker acquisition.

### 22.2 Performance

- No-op discovery and plan latency.
- Cache-hit latency and percentage of hits that acquire no worker.
- Local sandbox creation latency.
- Warm Linux and macOS sandbox creation latency.
- VM pool cold-start frequency rather than hiding cold-start cost.
- Local CPU/memory consumed while remote agent pipelines run.

### 22.3 Reproducibility

- Percentage of cacheable nodes at each reproducibility level.
- Cross-worker cache hit validity.
- Undeclared-input failures detected by isolation tests.
- Number of profile mismatches and quarantined workers.
- Artifact provenance completeness.

### 22.4 Agent concurrency

- Concurrent worktree stacks without collisions.
- Scheduler fairness and queue latency by class.
- Orphan resource count and cleanup time.
- Structured API usage without terminal scraping.
- Duplicate active work avoided through caching or authorized attachment.

### 22.5 Reliability and security

- Successful recovery after daemon, worker, and network failure injection.
- Secret redaction and artifact scanning failures.
- Effects with complete idempotency/provenance records.
- Unauthorized capability requests denied during plan or admission.

## 23. Risks and mitigations

### 23.1 The concise API may hide too much

Mitigation: every high-level operation lowers to an inspectable plan; advanced
authors retain the kernel escape hatch; explanations show hidden defaults.

### 23.2 Generic typed values may become awkward in Go

Mitigation: prototype real project modules before stabilizing signatures. Favor
small value handles and ordinary functions over a deep generic type hierarchy.

### 23.3 Compiled planning code is arbitrary code

Mitigation: run it outside the daemon in a restricted planning sandbox, provide
no secrets, validate emitted IR, and bind the accepted plan digest.

### 23.4 Native execution may be less isolated than promised

Mitigation: publish attained reproducibility levels, require profile attestation,
test undeclared access, and fail rather than silently downgrade. Use VMs for
hostile code or stronger macOS isolation.

### 23.5 Warm state may contaminate results

Mitigation: distinguish workers, sandboxes, sessions, tool caches, and result
caches. Only immutable result artifacts prove success. Reset and contamination
tests are provider acceptance requirements.

### 23.6 The daemon may become too large

Mitigation: preserve small interfaces and separate planning, scheduling,
provider, CAS, service, and policy packages. Start as one deployable process;
do not prematurely turn it into distributed microservices.

### 23.7 Remote providers may shape the universal API

Mitigation: provider-specific configuration stays typed in provider packages.
The universal contract includes only proven lifecycle and identity concepts.
Implement Linux and macOS providers before declaring it stable.

### 23.8 Taskfile migration may duplicate work

Mitigation: enforce and document one owner per edge. Provide graph diagnostics
for obvious nested Task invocations and migration examples.

### 23.9 Agent parallelism may increase cost or resource pressure

Mitigation: global quotas, fairness, concurrency groups, TTLs, budget-aware
providers, cache-before-provision, and visible queue/cost estimates.

## 24. Open decisions

These questions should be answered through prototypes and ADRs:

1. What is the smallest pleasant Go API for typed value production and inferred
   edges?
2. Can operation schemas be derived reliably from Go signatures and annotations,
   or should registration use explicit typed descriptors?
3. What evidence and adoption threshold would justify a second authoring SDK,
   and should TypeScript be the first candidate?
4. Which condition/result combinators are necessary before optional values
   become cumbersome?
5. What local sandbox technology gives useful isolation on macOS with low
   enough startup cost?
6. Should the first daemon RPC use local HTTP, Connect/gRPC, or a simpler framed
   protocol?
7. Is SQLite sufficient for all initial lease and event-stream requirements?
8. Which Merkle tree/CAS format best balances interoperability, safe extraction,
   and implementation effort?
9. How should tool caches be partitioned and scrubbed without destroying their
   performance value?
10. What exact trust policy applies to uncommitted agent changes in `.taskflow`?
11. Which Linux provider best falsifies the worker/sandbox contract before a
    stable protocol is published?
12. Can a warm macOS VM safely host multiple concurrent sandboxes, or should it
    be single-tenant per active namespace?
13. How are interactive approval and production effects represented without
    turning Taskflow into a hosted CI service?
14. What standard provenance and remote-execution protocols should Taskflow
    adopt rather than invent?
15. When should an identical caller attach to an active run versus create a new
    run that reuses node cache entries?

## 25. Recommended next step

Do not begin with `taskflowd`, a production provider, or a new shared kernel.
Follow the [risk-first roadmap](roadmap.md): establish representative fixtures
and measurement contracts, then run the typed-authoring/plan-IR,
planner-security, immutable-source/sandbox/cache, shared-scheduler simulation,
and macOS feasibility experiments. Only Gate 1 may authorize the clean
production module and its first public value contracts.

This front-loads the claims most capable of invalidating the architecture:
that Taskflow can be more natural to author, safe for agents, lightweight to
run, cacheable before provisioning, and credible for native mobile work.

## 26. References

Taskflow repository documents:

- [Risk-first roadmap](roadmap.md)
- [Architecture-bootstrap prototype](../prototype/bootstrap/README.md)
- [Prototype architecture](../prototype/bootstrap/docs/architecture.md)
- [Prototype historical roadmap](../prototype/bootstrap/docs/roadmap.md)
- [ADR 0001: Pipelines are compiled Go](decisions/0001-code-first-go.md)
- [ADR 0002: Every dependency edge has one scheduler](decisions/0002-one-owner-per-edge.md)

External primary documentation:

- [Dagger: The Type System](https://docs.dagger.io/extending/type-system/)
- [Dagger: Core and custom types](https://docs.dagger.io/extending/types/)
- [Dagger: Sandboxed Runtime](https://docs.dagger.io/features/sandbox/)
- [Dagger: Running Services](https://docs.dagger.io/next/using-dagger/services/)
- [Dagger: Custom Runner](https://docs.dagger.io/next/reference/configuration/custom-runner/)
- [Cloudflare CI repository](https://github.com/cloudflare/ci)
- [Cloudflare Workflows](https://developers.cloudflare.com/workflows/)
- [Cloudflare Sandbox backups](https://developers.cloudflare.com/sandbox/api/backups/)
- [GitHub Actions workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [GitHub Actions expressions](https://docs.github.com/en/actions/reference/workflows-and-actions/expressions)
- [GitHub Actions concurrency](https://docs.github.com/en/actions/concepts/workflows-and-actions/concurrency)
- [Bazel hermeticity](https://bazel.build/concepts/hermeticity)
- [Bazel remote execution](https://bazel.build/remote/rbe)
- [Bazel rules for remote execution](https://bazel.build/docs/remote-execution-rules)
- [Task guide](https://taskfile.dev/docs/guide)
- [Lefthook `only`](https://lefthook.dev/configuration/only/)
- [Lefthook `skip`](https://lefthook.dev/configuration/skip/)
- [Lefthook file selection](https://lefthook.dev/configuration/files/)
