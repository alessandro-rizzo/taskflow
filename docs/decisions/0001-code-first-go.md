# ADR 0001: Pipelines are compiled Go

Status: accepted

## Context

Taskflow needs reusable and typed pipeline definitions without recreating a
large declarative workflow language. Go is already required for the engine and
provides functions, packages, generics, editor tooling, tests, and a portable
compiler cache.

## Decision

Pipeline definitions are compiled Go code using the `flow` API.

The CLI will build and cache a small project-local driver rather than interpret
Go source or load Go `plugin` binaries.

JSON is permitted for generated state and internal protocols. It is not a
user-authored pipeline format.

## Consequences

- Invalid references and provider configuration can fail during compilation or
  graph construction.
- Users can create normal Go helper libraries for shared pipelines.
- Startup must hide driver compilation behind hashing and the Go build cache.
- Extension modules are linked into the driver.
- Taskflow cannot edit workflow definitions through a generic form or web UI,
  which is an intentional non-goal.
