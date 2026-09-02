# Taskflow risk-first development roadmap

Status: proposed

Date: 2026-08-26

Owner: Taskflow maintainers

## 1. Purpose

This roadmap develops Taskflow from a clean foundation while preserving the
existing implementation as an isolated prototype. It is ordered by uncertainty
and cost of being wrong, not by the apparent dependency order of product
features.

The previous architecture-bootstrap implementation proved that Taskflow can
build a compiled Go DAG, resolve runner adapters, schedule parallel work,
journal transitions, restore content-addressed artifacts, resume compatible
runs, and execute through local and SSH-shaped target contracts. It did not
prove the higher-risk product claims:

- that a typed Go project API can be both concise and agent-discoverable;
- that Go project code can safely produce plans for a privileged daemon;
- that reproducibility without mandatory containers can be enforced cheaply;
- that execution identity can be known early enough to avoid provisioning on
  cache hits;
- that a shared daemon materially improves concurrent agent workflows;
- that per-worktree stacks can be isolated without excessive provisioning;
- that native macOS/Xcode and simulator work can use warm immutable capacity
  without state contamination or unacceptable latency.

Those questions are addressed before a new production architecture is allowed
to accumulate. The prototype is evidence, not a compatibility constraint.

## 2. Roadmap principles

### 2.1 Buy information before infrastructure

The earliest work should reduce a major uncertainty or falsify a product
hypothesis. A polished daemon, provider SDK, web UI, or module ecosystem is
waste if the authoring model or reproducibility contract is wrong.

### 2.2 Make branch decisions explicit

Every risky experiment defines at least three outcomes:

- **continue:** evidence supports the preferred architecture;
- **pivot:** the product goal remains valid but needs a different mechanism;
- **stop or narrow:** the cost or limitation undermines the product thesis and
  scope must be reduced before more implementation.

Passing means satisfying a threshold chosen before implementation, not merely
producing a demo.

### 2.3 Keep experiments disposable

Experiment code lives under `experiments/`, has no production consumers, and
does not become the new kernel by accident. A successful concept is specified
in an ADR and reimplemented or deliberately promoted with tests.

### 2.4 Deliver vertical slices after convergence

Once the highest risks have converged, each implementation tranche produces a
usable end-to-end release: discovery through plan, local execution through
artifact, daemon through detached agent run, stack through E2E test, and remote
placement through resume.

### 2.5 Preserve one semantic model

Human CLI, agent API, Git hooks, local execution, remote execution, native
mobile targets, and future authoring SDKs must consume the same schema and plan
semantics. Short-term adapters may differ; graph meaning may not.

### 2.6 Defer compatibility until the model earns it

Before the first public alpha, state, plan, cache, provider, and SDK formats may
change incompatibly. Each format is versioned from the beginning, but a
migration promise starts only when explicitly documented.

## 3. Repository and code-lifecycle policy

```text
docs/                         canonical product decisions and roadmap
experiments/eNN-*/            disposable, question-specific evidence
fixtures/                     frozen, reusable T1+ measurement fixtures and harnesses
prototype/bootstrap/          frozen previous implementation
cmd/, internal/, pkg/         future clean implementation after Gate 1
```

Rules:

1. New production packages must not import `prototype/bootstrap`.
2. Prototype code changes only to preserve reproducibility, correct evidence,
   or support an explicitly named comparison.
3. Experiments do not share a convenience framework until at least two
   experiments prove the same abstraction is actually common.
3a. `fixtures/` holds T1+ measurement fixtures and harnesses that multiple
    Risk Lab experiments reuse repeatedly and that stay frozen once accepted;
    unlike `experiments/`, entries here are not disposable, and each declares
    an explicit experimental version. New production packages must not import
    `fixtures/` either; a fixture graduates the same way an experiment does,
    per rule 4.
4. A concept enters production only with an accepted decision record, an owner,
   tests, and a removal/migration plan for any superseded experiment.
5. Root `task check` verifies all maintained production code and the isolated
   prototype. Each experiment exposes its own verification command while
   active.
6. Generated benchmark data and large VM/CAS artifacts remain outside Git;
   manifests, scripts, summarized results, and checksums are committed.

## 4. Reference workflows

Every material architectural decision is tested against the same three
workflows. Toy “echo” graphs may validate mechanics but cannot pass a product
gate.

### W1: fast project check

Purpose: validate ordinary local ergonomics and cache latency.

Shape:

```text
immutable source
   +-> format check
   +-> unit tests -> test report
   +-> static analysis
                 \-> aggregate Check
```

Required properties:

- one concise public operation;
- inferred typed dependencies;
- deterministic machine-readable schema and plan;
- planning conditions based on changed paths;
- cache hit without worker acquisition;
- human output and JSON events;
- local warm path fast enough for a Git hook.

### W2: cross-target artifact pipeline

Purpose: validate identity, transfer, remote placement, failure, and resume.

Shape:

```text
source -> Linux build -> Artifact[BackendBinary]
                      -> Linux tests -> Report[GoTests]
                      -> local package/inspection
```

