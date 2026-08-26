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
> cache coordinator, revisioned transition journal, parallel scheduler,
> compiled-driver protocol, and local/SSH target contracts compile and are
> tested. The SSH provider is a contract-falsification spike, not a
> production-ready remote backend.

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
	"github.com/arr/taskflow/flow"
	"github.com/arr/taskflow/runner/taskfile"
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
			flow.EnvironmentKeys("GOFLAGS"),
			flow.Toolchain("go", "go", "version"),
			flow.Requires("linux", "arm64"),
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
The resolved command, adapter configuration, selected environment values,
toolchain probes, and target identity all participate in cache identity.

## Project driver

A project defines its executable configuration in `.taskflow/main.go`:

```go
func main() {
	runners := runner.NewRegistry()
	must(runners.Register(taskfile.New()))

	targets := target.NewRegistry()
	must(targets.Register(local.New(".")))

	executor := &engine.RuntimeExecutor{
		Runners: runners,
		Targets: targets,
		Cache: &cache.Coordinator{
			Store:         cachefile.New(".taskflow/cache"),
			WorkspaceRoot: ".",
		},
	}
	os.Exit(driver.Main(driver.Config{
		Pipelines: []*flow.Pipeline{localVerify()},
		Executor:  executor,
	}))
}
```

The generic CLI fingerprints and caches that compiled driver, checks its
internal protocol version, then delegates:

```sh
taskflow list
taskflow graph verify
taskflow run --max-parallel 4 verify
taskflow resume RUN_ID verify
```

This repository dogfoods the protocol with its own `.taskflow/main.go`.
`TASKFLOW_DRIVER_CACHE` can override the platform driver cache directory for
hermetic development environments.

## Packages

- `flow`: typed DAG construction, validation, and definition fingerprinting.
- `runner`: runner adapter contract and adapter registry.
- `runner/taskfile`, `runner/just`, `runner/command`: initial adapters.
- `target`: execution target lifecycle and provider registry.
- `target/local`: local process execution.
- `target/ssh`: deliberately crude remote transfer/execution proof.
- `engine`: parallel scheduler and runtime executor.
- `state`: revisioned durable transition-journal contract.
- `state/file`: atomic append-only JSON transition implementation with locking.
- `cache`: cache-key coordinator and content-addressed blob contract.
- `cache/file`: atomic filesystem-backed blob store.
- `workspace`: deterministic input hashing and safe tar transfer.
- `driver`, `internal/projectdriver`: versioned project protocol and CLI loader.
- `event`: stable execution event stream.
- `terminal`: line-oriented terminal renderer.

See [Architecture](docs/architecture.md) and
[Roadmap](docs/roadmap.md) for the current boundaries and implementation order.
The proposed [Product specification](docs/product-specification.md) describes
the longer-term typed, reproducible, native-target, and agent-first direction.
The [Fable 5 adversarial review](docs/reviews/2026-07-27-fable-5.md) records the
second-pass findings and their disposition.

## Development

Requirements:

- [mise](https://mise.jdx.dev/) (installs the pinned Go toolchain)
- Task 3.x (optional, for repository shortcuts)

```sh
mise trust
mise install
mise exec -- task check
mise exec -- task example
```

Without Task:

```sh
mise exec -- go test ./...
mise exec -- go vet ./...
mise exec -- go run ./examples/basic
```

`mise.toml` pins the development toolchain to Go 1.25.12. The `go 1.24.0`
directive in `go.mod` remains the module's minimum supported Go version.

## Status

Taskflow is not ready for production use. The next remote slice should replace
the SSH subprocess spike with a real Sprite provider and use the resulting
pressure to revise these pre-v1 interfaces.

## License

MIT
