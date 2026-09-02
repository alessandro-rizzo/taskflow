# T0 gate evidence: reproducible prototype gate

Roadmap tranche: T0. Gate: G0. Task: TF-001.01.

Status: measured evidence, not a product claim. This records one reproduction
of the isolated `prototype/bootstrap` module's format/test/race/vet gate on
one machine at one revision. It does not claim performance, portability, or
future stability.

## Measured facts

### Environment

- Source revision: `9ddea886c7b4e368b5bcd8e48c36a9e2e916cb18` (branch
  `tf-001.01-prototype-gate-evidence`, based on `main`)
- Timestamp: 2026-09-02T19:00:16Z
- OS: Darwin (macOS 26.5.2)
- Architecture: arm64
- Kernel: Darwin Kernel Version 25.5.0
- Go version: go1.25.12 darwin/arm64
- mise version: 2026.4.28 macos-arm64

Raw capture: [`raw/environment.txt`](raw/environment.txt)

### Commands run and results

All commands were run with `mise exec --` inside a trusted mise environment
(`mise trust && mise install`). `go clean -testcache` was run before each
test/race invocation below so the recorded pass is a genuine execution, not a
cached Go test result.

| # | Command | Working directory | Result | Raw output |
| - | --- | --- | --- | --- |
| 1 | `mise exec -- task check` | repo root | exit 0 (pass) | [`raw/root-check.log`](raw/root-check.log) |
| 2 | `mise exec -- task check` | `prototype/bootstrap` | exit 0 (pass) | [`raw/standalone-check.log`](raw/standalone-check.log) |
| 3 | `mise exec -- task fmt:check` | `prototype/bootstrap` | exit 0 (pass) | [`raw/fmt-check.log`](raw/fmt-check.log) |
| 4 | `mise exec -- task test` | `prototype/bootstrap` | exit 0 (pass) | [`raw/test.log`](raw/test.log) |
| 5 | `mise exec -- task test:race` | `prototype/bootstrap` | exit 0 (pass) | [`raw/test-race.log`](raw/test-race.log) |
| 6 | `mise exec -- task lint` (`go vet ./...`) | `prototype/bootstrap` | exit 0 (pass) | [`raw/lint.log`](raw/lint.log) |

Row 1 is the root command documented in `README.md`; it delegates to
`prototype:check`, which in turn runs `task check` inside
`prototype/bootstrap` (`aggregating fmt:check`, `test:race`, `lint` — see
`Taskfile.yml` and `prototype/bootstrap/Taskfile.yml`). Rows 3-6 rerun the
same three gates individually, plus a plain (non-race) `task test`, so
"ordinary tests" have dedicated evidence distinct from the race run.

No package in either the root or standalone run failed, and no formatting or
vet finding was produced.

### Root vs. standalone reproduction consistency

Root-level instructions (`README.md`) and the prototype's own instructions
(`prototype/bootstrap/docs/baseline.md`) both document the same two commands:

```sh
mise trust
mise install
mise exec -- task check
```

run once from the repository root and once from `prototype/bootstrap/`. Both
were executed in this session. The set of exercised packages and their
pass/fail outcome is byte-identical between the two runs after stripping
per-run timing and Go's `(cached)` marker (diff of sorted, timing-stripped
`ok`/`?`/`FAIL` lines: no differences). The root command is confirmed to be a
faithful delegation to the standalone command, not a divergent path.

## Limitations

- Single machine, single OS/arch (macOS/arm64), single Go toolchain version.
  No Linux or amd64 reproduction was captured in this task.
- This is one point-in-time snapshot at revision `9ddea88`. It does not by
  itself prove the gate stays green over time; that is a CI/process concern
  outside T0 scope.
- `go vet` and `gofmt -l` were run through the Taskfile's `lint`/`fmt:check`
  wiring rather than any additional static analyzers; the gate's coverage is
  exactly what `prototype/bootstrap/Taskfile.yml` defines, no more.
- Benchmark-style timing (latency, throughput) is out of scope here; see
  TF-001.03 for W1 graph/startup measurements.

## Open questions

- None block G0 for this ticket: every evidence-to-capture item this ticket
  owns (source revision, OS, architecture, Go version, exact commands,
  timestamp, formatting/race/ordinary-test/vet results, raw-output location,
  root/standalone consistency) has a reproducible artefact above, and no
  failure occurred that would need to be preserved as a G0 blocker.

## Reproduction

From a clean checkout at revision `9ddea88` (or later, noting drift):

```sh
mise trust
mise install
mise exec -- task check
```