Required properties:

- execution profile known before placement;
- artifact manifest verified across targets;
- a failed downstream node resumes on another compatible worker;
- successful work is not repeated;
- provider outage and cancellation produce durable, explainable state.

### W3: isolated native-mobile stack

Purpose: validate Taskflow's main differentiation from container-only systems.

Shape:

```text
source -> Linux database/API stack -> Endpoint[API]
source -> macOS Xcode build ---------> Artifact[IOSApp]
Endpoint + IOSApp + simulator -------> Report[MobileE2E]
```

Required properties:

- two worktree/agent namespaces run concurrently without data or port collision;
- Linux-to-macOS endpoint routing is explicit and authorized;
- macOS profile and simulator identity are attested;
- warm infrastructure is reused without sharing semantic state;
- cleanup survives cancellation and caller loss.

## 5. Risk register

Scores are initial estimates from 1 (low) to 5 (high). `Exposure` is
probability multiplied by impact. A high exposure and high downstream rework
cost moves the experiment earlier.

| ID | Uncertain claim | Probability | Impact | Exposure | Rework if learned late | Earliest evidence |
| --- | --- | ---: | ---: | ---: | --- | --- |
| R1 | Go can provide a concise typed project API | 4 | 5 | 20 | Entire public SDK and module model | E01 |
| R2 | Project APIs can emit stable language-neutral schema/plan IR | 4 | 5 | 20 | Daemon, cache, SDK, and protocol rewrite | E01/E02 |
| R3 | Arbitrary compiled project code can be safely separated from daemon authority | 4 | 5 | 20 | Security boundary and deployment model | E03 |
| R4 | Lightweight native/VM sandboxes can enforce useful reproducibility at acceptable latency | 4 | 5 | 20 | Worker, cache, and local UX redesign | E04/E06 |
| R5 | Profile identity can be resolved before worker acquisition | 3 | 5 | 15 | Cache and provider contract rewrite | E04 |
| R6 | A shared daemon improves agent throughput without becoming an operational burden | 3 | 4 | 12 | CLI, state, scheduling, and lifecycle rewrite | E05 |
| R7 | Namespace-private stacks and endpoints are simpler than current ad hoc orchestration | 3 | 4 | 12 | Service/network model rewrite | E07 |
| R8 | Warm macOS VMs and simulators can be reset reliably and quickly | 4 | 5 | 20 | Native-mobile product promise | E06 |
| R9 | A provider-neutral worker protocol survives local, Linux, and macOS shapes | 3 | 5 | 15 | All remote providers | E04/E06/E08 |
| R10 | Conditions and optional typed outputs remain understandable | 3 | 3 | 9 | Plan/value API churn | E01/E02 then T8 |
| R11 | Policies can constrain agent-authored plans and effects | 3 | 5 | 15 | Trust model and daemon rewrite | E03 then T8 |
| R12 | Taskfile leaf migration is materially easier than a rewrite | 2 | 4 | 8 | Adoption positioning | W1/W2 dogfood |

The register is reviewed at every gate. A new risk with exposure 15 or greater
preempts feature work until it has an experiment or an accepted mitigation.

## 6. Programme map

```text
T0 repository reset and evidence baseline
                    |
                    v
T1 measurement contracts and fixtures
                    |
                    v
+---------------- Risk Lab ----------------+
| E01 authoring + schema                    |
| E02 deterministic plan IR                |
| E03 planning trust boundary              |
| E04 source/sandbox/cache identity         |
| E05 daemon/fairness simulation            |
| E06 macOS VM/simulator feasibility        |
| E07 namespace/service routing             |
| E08 remote worker protocol                |
+-------------------------------------------+
                    |
                 Gate 1
       +------------+-------------+
       |            |             |
 Go-first SDK   second-SDK    narrow/pause
 native sandbox    spike       product thesis
 warm macOS VM  alternative
       +------------+-------------+
                    |
                    v
T2 clean semantic foundation and local planner
                    |
                    v
T3 reproducible local execution and result cache
                    |
                    v
T4 shared daemon and agent lifecycle
                    |
                    v
T5 namespaces, services, and isolated stacks
                    |
                    v
T6 remote Linux vertical slice
                    |
                    v
T7 native macOS/mobile vertical slice
                    |
                    v
T8 triggers, conditions, effects, and policy
                    |
                    v
T9 alpha dogfood -> T10 beta hardening -> v1 decision
```

The Risk Lab experiments may run in parallel once T1 fixes their measurement
contracts. The implementation tranches after Gate 1 are sequential by default;
small independent work can overlap only when it does not force an undecided
contract.

## 7. T0: repository reset and prototype baseline

Purpose: create a clean decision environment without discarding working
evidence.

### Scope

- isolate the previous implementation under `prototype/bootstrap`;
- retain its module, tests, toolchain, project driver, examples, and historical
  documentation;
- establish `docs/` as product truth and `experiments/` as disposable work;
- ensure root commands continue to verify maintained code;
- record the exact prototype commit and baseline behavior.

