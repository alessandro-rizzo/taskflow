# ADR 0002: Every dependency edge has one scheduler

Status: accepted

## Context

Taskfile and Just can compose recipes, while Taskflow also needs a DAG for
placement, caching, parallelism, retries, and resume.

If both Taskflow and an invoked task runner execute the same dependency, work
may run twice or on the wrong machine. Taskfile's `run: once` cannot deduplicate
separate processes or remote environments.

## Decision

A task-runner dependency may stay inside one opaque Taskflow node. When it needs
individual Taskflow behavior, the edge moves to Taskflow and the invoked recipe
becomes a dependency-free leaf.

Taskflow will not infer distributed semantics from arbitrary nested task-runner
commands.

## Consequences

- Existing repositories can adopt Taskflow incrementally.
- Fine-grained graph visibility requires selectively refactoring aggregate
  tasks.
- The source of truth for each edge is unambiguous.
- Local compatibility wrappers can preserve familiar `task <aggregate>`
  commands while delegating the expanded graph to Taskflow.
