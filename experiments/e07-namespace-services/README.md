# E07 namespace-private services and cross-target endpoints

Roadmap experiment: E07. Ticket: TF-003.15. Risk: R7.

Status: Phase A frozen contract only. No controller, reaper, service process,
listener, database, route, benchmark, raw evidence, selected branch, or E07 ADR
exists in this phase. All formats are experimental and carry no compatibility
promise.

## Question

Can Taskflow reproduce full stacks per worktree while keeping ports, provider
networking, authorization details, and mutable service state out of normal
project code?

The later execution phase will run two barrier-synchronised W3 service subsets.
Each subset requests a Linux-class database/API service and consumes a typed
`Endpoint[API]` from a fake-macOS target. The fake target is allowed by the
roadmap and ticket, but it does not prove real Linux-to-macOS networking.

## Phase boundary

Phase A freezes the workload, candidates, thresholds, event/evidence contract,
and repository bindings before implementation. `frozen-artifacts.json` hashes
every contract file other than itself and `protocol.sha256`; the latter hashes
the manifest. The verifier also checks semantic constants, so rehashing a
relaxed threshold cannot make it valid.

Phase B requires a reviewed and explicitly authorized commit containing this
contract. Plan approval alone does not authorize service processes, listeners,
containers, Compose, external networking, benchmarks, evidence generation, or
the E07 ADR. Any real Compose candidate needs an additional exact preflight and
approval; CLI presence or a static file is not evidence.

## Frozen workload and boundary

The two project-visible requests contain only source identity, `Service[API]`,
`Endpoint[API]`, and an authorized consumer identity. They contain no port,
route, token, path, process, provider option, or mutable database detail.

Phase B is constrained to an experiment-owned temporary root and Python 3.9
standard-library facilities. A narrow controller/reaper may own OS-assigned
loopback ports, child processes, SQLite state, leases, and route adapters. It
must remain disposable experiment code and must not import the prototype or
create production packages.

## Predeclared gates

All gates are hard and unweighted.

| Property | Frozen requirement |
| --- | --- |
| Concurrent isolation | 20 paired trials; zero collisions, peer reads/writes, endpoint exposure, or project-visible route details |
| Authorization | Six denial classes, at least 20 repetitions each; zero success or connection-secret disclosure |
| Readiness | 30 serial starts; health probe then durable `service.ready`; p95 strictly below 1 second |
| Failure drain | Unhealthy or early-exit service drains within 2 seconds |
| Caller loss | TTL 1 second, heartbeat 250 ms, reaper 100 ms; expiry at most 500 ms late |
| Cleanup | 20 trials; after expiry p95 at most 1 second and maximum at most 2 seconds; zero live resources |
| Durable cleanup | Fresh-controller restart immediately before and after each of four cleanup-stage commits |
| Reuse | One immutable API artifact digest may be shared; no database, token, process, route, or mutable identity may be shared |
| Endpoint resolution | 30 serial samples; p95 below 25 ms |
| Fake-macOS relay overhead | 30 alternating paired samples; p95 delta over direct loopback at most 10 ms |

The percentile method sorts samples and selects index
`round(0.95 * (count - 1))`, matching the bound E05 comparison.

## Decision precedence

1. Select `stop-narrow-safety` immediately if any hard isolation,
   authorization, readiness, cleanup, durability, or reuse gate fails.
2. Select `typed-endpoint-manager` if one manager-owned transport-neutral
   mechanism passes every gate for both target classes without project-visible
   provider data.
3. Select `explicit-provider-routing` if typed handles, lifecycle, and
   authorization pass but fake-macOS connectivity requires one declared,
   adapter-hidden provider route capability.
4. Select `compose-style-integration` only if native lifecycle is rejected and
   a separately approved real Compose candidate passes the same gates.
5. Otherwise select `stop-narrow-no-credible-candidate`.

## Evidence required from Phase B

Raw normalized JSONL must cover every paired trial, fault, restart, and timing
sample. Evidence also includes process/listener inventories, collision and leak
reports, the authorization matrix, readiness and cleanup measurements, T1 v2
benchmark records, environment metadata, checksums, implementation/evidence
manifests, a mechanical scorecard, limitations, recommendation, and exact
reproduction command.

Events follow the durable mutation they describe. Route credentials are never
logged; only a SHA-256 digest may appear in retained evidence.

## Requirement scope

The current product specification defines no `NS-*` requirements. `NS-1`
through `NS-5` remain ticket provenance only and are not recreated. The bounded
experiment targets AGENT-4, AGENT-5, and EXEC-5; it partially exercises PLAN-5
and AGENT-6 for endpoint authorization. Fake-target placement is limited EXEC-1
evidence, not a real provider claim.

## Limitations

- W3 remains specification-only until Phase B.
- Same-host loopback and a fake-macOS adapter cannot establish real
  cross-machine routing, tunnel security, VM isolation, or native performance.
- A one-second experimental TTL is a test acceleration, not a product default.
- Local SQLite process-crash behavior does not prove hardware power-loss
  durability or select a production state schema.
- Process, credential, and path checks cannot prove OS network-namespace
  isolation.
- Static typing was established by E01; E07 will exercise an experimental
  runtime type tag and authorization boundary without stabilizing its schema.

## Verification

From the repository root:

```sh
mise exec -- task --dir experiments/e07-namespace-services check:phase-a
```

This command performs only static file, digest, semantic, and mutation checks.
It starts no listener or service and produces no Phase B evidence.