### Evidence to capture

- full prototype test/race/vet result;
- package and interface inventory;
- W1-like dogfood graph definition size;
- warm and cold project-driver startup;
- cache-hit and cache-miss path ordering;
- local concurrency and filesystem interference behavior;
- known correctness findings from the Fable review;
- explicit list of concepts proven, unproven, and disproven.

### Exit gate G0

T0 passes when:

- the prototype builds and tests from its isolated directory;
- no new root production package imports the prototype;
- root documentation clearly distinguishes product proposals from prototype
  facts;
- baseline measurements and commands are reproducible;
- future experiment IDs and owners are assigned.

If isolation breaks the prototype, fix layout/build assumptions before any new
architecture work. A prototype that cannot be reproduced is weak evidence.

## 8. T1: measurement contracts and representative fixtures

Purpose: prevent experiments from declaring success against convenient toy
cases.

### Deliverables

1. Minimal repositories or frozen fixture trees for W1, W2, and W3.
2. A benchmark runner recording hardware, OS build, toolchain, cold/warm state,
   sample count, median, p95, and raw result location.
3. A plan-schema conformance harness with deterministic golden fixtures.
4. Fault injectors for process crash, daemon restart, worker loss, corrupt
   artifact, cancellation, lease expiry, and source mutation.
5. A malicious-planner fixture that attempts filesystem, environment, network,
   process, resource, and output abuse.
6. Initial performance budgets, explicitly marked provisional.

### Initial budgets

These are decision thresholds, not marketing promises:

- cached project discovery: p95 below 150 ms;
- cached plan for W1: p95 below 250 ms;
- W1 cache hit after planning: p95 below 300 ms and zero worker reservations;
- local lightweight sandbox creation: warm p95 below 250 ms;
- warm remote Linux sandbox admission: p95 below 2 seconds, excluding queueing;
- warm macOS workspace/sandbox creation: p95 below 3 seconds;
- warm macOS simulator ready-to-install: p95 below 15 seconds;
- no cross-namespace writable path or service endpoint in isolation tests;
- deterministic plan fixture byte-equivalent after canonical encoding;
- no lost durable event after injected daemon restart.

Budgets may change at G1 only with recorded evidence. A threshold is not relaxed
merely because the first implementation misses it.

### Exit gate

T1 passes when every Risk Lab experiment can run against a representative
fixture, report comparable results, and distinguish cold, warm, and cache-hit
paths.

## 9. Risk Lab experiments

### E01: typed authoring and schema ergonomics

Question: can Go express Taskflow's project API naturally while producing a
complete agent-discoverable schema?

Competing approaches:

- A: generic typed values plus explicit typed operation registration;
- B: generic values plus code generation from Go declarations;
- C: reflection-heavy registration;
- D: a minimal TypeScript comparison that emits the same provisional schema.

Build only enough to express W1, the build/artifact half of W2, and the public
surface of W3. Execution may be fake.

Measure:

- authored project lines and concepts visible at each abstraction layer;
- compile-time rejection of incompatible artifacts/endpoints;
- schema completeness without running operation bodies;
- diagnostics for invalid arguments and graph construction;
- cold/warm driver build and discovery latency;
- agent success on discover, edit, and invoke tasks using schema alone;
- amount of reflection, generated code, and user annotations.

Continue criteria:

- common W1 project code is materially shorter and clearer than equivalent
  low-level `flow.Step` definitions;
- typed misuse fails before execution;
- schema describes arguments, defaults, enums, outputs, effects, and
  capabilities without evaluating privileged work;
- warm discovery meets T1 budget;
- at least two independent agent attempts use the schema without reading the
  implementation.

Branches:

- **A wins:** make explicit Go registration the first SDK contract.
- **B wins:** accept code generation and define generator/version ergonomics
  before foundation work.
- **C only works:** stop and redesign; reflection must not be the sole source of
  stable protocol identity.
- **Go authoring fails but schema succeeds:** keep Go core, freeze only schema
  concepts, and run a time-boxed TypeScript SDK experiment before T2.
- **Typed API adds little over recipes:** narrow Taskflow to an execution engine
  or stop; do not build a module ecosystem around cosmetic typing.

### E02: deterministic language-neutral plan IR

Question: can authored operations lower to a canonical plan that contains no Go
runtime values and is sufficient for independent execution and explanation?

The plan fixture must include typed artifacts, optional outputs, a planning
condition, an outcome condition, resource requirements, execution profile,
cache policy, secret capability reference, service endpoint, and an effect.

Tests:

- repeated generation across processes produces the same canonical digest;
- declaration reordering that is semantically irrelevant does not alter the
  structural digest;
- meaningful condition/profile/output changes do alter it;
- an independent reader with no Taskflow Go imports validates and displays the
  plan;
- unknown fields and protocol versions fail according to explicit rules;
- plan size and generation time remain practical for a large synthetic graph;
- resume-compatibility differences are explainable field by field.

Branches:

