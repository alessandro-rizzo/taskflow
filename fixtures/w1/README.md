# W1 fixture: fast project check

Roadmap tranche: T1. Workflow: W1. Task: TF-002.01.

See [`manifest.yaml`](manifest.yaml) for the machine-readable declaration
(fixture id, version `t1-experimental-v1`, expected graph, planning
conditions, expected diagnostics, execution states). This file is the
human-readable twin.

Status: frozen, reusable T1+ fixture per `docs/roadmap.md` section 3 rule 3a
— not disposable, not a Taskflow-authored pipeline, and not a claim that any
current implementation (including `prototype/bootstrap`) satisfies every
expectation declared here. It is what future experiments (E01, E02, E04, ...)
are measured against.

## What this fixture is, and is not

- It is a minimal **target repository** representing W1's shape (roadmap
  section 4: format check + unit tests + static analysis -> aggregate
  Check) that a future authoring/planning implementation points a pipeline
  at.
- It is **not** a Taskflow-authored pipeline itself: no typed authoring SDK
  exists before Gate 1, and fixtures must not import `prototype/bootstrap`
  (roadmap section 3 rule 3a).
- It is **not** a benchmark result format: `TF-002.04` owns that. This
  fixture's `expected_graph`, `planning_conditions`, and
  `expected_diagnostics` are golden values a benchmark run or conformance
  harness is meant to check against.

## Repositories

| Directory | Fails | Purpose |
| --- | --- | --- |
| `repo/` | none | base case: format, unit tests, and static analysis all pass cleanly |
| `repo-format-failure/` | format only | `greeter.go` has non-canonical formatting (mixed tab/space indentation, no spaces around a binary `+`) |
| `repo-test-failure/` | test only | `greeter_test.go` asserts an incorrect expected value |
| `repo-lint-failure/` | lint only | `greeter.go` has an unreachable `return` after another `return`, caught by `go vet`'s `unreachable` analyzer |

Each variant differs from `repo/` in exactly one file, along exactly one
dimension, verified empirically below.

### Why "unreachable code", not a `Printf` mismatch, for the lint variant

`go test` runs a built-in high-confidence subset of `go vet` before testing
(unless invoked with `-vet=off`), and that subset includes the `printf`
analyzer — an original draft of this fixture used a `fmt.Printf` verb
mismatch for the lint-failure variant, and it turned out `go test ./...`
failed too (a build failure), collapsing the intended lint/test distinction.
`unreachable` was verified empirically (see `raw/repo-lint-failure.log`) to
be caught by `go vet ./...` but **not** by `go test ./...`'s default subset,
keeping the four variants' failures cleanly isolated to one dimension each.

## Execution states (cold / warm / ready-cache-hit)

Per `manifest.yaml`'s `execution_states`: these are **external
preconditions** on whatever cache/driver state the implementation under test
maintains — never a change to any file under `repo*/` or to `manifest.yaml`.
This mirrors the pattern `docs/evidence/t0/w1-startup.md` (TF-001.03) used
with `TASKFLOW_DRIVER_CACHE`:

- **cold**: point the implementation's own driver/tool-build cache at a
  fresh, empty location before invoking against `repo/`.
- **warm**: reuse a previously-populated driver/tool-build cache, but with no
  matching result-cache entry for this exact input, so the check still runs.
- **ready-cache-hit**: pre-populate the implementation's result cache with an
  entry matching `repo/`'s current inputs (source content, declared
  conditions, profile) before invoking, so a correct implementation can
  recognize the hit.

No harness exists yet to automate this (that is future Risk Lab / T1 harness
work, e.g. `TF-002.04`'s benchmark runner); this section defines the contract
any such harness must follow when it targets this fixture.

### Ready-cache-hit target: zero worker reservations

`manifest.yaml`'s `ready_cache_hit_target` declares that a ready cache hit
against unmodified `repo/` must perform **zero** worker/environment
reservations. This is a target for a future implementation, not a claim
about today's prototype: `docs/evidence/t0/cache-characterisation.md`
(TF-001.04) already demonstrated the opposite for `prototype/bootstrap` —
its engine always acquires and probes an environment before cache
resolution can complete, even on a guaranteed hit. This fixture's target is
unaffected by that finding; it is exactly what E04's eventual design will be
measured against.

## Evidence: verification commands and results

Environment: [`raw/environment.txt`](raw/environment.txt) — source revision
`7d3c91f`, macOS 26.5.2 arm64, Go 1.25.12.

| Repo | `gofmt -l .` | `go vet ./...` | `go test ./...` | Raw output |
| --- | --- | --- | --- | --- |
| `repo/` | clean | clean | pass | [`raw/repo.log`](raw/repo.log) |
| `repo-format-failure/` | flags `greeter.go` | clean | pass | [`raw/repo-format-failure.log`](raw/repo-format-failure.log) |
| `repo-test-failure/` | clean | clean | **fail** (`TestGreet`) | [`raw/repo-test-failure.log`](raw/repo-test-failure.log) |
| `repo-lint-failure/` | clean | **fails** (`unreachable code`) | pass | [`raw/repo-lint-failure.log`](raw/repo-lint-failure.log) |

Note: `gofmt -l` itself always exits 0 (it only lists non-canonically
formatted files); a real format-check step must turn a non-empty file list
into a failure, exactly as `prototype/bootstrap/Taskfile.yml`'s `fmt:check`
task already does (`test -z "$files"`). This fixture's `format-failure`
variant is verified by `gofmt -l .` printing `greeter.go` (see the raw log),
not by its own exit code.

Reproduce, from `fixtures/w1/<repo-dir>/`:

```sh
gofmt -l .
go vet ./...
go test ./...
```

## Limitations

- Single machine, single OS/arch/toolchain snapshot (macOS/arm64, Go
  1.25.12), matching the T0 evidence tickets' scope.
- The base repo is deliberately trivial (one function, one test) — it is
  sized to make each fault variant unambiguous, not to be representative of
  a real project's format/test/lint surface area or timing.
- This fixture defines no explicit "changed-path" mechanism itself (no
  future implementation exists yet to plan against changed paths); it only
  declares, in `manifest.yaml`'s `planning_conditions`, what a correct
  implementation's re-planning behavior must be when handed this fixture and
  a diff.
- The `expected_graph`'s `check` aggregate node is declared structurally
  (depends_on format/test/lint); no current implementation is asserted to
  produce this exact graph. `prototype/bootstrap/.taskflow/main.go`
  (measured in `docs/evidence/t0/w1-startup.md`) notably does *not* model an
  explicit aggregate node today — this fixture intentionally specifies one,
  since roadmap section 4's W1 diagram shows one explicitly.
- No cross-target, remote, or multi-machine variant exists; W1 is local-only
  per roadmap section 4.

## Open questions

- Whether `t1-experimental-v1` needs a formal versioning/compatibility
  policy beyond "declare a version string" is left to whichever harness
  (e.g. `TF-002.04`'s benchmark runner, or `TF-002.05`'s plan-schema
  conformance harness) first consumes this fixture programmatically.
- Whether additional fault dimensions (e.g. a combined multi-failure
  variant, or a "changed only an unrelated file" no-op variant to test
  planning-condition negatives) are needed is left open for whichever
  experiment first exercises `planning_conditions` against this fixture.
