# E05 daemon fairness and durable-lease simulation

Roadmap experiment: E05. Ticket: TF-003.12. Risks: R6 and R7.

Status: Phase A contract only. No scheduler, SQLite adapter, benchmark, raw
trace, measured result, scorecard, or selected decision branch exists here.
All formats are experimental and carry no compatibility promise.

## Question

Can shared coordination improve saturated multi-agent scheduling without
oversubscription, starvation, durable-state loss, or unacceptable local
operational cost?

The comparison includes a safe independent-CLI baseline with provider-level
atomic admission. The unguarded independent mode is only a negative control,
so a future shared-daemon result cannot win by being compared with an
intentionally unsafe baseline.

## Phase boundary

Phase A freezes the workload, candidate policies, thresholds, fixture inputs,
and branch precedence before a simulator exists. The frozen decision artifacts
are:

- `contract.json`
- `workload.json`
- `policies.json`
- `thresholds.json`
- `fixture-bindings.json`
- `decision-matrix.json`

`frozen-artifacts.json` records the SHA-256 digest of those artifacts plus this
README, the Taskfile, the verifier, and its tests. `protocol.sha256` records the
digest of that manifest. The two digest files do not include themselves because
a file cannot contain its own cryptographic digest. The verifier also checks
semantic constants, so updating both an artifact and its manifest cannot
silently relax a threshold.

Phase B may start only after this Phase A diff is reviewed, accepted, and
committed with explicit authorization. Phase B will implement the simulator,
disk-backed restart tests, measurements, evidence, and decision. None of those
are permitted in this checkpoint.

## Frozen workload

The primary workload contains 20 agents, split evenly between interactive and
background classes. Each submits W1-, W2-, and W3-shaped work, producing 60
runs. Submission waves intentionally place later interactive work behind
background load. Every client asks for concurrency 32 while fixed shared
capacities remain local 4, Linux 4, macOS 2, simulator 2, and device 1.

Thirty fixed seeds vary only equal-priority tie order. Service durations,
arrival ticks, simulator/device assignment, attachment cases, concurrency
groups, disconnects, and the 60-case durability matrix are all declared in
`workload.json`.

## Frozen gates

Hard safety gates require zero capacity violations, zero leaked leases, and
terminal outcomes for all work not explicitly cancelled or superseded. The
weighted policy must avoid starvation, reach per-class Jain fairness of at
least 0.95, bound maximum ready wait, and improve interactive latency without
unbounded background delay.

A material shared-scheduling result needs at least 15 percent more throughput
or 15 percent less makespan than the safe independent baseline, at least 20
percent lower interactive queue p95, and no material utilization regression.
Durability allows no lost, duplicate, reordered, or spuriously visible event
across 60 fresh-process cases. Cleanup, startup, idle CPU/RSS, stop time, and
operational-shape budgets are explicit in `thresholds.json`.

The decision is mechanical and ordered: stronger state, stop, full daemon,
on-demand daemon, broker-only, then stop/narrow fallback. Thresholds are not
relaxed after results exist.

## Requirement scope

The current product specification defines no `CONC-*` identifiers and only
`DUR-1` through `DUR-3`. The older identifiers in the ticket are stale and are
not recreated. This experiment targets AGENT-2 through AGENT-5, EXEC-2,
EXEC-3, EXEC-5, DUR-1, and DUR-3. AGENT-4 is only partially exercised through
namespace and lease ownership; no filesystem or service isolation is claimed.

## Phase A verification

From the repository root:

```sh
mise exec -- task --dir experiments/e05-daemon-simulation check:phase-a
```

The command checks artifact hashes, live fixture bindings, exact workload and
threshold constants, policy candidates, decision precedence, experimental
version markers, and the absence of Phase B files. Its mutation tests prove
that drift is rejected even when a changed artifact is rehashed.

## Limitations

- This contract contains no experimental result and selects no architecture.
- Simulated ticks will not prove real scheduler timing.
- The later SQLite experiment can test returned commits across process death,
  not hardware power-loss guarantees or a production database API.
- Later idle/startup measurements are simulator operational proxies, not proof
  of packaging, launch-agent integration, authenticated RPC, or migrations.
- W3 remains a specification-only fixture; E05 does not implement native
  macOS, simulator, device, service, or endpoint infrastructure.