- **Canonical JSON is sufficient:** use it for early driver/daemon protocol and
  retain freedom to change transport later.
- **Canonicalization is fragile:** use a schema-first binary protocol or
  canonical CBOR/Protobuf representation, with a JSON diagnostic projection.
- **Plan cannot express runtime-dependent graph shape:** separate static plan
  from bounded dynamic expansion; do not give arbitrary daemon callbacks to
  project code.
- **Language neutrality requires weakening types:** revise value/schema design
  before T2.

### E03: project-planner trust boundary

Question: can compiled project code emit a plan without inheriting the daemon's
filesystem, credentials, network, or authority?

Attack fixture attempts:

- reading repository-external files and process environment;
- opening network connections and local sockets;
- spawning descendants that outlive planning;
- exhausting CPU, memory, file descriptors, output, and wall time;
- embedding secret material or unsafe paths in plan fields;
- exploiting parser/version ambiguity;
- requesting privileged targets, networks, secrets, and effects.

Approaches to compare:

- restricted native subprocess with OS sandbox controls;
- a reusable minimal planning sandbox/container;
- a microVM only where native controls are insufficient;
- a declarative/code-generated registration path that executes less project
  code during discovery.

Continue criteria:

- the planner receives only an immutable selected source view and declared
  inputs;
- every malicious fixture is blocked, bounded, or explicitly classified as a
  trusted-local limitation;
- the daemon validates and authorizes the emitted plan independently;
- no daemon/provider/secret credential enters the planner;
- warm planning meets its latency budget.

Branches:

- **Native sandbox is adequate:** use it for local trusted and agent planning.
- **Container is required for planning:** pool it so provisioning is not on the
  warm path; this does not force containers for task execution.
- **Strong local isolation is unavailable on macOS:** use a helper VM for
  untrusted agent-authored planning and allow an explicit trusted-local mode.
- **No acceptable boundary:** remove arbitrary executable planning from the
  agent threat model and use generated/static descriptors for untrusted runs.

### E04: immutable source, lightweight sandbox, and cache identity

Question: can Taskflow provide useful isolation and compute result identity
before provisioning without making local execution feel slow?

Approaches:

- immutable Merkle/CAS source plus copy-on-write local workspace;
- Linux namespace/overlay sandbox;
- macOS APFS clone/sandbox controls;
- pooled container or microVM fallback;
- declared immutable execution profile with worker attestation.

Required demonstrations:

1. Mutating the source worktree after run creation does not affect execution.
2. Two concurrent W1 runs cannot observe each other's writable outputs.
3. Undeclared source paths and environment values are denied or detected at the
   requested reproducibility level.
4. Cache identity is computed from source, inputs, process, profile, policy, and
   dependency manifests before any worker reservation.
5. A cache hit performs zero provider reservations/acquisitions.
6. A worker with mismatched profile attestation is rejected rather than
   silently creating a different cache key.
7. Result cache, tool cache, and warm worker state are demonstrably distinct.

Branches:

- **Native lightweight sandbox meets isolation and latency:** make it the local
  default.
- **Native sandbox is fast but incomplete:** expose attained reproducibility
  honestly and reserve stronger VM/container modes for stricter operations.
- **Only pooled containers meet the contract:** use them for reproducible Linux
  nodes while retaining native providers where containers are impossible.
- **Profile identity cannot be known before acquisition:** redesign profiles
  and provider attestation; do not carry the prototype's probe-before-cache
  ordering into T2.
- **No local option meets hook latency:** keep planning/cache hits local and
  dispatch misses to a warm worker pool; reconsider local-miss defaults.

### E05: daemon, fairness, and durable lease simulation

Question: is a shared daemon necessary and can it coordinate many agents
without excessive operational complexity?

Build a scheduler simulation with fake local, Linux, macOS, simulator, and
device providers. Do not execute real builds.

Scenarios:

- 20 agents submit mixed W1/W2/W3-shaped plans;
- each client independently asks for high concurrency;
- interactive work competes with background work;
- macOS and device capacity saturates;
- daemon restarts during admission, execution, and cleanup;
- clients disconnect without cancellation;
- identical active requests attempt authorized attachment;
- concurrency groups queue, supersede, or cancel work.

Measure:

- resource oversubscription (must be zero);
- starvation and queue-time distribution;
- state/event loss after restart (must be zero for committed transitions);
- orphan detection and cleanup latency;
- complexity of running/installing/upgrading the daemon;
- throughput compared with independent CLI schedulers.

Branches:

- **Shared daemon materially improves utilization:** make it the default after
  the local vertical slice.
- **Daemon benefits only multi-agent use:** keep a compatible in-process mode
  and start the daemon on demand.
- **SQLite cannot safely express leases/events:** choose a stronger local state
  model before T4, not a distributed database by reflex.
- **Operational cost exceeds benefit:** narrow the daemon to a resource broker
  while keeping run execution client-owned.

### E06: macOS VM, Xcode, and simulator feasibility

