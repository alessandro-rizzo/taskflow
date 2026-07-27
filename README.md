# Taskflow

Taskflow is a code-first pipeline orchestrator for solo developers.

It keeps task runners such as [Task](https://taskfile.dev/) and
[Just](https://github.com/casey/just) as the executable recipe layer, then adds
a typed Go DAG, parallel scheduling, durable resume, caching, and replaceable
local or remote execution targets.

Taskflow is intentionally not a hosted CI service, a YAML workflow language,
or a web UI.

> [!IMPORTANT]
> This repository is at its architecture bootstrap. The typed graph,
> adapter/provider contracts, parallel scheduler, and durable state primitives
> compile and are tested. Cache coordination and remote providers are the next
> implementation slices.

## Design principles

- **Go is the pipeline language.** Pipelines are ordinary compiled Go code with
  refactoring, functions, loops, types, tests, and editor support.
- **Existing task runners remain useful.** A node can invoke a Task task, a
  Just recipe, a direct command, or a future adapter.
- **Resume is foundational.** Every transition is journaled. A compatible
  failed run can restart without re-running successful nodes.
- **Caching is content-addressed.** A cache hit must be explainable from
  declared inputs, implementation, platform, and toolchain identity.
- **Targets are replaceable.** Local execution, Fly Sprites, Tart/Orchard, and
  future providers implement the same small lifecycle.
- **The terminal is the UI.** Output is line-oriented, scriptable, and useful at
  quiet, normal, or verbose levels.
- **Local should remain the fastest path.** Remote execution is a placement
  decision, not a different workflow authoring experience.

## Intended API

```go
package main

import (
	"github.com/alessandro-rizzo/taskflow/flow"
	"github.com/alessandro-rizzo/taskflow/runner/taskfile"
)

func verify() *flow.Pipeline {
	task := taskfile.New()

	return flow.MustDefine("verify", func(p *flow.Builder) {
		format := p.Step(
			"format",
			task.Run("fmt:check"),
			flow.On("local"),
			flow.Inputs("**/*.go"),
		)

		unit := p.Step(
			"unit",
			task.Run("test"),
			flow.Needs(format),
			flow.On("sprite"),
			flow.Inputs("**/*.go", "go.mod", "go.sum"),
			flow.Outputs("build/test-results/**"),
			flow.WithCache(flow.CacheReadWrite, "v1"),
		)

		p.Step(
			"package",
			task.Run("build"),
			flow.Needs(unit),
			flow.On("local"),
			flow.Outputs("bin/taskflow"),
		)
	})
}
```

The invocation is structured data. The Task adapter resolves it to
`task <name>` only after Taskflow has selected and acquired the target.

## Packages

- `flow`: typed DAG construction, validation, and definition fingerprinting.
- `runner`: runner adapter contract and adapter registry.
- `runner/taskfile`, `runner/just`, `runner/command`: initial adapters.
- `target`: execution target lifecycle and provider registry.
- `target/local`: local process execution.
- `engine`: parallel scheduler and runtime executor.
- `state`: durable run journal contract.
- `state/file`: atomic JSON journal implementation.
- `cache`: content-addressed blob contract.
- `cache/file`: atomic filesystem-backed blob store.
- `event`: stable execution event stream.
- `terminal`: line-oriented terminal renderer.

See [Architecture](docs/architecture.md) and
[Roadmap](docs/roadmap.md) for the boundaries and implementation order.

## Development

Requirements:

- Go 1.24 or newer
- Task 3.x (optional, for repository shortcuts)

```sh
task check
task example
```

Without Task:

```sh
go test ./...
go vet ./...
go run ./examples/basic
```

## Status

Taskflow is not ready for production use. The repository deliberately starts
with small interfaces and executable invariants before adding provider SDKs.

## License

MIT
