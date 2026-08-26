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

The root gate currently verifies the preserved prototype:

```sh
mise trust
mise install
mise exec -- task check
```

Run its example with:

```sh
mise exec -- task prototype:example
```

Experiments will add their own self-contained verification commands as they are
introduced.

## License

MIT