Question: can Taskflow make native mobile work reproducible and fast enough to
be a first-class differentiator?

Run this experiment early even though the full provider comes later. It tests
the product promise, not an implementation dependency.

Compare where available:

- warm Tart/Orchard-style VM restored from an immutable image;
- one warm clean VM with APFS-cloned workspaces;
- one VM per run or per namespace;
- trusted native host execution with strict workspace/session reset;
- simulator clone/reset versus fresh boot.

Record:

- base image digest, macOS build, Xcode build, SDKs, simulator runtime, and
  runner identity;
- cold boot, warm acquire, workspace clone, simulator-ready, build, install,
  test, reset, and cleanup distributions;
- state contamination tests across namespaces;
- maximum safe concurrency per host;
- image distribution/update cost;
- failure recovery after VM or simulator loss.

Branches:

- **Warm VM + cloned workspace meets budgets:** build the future macOS provider
  around reusable workers and disposable sandboxes.
- **VM is reliable but per-node overhead is high:** use a VM per namespace/run
  with per-node workspaces and explicit sessions.
- **Native host is the only practical warm path:** classify it as trusted and
  use host snapshots/reset plus strong provenance rather than claiming
  hermeticity.
- **Remote macOS cannot meet latency/correctness:** integrate an external macOS
  runner as a coarse target and defer first-class native execution.
- **No approach isolates concurrent agents:** serialize macOS by namespace and
  reassess whether W3 remains a primary product goal.

### E07: namespace-private services and cross-target endpoints

Question: can Taskflow reproduce full stacks per worktree without exposing
ports, provider networking, and mutable state in normal project code?

Build two simultaneous W3 service subsets with separate databases and API
instances. Consume each endpoint from a different target class, using a fake
macOS consumer if necessary.

Continue criteria:

- no fixed host-port coordination in project code;
- endpoint handles are typed and authorization-aware;
- service names, volumes, and data are namespace-private;
- health and readiness are durable state rather than sleeps;
- cleanup and TTL reclaim all resources after client loss;
- immutable service build artifacts may be reused without sharing mutable data;
- routing overhead and diagnostics are acceptable.

Branches:

- **Typed endpoint manager works:** graduate `Service`, `Endpoint`, and `Stack`
  concepts after the daemon foundation.
- **Cross-target networking is provider-specific:** retain typed endpoints but
  make routing an explicit provider capability.
- **Full stack lifecycle is too broad:** integrate Compose or another service
  manager behind one typed service leaf before building native lifecycle.

### E08: minimal remote worker protocol

Question: what is the smallest protocol that survives both remote Linux and the
macOS shapes discovered by E06?

The spike implements only:

- capability/profile advertisement;
- non-blocking reservation;
- profile attestation;
- sandbox/session creation;
- CAS source/artifact materialization;
- command execution, logs, cancellation, and exit status;
- output publication and bounded cleanup;
- reconnect and orphan query.

Test the protocol with an in-process fake, one SSH-backed Linux worker, and a
macOS adapter stub shaped by E06. Do not add provider-specific universal option
maps.

Branches:

- **One protocol fits with typed capability extensions:** freeze only the
  proven core for T6.
- **macOS sessions distort stateless Linux execution:** separate worker,
  sandbox, and session protocols rather than widening one environment object.
- **Transport concerns dominate semantics:** specify the state machine first
  and postpone gRPC/Connect/HTTP encoding choice.

## 10. Gate 1: product and architecture convergence

No new production kernel begins until E01-E06 have decisions. E07 and E08 may
finish shortly after if their outcomes do not affect the first local slice.

Gate 1 produces accepted ADRs for:

- authoring SDK shape and schema derivation;
- typed value and optional-output semantics;
- language-neutral plan and condition IR;
- planner trust boundary;
- source snapshot and reproducibility levels;
- execution profiles and pre-provision identity;
- worker versus sandbox versus session lifecycles;
- daemon responsibility and local state model;
- macOS/native feasibility branch.

### Continue decision

Continue into the clean foundation when:

- Go authoring or an approved alternative is measurably concise;
- an agent can discover and plan without reading implementation source;
- plan identity is deterministic and language-neutral;
- planner authority is bounded acceptably;
- immutable local execution and cache-before-provision are feasible;
- at least one credible native-mobile execution branch remains;
- no unresolved risk with exposure 20 lacks a bounded mitigation.

### Pivot decision

Possible coherent pivots include:

- Go core with TypeScript-first authoring;
- container-backed reproducible Linux with native VM macOS profiles;
- on-demand daemon only for multi-agent/service workloads;
- coarse external macOS target while native provider work is deferred;
- Taskflow as typed execution engine without owning service lifecycle.

Each pivot updates the product specification before implementation resumes.

### Stop or narrow decision

Pause broad product development if:

- typed project values do not improve real authoring or agent behavior;
- secure planning requires latency/operations incompatible with local use;
- cache identity cannot be known independently of mutable workers;
- native mobile execution cannot be isolated or made operationally credible;
- the product is no more useful than Taskfile plus a remote job queue for W1-W3.

