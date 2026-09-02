# T0 evidence: W1 graph size and project-driver startup

Roadmap tranche: T0. Gate: G0. Workflow: W1. Task: TF-001.03.

Status: measured evidence, not a product claim. This describes the closest
existing prototype fixture to W1 and one machine's cold/warm project-driver
startup timings. It is not a T1 budget-conformance test (T1's budgets, per
roadmap section 8, do not exist yet) and it is not a performance or latency
commitment for the future SDK.

## Representative W1-like graph

The prototype self-hosts its own gate as a compiled project driver at
`prototype/bootstrap/.taskflow/main.go`. This is the closest existing fixture
to W1 ("format check + unit tests + static analysis -> aggregate Check"): it
defines a `check` pipeline with three steps — `format` (`task fmt:check`),
`test` (`task test`), `lint` (`task lint`) — each delegating to the taskfile
runner, and it is the fixture actually invoked through the real
`projectdriver`/`driver` handshake protocol (unlike `examples/basic/main.go`,
which builds and runs its own scheduler in-process and never goes through the
`.taskflow` project-driver discovery/build/handshake path). Because this
ticket measures project-driver startup, the fixture had to be one actually
driven through that protocol, so `.taskflow/main.go` was used rather than
`examples/basic`.

Definition: `prototype/bootstrap/.taskflow/main.go`, lines 16-39 (the `main`
function containing the pipeline declaration and driver wiring).

Counting rule and result:

- Non-comment, non-blank lines in the file: 41 of 46 total lines (0 comment
  lines, 5 blank lines).
- Declared steps (`p.Step(...)` calls): 3 (`format`, `test`, `lint`).
- Declared explicit dependency edges (`flow.Needs(...)`): 0 — the three steps
  are independent and run concurrently (`MaxParallel: 3`); there is no
  separate modeled join/aggregate node. The "aggregate Check" in this fixture
  is the driver's overall run result (non-zero exit if any step fails), not a
  distinct graph node. This is a simpler shape than the roadmap's W1 diagram,
  which shows an explicit aggregate node fed by all three checks — noted as a
  limitation below.

## Project-driver startup: method

The measured unit is `taskflow list`, run from inside `prototype/bootstrap`
against its own `.taskflow` package, using the root `cmd/taskflow` CLI. This
exercises exactly the path `internal/projectdriver.Loader` uses for every
project-driver invocation: `FindRoot` -> `Build` (source-digest lookup in
`TASKFLOW_DRIVER_CACHE`; `go build ./.taskflow` only on a cache miss) ->
`Run` (handshake, then the actual command).

Two modes, using the throwaway helper script
[`raw-w1-startup/benchmark.sh`](raw-w1-startup/benchmark.sh) (bash, outside
`prototype/bootstrap`, removable without any product-code impact):

- **cold**: a fresh, empty `TASKFLOW_DRIVER_CACHE` directory before every
  sample, so `Loader.Build` always misses its own driver-binary cache and
  recompiles `.taskflow` with `go build`. The Go toolchain's own build cache
  (`GOCACHE`) is left warm across these samples (see limitations).
- **warm**: one untimed prewarming invocation populates a fixed
  `TASKFLOW_DRIVER_CACHE`, then every timed sample reuses the cached driver
  binary (`Loader.Build` returns after a single `os.Stat`).

Sample count was declared before running: **N = 15** per mode. Each sample is
the wall-clock real time of one `taskflow list` invocation, from bash's `time`
builtin (`TIMEFORMAT=%R`).

A single additional **GOCACHE-cold anchor** sample was also captured: `go
clean -cache` (Go's own build-object cache) followed by one cold-driver-cache
`taskflow list` invocation. This is reported separately and is **not**
included in the N=15 cold statistics, because clearing `GOCACHE` before every
sample is not representative of normal development use (the toolchain build
cache is essentially always warm on a developer machine) and would make the
benchmark dominated by standard-library/dependency compilation rather than
the project driver itself.

## Results

| Mode | N | Median | p95 | Min | Max | Raw samples |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| cold (driver-cache miss, GOCACHE warm) | 15 | 0.548s | 0.576s | 0.508s | 0.585s | [`raw-w1-startup/cold-samples.txt`](raw-w1-startup/cold-samples.txt) |
| warm (driver-cache hit) | 15 | 0.140s | 0.157s | 0.121s | 0.171s | [`raw-w1-startup/warm-samples.txt`](raw-w1-startup/warm-samples.txt) |
| GOCACHE-cold anchor (single sample, not in the stats above) | 1 | 3.118s | - | - | - | [`raw-w1-startup/gocache-cold-anchor.txt`](raw-w1-startup/gocache-cold-anchor.txt) |

Median/p95 method: samples sorted ascending; median is the statistics-library
median (average of the two middle values for even N, here N is odd so it is
the middle value); p95 is the nearest-rank value at index
`round(0.95 * (N-1))` of the sorted list (index 13 of 0-14 for N=15).

Environment for all samples above: [`raw-w1-startup/environment.txt`](raw-w1-startup/environment.txt).

- Source revision: `9ddea886c7b4e368b5bcd8e48c36a9e2e916cb18`
- OS: macOS 26.5.2, Darwin arm64
- CPU: Apple M5 Max, 18 physical/18 logical cores, 64 GiB RAM
- Go: go1.25.12 darwin/arm64
- mise: 2026.4.28 macos-arm64
- Cache state: `TASKFLOW_DRIVER_CACHE` explicitly controlled per mode as
  described above; `GOCACHE` warm for the cold/warm N=15 runs, explicitly
  cleared only for the single anchor sample.

## Limitations

- Single machine, single OS/arch/toolchain snapshot (macOS/arm64, Go
  1.25.12). No Linux or amd64 measurement was taken.
- This is a bootstrap/prototype-only measurement of `internal/projectdriver`.
  It says nothing about the latency of a future typed authoring SDK, a real
  daemon, or a production plan/cache pipeline — those do not exist yet.
- The fixture's graph shape (3 independent steps, no explicit aggregate join
  node) is simpler than the roadmap's W1 diagram; it is the closest thing
  that exists today, not a claim that this is the final W1 fixture. T1
  (TF-002.01) is expected to freeze a purpose-built W1 fixture.
- `go clean -cache` reported one non-fatal `unlinkat: directory not empty`
  warning on the first attempt (likely a concurrent write into `GOCACHE` from
  an unrelated process); a second `go clean -cache` plus a `du -sh` check
  confirmed the cache directory was reduced to 472K before the anchor sample
  was taken, so the anchor is still a meaningfully cold measurement even
  though it may not be byte-for-byte empty.
- N=15 is a modest sample size chosen to keep this evidence task's runtime
  reasonable; it is sufficient to see a clear, well-separated cold/warm gap
  but not enough to make strong tail-latency claims. T1's benchmark runner
  (TF-002.04) is expected to define a more rigorous sampling and reporting
  contract.
- This baseline must not be read as a performance budget or product
  commitment; T1 (roadmap section 8) defines provisional budgets separately
  and later, against a purpose-built fixture and runner.

## Open questions

- Whether the future W1 fixture (TF-002.01) should model an explicit
  aggregate "Check" join node, and how that changes both graph-size counting
  and startup-path timing, is left to T1.
- Whether project-driver cold-start cost (the ~0.4s gap between cold and warm
  here) is acceptable for a Git-hook-latency product target is a T1/E01
  question, not answered by this baseline.
