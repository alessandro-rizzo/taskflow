# Taskflow

Taskflow is exploring a typed, reproducible, agent-first execution system for
project workflows across local, remote, VM, native macOS, simulator, emulator,
and device targets.

The repository is deliberately back in an architecture-validation phase. The
previous Go implementation proved several useful kernel concepts, but it is no
longer treated as the codebase that the product must incrementally extend.

## Repository layout

```text
docs/                         product specification, decisions, and roadmap
experiments/                  disposable risk-reduction spikes
fixtures/                     frozen, reusable T1+ fixtures and harnesses
prototype/bootstrap/          isolated previous implementation
```

- [Product specification](docs/product-specification.md) defines the intended
  product and architectural direction.
- [Risk-first roadmap](docs/roadmap.md) defines the experiments, decision gates,
  branches, and incremental delivery sequence.
- [Architecture-bootstrap prototype](prototype/bootstrap/README.md) preserves
  the existing compiled-Go DAG, scheduler, journal, cache, runner adapters, and
  local/SSH target experiments as evidence.
- [Prototype baseline](prototype/bootstrap/docs/baseline.md) separates the
  concepts it demonstrates from the product claims it does not validate.

New product code should not import `prototype/bootstrap`. A concept graduates
from an experiment only after its evidence and decision are recorded. Code may
then be implemented cleanly at the repository root with no compatibility
obligation to prototype APIs.

## Current status

The next work is the roadmap's uncertainty-reduction tranche, not a wholesale
rewrite. It tests the typed Go authoring experience, language-neutral plan IR,
planning security boundary, lightweight reproducibility, cache-before-provision
identity, shared agent scheduling, and native macOS feasibility before the new
foundation is selected.

## Development

The root gate verifies the preserved prototype and every maintained executable
T1 fixture or harness under the root-pinned toolchain:

```sh
mise trust
mise install
mise exec -- task check
```

The T1-only portion is also available directly:

```sh
mise exec -- task t1:check
```

| Surface | Root-gate coverage |
| --- | --- |
| `fixtures/w1/repo` | Formatting, `go vet`, plain `go test`, and a separate race-detector run |
| `fixtures/w1/repo-*-failure` | Negative fixtures; excluded from the normal green gate and used only by explicit failure probes |
| `fixtures/w2` | Specification-only; no executable validator exists to delegate to |
| `fixtures/w3` | The dependency-free JSON specification validator; this does not claim real W3 infrastructure exists |
| `fixtures/t1-benchmark-harness` | Its fixture-local `task check`, followed separately by `go test -race ./...` |
| `fixtures/t1-plan-conformance` | Its fixture-local `task check`, followed separately by `go test -race ./...` |
| `fixtures/t1-lifecycle-faults` | Its fixture-local `task check`, followed separately by `go test -race ./...` |
| `fixtures/integrity-faults` | Its fixture-local `task check`, followed separately by `go test -race ./...` |
| `fixtures/malicious-planner` | Its fixture-local `task check`, followed separately by `go test -race ./...` |

The fixture-local Taskfiles remain the authority for their ordinary checks.
Root delegation invokes `task` and `go` directly inside the environment already
created by the single root `mise exec`; it does not nest `mise exec` or trust a
fixture-local `mise.toml`. Named wrapper tasks keep the failing fixture visible
in Task output, and any delegated non-zero exit fails the root gate.

Run its example with:

```sh
mise exec -- task prototype:example
```

Experiments add their own self-contained verification commands as they are
introduced; they are not implicitly part of the maintained root gate.

## License

MIT