Stopping a branch is a successful Risk Lab outcome when it prevents a costly
wrong architecture.

## 11. T2: clean semantic foundation and local planner

Target release: `v0.1-plan`

Purpose: implement only the semantic model that passed Gate 1.

### In scope

- new root Go module and CLI skeleton;
- typed Go operation registration;
- core value handles selected at G1;
- project schema emission;
- canonical plan and condition IR;
- structural/definition digests;
- plan validation and explanations;
- restricted project-driver planning path;
- `taskflow api`, `describe`, and `plan` in human and JSON modes;
- W1 planning with fake execution.

### Explicitly out of scope

- real daemon;
- remote providers;
- services and stacks;
- durable execution/resume;
- production cache/CAS;
- release effects;
- multiple authoring SDKs unless G1 selected that branch.

### Required tests

- compile-time typed misuse fixtures;
- schema and plan golden tests;
- canonical digest property tests;
- malicious planner suite from E03;
- large-graph performance test;
- CLI/JSON compatibility tests;
- independent language-agnostic plan-reader fixture.

### Exit gate G2

- W1, W2, and W3 public surfaces plan without real infrastructure;
- agents complete discover/plan tasks using JSON only;
- all capability/effect requests are visible before execution;
- no production package imports prototype or experiment code;
- public API churn is still permitted and documented.

## 12. T3: reproducible local vertical slice

Target release: `v0.2-local`

Purpose: make W1 genuinely better than invoking an aggregate local recipe.

### Deliverables

- immutable `SourceView` snapshot and local CAS;
- local worker and disposable sandbox implementation selected at G1;
- process runner and Taskfile/Just/direct-command leaf adapters;
- result artifact manifests and safe materialization;
- result cache lookup before worker reservation;
- separate tool-cache and warm-worker policies;
- append-only durable run journal;
- cancellation, retries, bounded cleanup, and local resume;
- cache, placement, skip, and resume explanations;
- line-oriented terminal and JSONL events;
- `run`, `status`, `watch`, `cancel`, and `resume` in foreground mode.

### Migration slice

Adopt one real repository check using Taskfile leaves. Apply one-owner-per-edge:
keep an aggregate opaque initially, then expose only the edges that benefit from
independent cache, placement, or diagnostics.

### Failure tests

- controller process killed at every durable transition;
- source modified during execution;
- artifact corruption and partial write;
- sandbox cleanup failure;
- dependency reset after missing output;
- tool-cache contamination attempt;
- mismatched execution-profile attestation;
- signal cancellation with child process tree.

### Exit gate G3

- W1 meets planning, sandbox, and cache-hit budgets;
- a cache hit reserves no worker;
- concurrent runs have no writable workspace collision;
- resume never trusts a missing/corrupt artifact;
- Taskflow is faster or substantially more explainable than the equivalent
  aggregate recipe on the measured warm path.

If W1 is slower without compensating correctness/diagnostic value, stop before
building the daemon and fix the local product.

## 13. T4: shared daemon and agent lifecycle

Target release: `v0.3-agent`

Purpose: remove the local host and independent CLI schedulers as multi-agent
bottlenecks.

### Deliverables

- authenticated per-user `taskflowd` with on-demand startup;
- versioned local RPC selected by evidence;
- SQLite or selected durable state implementation;
- detached runs and resumable event cursors;
- global CPU, memory, disk, and provider resource accounting;
- fair queueing between interactive and background agents;
- idempotent create/cancel/resume operations;
- concurrency groups and supersession policies;
- namespace and lease records, heartbeat, TTL, and reaper;
- CLI fallback or clear failure mode when daemon is unavailable;
- installation, upgrade, diagnostic, and clean shutdown paths.

### Agent acceptance test

At least four independent agent processes must concurrently:

1. discover operations;
2. plan against distinct worktree snapshots;
3. detach runs;
4. follow JSONL logs from cursors;
5. cancel one run;
6. survive one agent and one daemon restart;
7. remain within global configured resources.

### Exit gate G4

- zero resource oversubscription in the E05 suite;
- no committed transition/event loss after restart;
- abandoned runs and sandboxes are reclaimed within policy;
- daemon installation and idle overhead fit published local budgets;
- agents never need to scrape human terminal output.

## 14. T5: namespaces, services, and isolated stacks

Target release: `v0.4-stack`

Purpose: reproduce the runtime part of W3 independently for each worktree.

### Deliverables

- typed `Service[T]`, `Endpoint[T]`, and `Stack[T]` values selected after E07;
- lazy service start and durable health/readiness state;
- namespace-private names, ports, routes, volumes, and mutable data;
- typed endpoint injection into consumers;
- explicit placement affinity versus stateful session distinction;
- stack retain/release controls with TTL;
- diagnostics collection during bounded finalization;
- Compose or provider adapter if E07 chose integration rather than native
  lifecycle;
- artifact reuse for immutable service builds without mutable-state sharing.

### Exit gate G5

- two W3 stack subsets run concurrently with zero port/data collision;
- no project API parses connection details from logs;
- client and daemon loss are recovered or cleaned up deterministically;
- a retained stack accelerates an iterative agent run while remaining private;
- service lifecycle is simpler to author than equivalent ad hoc scripts.

## 15. T6: remote Linux vertical slice

Target release: `v0.5-remote`

Purpose: move W2 work off the local machine without changing its project API.

### Deliverables

- production implementation of the E08 worker protocol;
- one real remote Linux provider chosen for learning value;
- immutable profile resolution and worker attestation;
- warm worker pool and disposable sandbox lifecycle;
- CAS delta transfer, output publication, logs, cancellation, and reconnect;
- provider capacity refresh outside scheduler critical path;
- secrets and outbound-network capability injection;
- optional remote artifact/cache store;
- worker quarantine and orphan reconciliation.

The first provider is selected to falsify the protocol, not maximize provider
coverage. A second fake or local provider must still exercise the same contract.

### Exit gate G6

- W2 runs locally or remotely from the same plan;
- ready cache hits wake or create no remote worker;
- downstream failure resumes on another compatible worker without repeating
  valid successful work;
- transfer corruption, disconnect, and provider outage tests pass;
- local resource use falls materially when remote placement is selected;
- no provider-specific field leaks into common project modules.

## 16. T7: native macOS and mobile vertical slice

Target release: `v0.6-mobile`

Purpose: implement the branch selected by E06 and complete W3.

### Deliverables for the preferred warm-VM branch

- macOS provider backed by immutable VM images;
- macOS/Xcode/SDK/simulator execution-profile attestation;
- warm VM pool and APFS-cloned/disposable workspaces;
- explicit simulator/device session leases;
- install, test, cancellation, reset, and diagnostics lifecycle;
- cross-target endpoint routing from Linux stack to macOS consumer;
- finite-resource scheduling and host concurrency limits;
- VM/image update and rollback procedure;
- provenance distinguishing build content from signing/notarization envelope.

If E06 selected another branch, this tranche implements its documented
equivalent rather than forcing the preferred design.

### Exit gate G7

- W3 runs end to end for two concurrent namespaces or the documented serialized
  capacity model;
- no simulator, workspace, credential, or service data leaks between runs;
- warm-path latency meets the selected branch budget;
- VM/simulator loss produces durable recoverable state;
- the public W3 API is unchanged by Linux/macOS placement details;
- attained reproducibility is reported honestly rather than labelled hermetic
  by assumption.

## 17. T8: triggers, conditions, effects, and policy

Target release: `v0.7-policy`

Purpose: make the same operations safe across local hooks, agents, CI events,
and controlled external mutations.

### Deliverables

- normalized manual, agent, Git-hook, push/PR, cron, and webhook triggers;
- `Worktree`, `GitIndex`, `GitRange`, and exact `Commit` source views;
- planning and outcome condition IR with `true`, `false`, and `unknown`;
- durable `skipped` state and `Optional[T]` consumption rules;
- bounded engine-managed `Finally`;
- daemon-enforced target, network, secret, device, quota, and effect policy;
- opaque secret resolution and log/artifact leak defenses;
- `Effect[T]` with exact inputs, actor, authorization, idempotency, and
  reconciliation;
- Lefthook front-door integration;
- minimal GitHub Actions adapter that invokes the same operation.

### Security/failure gate G8

- untrusted agent modifications cannot grant capabilities to themselves;
- pre-commit tests the staged index, not unrelated worktree state;
- unknown validation conditions run safely, while unknown effect authorization
  fails closed;
- skipped producers never expose normal artifact handles;
- secret values appear in none of plan, state, cache, artifacts, or persisted
  logs in the adversarial suite;
- uncertain external-effect outcomes reconcile before retry.

## 18. T9: alpha dogfood and migration

Target release: `v0.8-alpha`

Purpose: prove sustained value on real heterogeneous work before stabilizing
extension contracts.

### Dogfood scope

- one mixed Go/Gradle/Xcode repository;
- W1 as the normal local check and Lefthook gate;
- W2 for remote Linux capacity;
- W3 for at least one native mobile E2E path;
- at least two concurrent coding agents over separate worktrees;
- one approval-gated, uncacheable external effect;
- progressive Taskfile leaf migration with no duplicated edge ownership.

### Operate for an evidence window

Collect at least several weeks of:

- cache hits/misses and explanations;
- cold/warm/local/remote latency distributions;
- daemon/worker/provider failures and recovery;
- namespace collisions or orphan cleanup;
- agent discovery/plan/run errors;
- authoring changes needed as workflows evolve;
- macOS capacity utilization and contamination results;
- security/policy denials and false positives.

### Exit gate G9

- Taskflow is the routine path rather than a side-by-side demo;
- no correctness incident is attributable to an invalid cache hit or hidden
  mutable dependency;
- agents operate through structured APIs without bespoke repository prompting;
- measured remote work relieves the local bottleneck;
- module and provider interfaces have survived at least two implementations;
- remaining high-exposure risks have owners and bounded plans.

## 19. T10: beta hardening and v1 decision

Target release: `v0.9-beta`, followed by an explicit v1 go/no-go decision.

### Deliverables

- schema migration registries and compatibility matrix;
- durable-state backup, recovery, and migration tooling;
- cache/artifact retention, garbage collection, and quotas;
- provider compatibility suite;
- extension/module versioning policy;
- installation, upgrades, rollback, and diagnostic bundles;
- OpenTelemetry and CI status export;
- performance regression suite tied to W1-W3 budgets;
- threat model, security review, and secret-handling audit;
- cross-platform packaging and signed releases;
- contributor documentation and stable public examples.

### v1 go criteria

- public Go SDK and plan semantics are stable enough for a documented
  compatibility window;
- local, Linux, and selected native-mobile paths have production evidence;
- resume and cache correctness survive fault injection;
- daemon and namespace cleanup operate unattended;
- one third-party-style module and provider can be implemented from public
  contracts alone;
- upgrade and rollback procedures preserve or explicitly migrate durable state;
- no unresolved critical security finding remains.

If these criteria are not met, continue beta releases. Version 1 is not a date
milestone.

## 20. Critical path and allowed parallelism

### Critical path

```text
T0 -> T1 -> E01/E02/E03/E04/E06 -> G1 -> T2 -> T3 -> T4 -> T5 -> T6/T7 -> T8 -> T9 -> T10
```

Dependencies:

- T2 waits for authoring, IR, and planner-boundary decisions.
- T3 waits for source/sandbox/profile identity decisions.
- T4 waits for durable node semantics from T3, though E05 runs earlier.
- T5 waits for durable daemon leases, though E07 runs earlier.
- T6 waits for T3 artifacts and T4 scheduling, though E08 runs earlier.
- T7 waits for T5 services and T6-tested remote concepts, while its feasibility
  was already established by E06.
- T8 waits for stable typed outcomes and daemon policy enforcement points.

### Safe parallel work

- E01 and E04 can run independently after T1.
- E03 can attack early E01/E02 drivers as soon as they exist.
- E05 is a simulation and can run beside sandbox experiments.
- E06 uses separate macOS infrastructure and should begin early.
- Documentation, fixtures, threat modelling, and fault-injection harnesses may
  progress alongside implementation.

### Unsafe parallel work

- building multiple real providers before E08/G1;
- building services before namespace/lease semantics;
- implementing a TypeScript SDK before plan/value semantics stabilize, unless
  G1 specifically selects that pivot;
- stabilizing public Go packages before W1-W3 authoring evidence;
- adding production effects before policy and idempotency contracts;
- optimizing cold provisioning before cache-before-provision is correct.

## 21. Decision records

Every gate produces a short ADR with:

- question and decision date;
- options considered;
- predeclared thresholds;
- evidence and raw-result location;
- chosen branch and why;
- consequences and deliberately unsupported cases;
- trigger for revisiting the decision;
- contracts now allowed to stabilize.

Rejected options remain documented. A later change cites new evidence rather
than silently reopening settled debates.

## 22. Backlog and milestone discipline

Every implementation item must declare:

- roadmap tranche and risk/requirement IDs;
- user-visible or evidence outcome;
- dependencies and contracts it assumes stable;
- test/fault scenario;
- observability needed to know it worked;
- rollback/removal strategy;
- whether it changes a versioned format.

Items that merely create abstraction without advancing a workflow, experiment,
or gate do not enter the active milestone.

At most one implementation tranche is active. The Risk Lab is the exception:
multiple bounded experiments may be active because their purpose is independent
information gathering.

## 23. Definition of done

A tranche is complete only when:

1. its reference workflow works end to end;
2. success and failure paths have automated tests;
3. declared performance and isolation measurements are recorded;
4. human and machine-readable diagnostics exist;
5. crash/cancellation/cleanup behavior is exercised;
6. security capabilities are explicit and policy-tested;
7. documentation distinguishes guarantees from limitations;
8. obsolete experiment/prototype dependencies are absent;
9. the exit gate decision is recorded;
10. the next tranche's assumptions are demonstrably true.

“Code merged” is not a gate outcome.

## 24. Immediate next actions

1. Complete T0 by recording the isolated prototype baseline and exact test
   command.
2. Create W1-W3 fixture specifications without building a shared framework.
3. Define the benchmark result format and provisional machine profile.
4. Start E01 with explicit registration and code-generation variants.
5. Start E04 with immutable source plus local copy-on-write sandbox; instrument
   worker reservation count from the first test.
6. In parallel, inventory available macOS VM/snapshot/simulator mechanisms for
   E06 and reserve representative hardware.
7. Draft E03 malicious-planner cases before choosing its sandbox mechanism.
8. Do not initialize the new production Go module until Gate 1 accepts the
   semantic and trust-boundary decisions.

This ordering deliberately delays visible infrastructure while front-loading
the decisions most capable of invalidating the product architecture.
