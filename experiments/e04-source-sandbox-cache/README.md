# E04 immutable source, sandbox, and cache identity

Roadmap experiment: E04. Ticket: TF-003.11. Risks: R4, R5, R9.

Status: Phase A contract only. No source/CAS, sandbox, cache, worker, provider,
or benchmark implementation exists in this directory yet.

This contract must be reviewed and committed before Phase B mechanism work.
Its byte identity is frozen by protocol.sha256. Phase B evidence must name that
contract commit and independently digest the implementation tree it measures.

## Question

Can Taskflow execute immutable source in a disposable local sandbox, compute
complete result identity before worker reservation, and remain fast enough for
ordinary W1 checks?

The experiment evaluates three related claims together because separating them
would allow a misleading success:

1. execution consumes captured bytes, not a live source path;
2. each run receives private writable state and controlled ambient inputs;
3. result identity is complete before provisioning and verified independently
   of mutable worker state.

A fast clone without source isolation is not a pass. A correct cache key that
requires probing a worker is not a pass. A sandbox that passes only because no
adversarial access was attempted is not a pass.

## Canonical requirements and compatibility correction

The current product specification defines REP-1 through REP-6 for
reproducibility/caching. It does not define SRC-* or CACHE-* requirements.
TF-003.11's description uses SRC-1 through SRC-5 and CACHE-1 through CACHE-6;
those labels are retained as stale ticket provenance only.

The machine contract maps E04 to:

- REP-1: one immutable source snapshot per run;
- REP-2: requested and attained reproducibility levels are reported;
- REP-3: cache identity includes semantic profile and declared typed inputs;
- REP-4: a ready cache hit returns before worker reservation;
- REP-5: result, tool, and warm-provider caches remain distinct;
- REP-6: artifact provenance is queryable and digest verified;
- EXEC-3: reusable workers and disposable sandboxes have separate lifecycles;
- EXEC-4: profile identity is known before provisioning and attested at
  execution.

This local single-node experiment does not establish per-node heterogeneous
placement (EXEC-1), global-slot behavior under provider saturation (EXEC-2), or
durable service/session/device leases (EXEC-5). E05 and later experiments own
those claims. Phase B must not invent compatibility aliases for the stale
SRC-* or CACHE-* labels.

## Bound evidence inputs

fixture-bindings.json pins each file Phase B may rely on:

- W1 t1-experimental-v1: the passing repository plus its manifest;
- integrity-faults t1-integrity-faults-v2-experimental: the source-identity and
  cache-corruption baseline;
- benchmark harness taskflow-t1-benchmark/v2: the record validator and serial
  per-sample preparation runner.

The integrity fixture is adversarial input, not reusable implementation. Its
Snapshot freezes identity metadata rather than executable bytes, and its toy
Store deliberately records reservation before lookup. E04 must demonstrate the
stronger materialization and lookup-before-reservation properties without
importing that fixture.

The benchmark harness is invoked through its CLI. The experiment does not
import its Go package or create a shared framework.

## Competing mechanisms

Phase B may exercise:

- APFS clonefile through the native cp -c mechanism, combined with sanitized
  environment and native sandbox controls;
- an ordinary verified filesystem copy as a correctness and latency control;
- a pooled container only if a daemon is actually reachable and the candidate
  is executed;
- a microVM only if an actual provider becomes available.

Command presence is not evidence. Planning found APFS storage, cp -c, and
sandbox-exec. Docker's CLI is installed but its daemon socket is inaccessible
inside the managed environment, and Tart is absent. An unavailable candidate
is recorded as unavailable rather than credited with hypothetical behavior.

## Requested and attained reproducibility

The requested and maximum predeclared level is isolated:

- immutable source bytes;
- a unique disposable writable workspace;
- declared inputs and outputs;
- a sanitized environment;
- no cross-run mutable workspace.

The experiment does not predeclare hermeticity. Network closure, time,
randomness, full host-tool closure, host sockets, and hardware capabilities
remain unproven unless Phase B adds an approved contract amendment before
observing results. A denied path access is stronger evidence than detection;
detection without enforcement must be reported and caps the attained claim.
There is no silent downgrade.

## Seven required demonstrations

### 1. Source mutation

Create a run snapshot from an experiment-owned copy of W1, mutate and extend
the live copy, then execute from materialized captured bytes. The observed
content/result must match the original digest and must not contain the
post-creation marker.

Raw evidence: evidence/raw/source-mutation.json.

### 2. Concurrent writable isolation

Start two barrier-synchronised W1 runs with distinct workspace, HOME, TMPDIR,
output, and tool-cache roots. Each writes a unique marker. Neither may observe
or mutate the peer marker, and the shared immutable base must still verify.

Raw evidence: evidence/raw/concurrent-output-isolation.json.

### 3. Ambient input control

Seed an undeclared environment canary in the parent and read/write canaries
outside the declared sandbox. The child environment must omit the value, and
each path attempt must be denied or explicitly detected. Evidence contains
canary names, decisions, and non-secret diagnostics, never canary bytes.

Raw evidence: evidence/raw/ambient-input-control.json.

### 4. Complete pre-reservation identity

The experimental key requires source manifest, typed input manifests, resolved
process and arguments, execution profile, sandbox policy, and dependency
manifests. Missing any component rejects before lookup. Mutating each semantic
component independently changes the digest. The key and lookup occur before
reservation.

Raw evidence: evidence/raw/pre-reservation-identity.json.

### 5. Zero-reservation ready hit

Every ready-hit sample must record lookup and verified artifact-handle return,
with zero reservation, acquisition, attestation, sandbox, and execution events
and counters.

Raw evidence: evidence/raw/zero-reservation-cache-hit.json.

### 6. Fail-closed attestation

After a miss and reservation, a worker whose attested profile differs from the
planned profile fails before sandbox creation, execution, or publication. The
planned key remains unchanged; the unexpected profile cannot become a new
cache key.

Raw evidence: evidence/raw/attestation-mismatch.json.

### 7. Cache-class separation

Result cache, mutable tool cache, and warm-worker state use separate types,
storage roots, and event namespaces. Warming or poisoning either performance
cache cannot manufacture or authorize a result hit. A verified result hit
needs neither.

Raw evidence: evidence/raw/cache-class-separation.json.

## Predeclared measurement protocol

All measurements run serially, with 30 samples per metric. The preparation
command runs untimed before every sample. Phase B builds its experiment CLI
before timing and invokes the frozen T1 benchmark harness rather than importing
it.

### Warm APFS sandbox creation

- Primary state: warm.
- Secondary state: source CAS warm, worker capacity warm, result cache absent.
- Timed boundary: CreateSandbox invocation with a verified immutable base
  already materialized through return of a unique writable APFS clone.
- Excluded: prior source materialization, preparation, cleanup, and W1
  execution.
- Pass: p95 strictly below 0.250 seconds.

### Ordinary-copy control

The same create-only boundary is sampled 30 times using an ordinary verified
copy. Its p95 is descriptive; it has no pass threshold and cannot override a
failed isolation probe.

### Ready cache hit after planning

- Primary state: cache-hit.
- Secondary state: result entry ready and verified, source CAS warm, tool cache
  irrelevant to authority, worker capacity not required.
- Timed boundary: after plan acceptance and complete identity, measure result
  lookup, manifest verification, and immutable artifact-handle return.
- Pass: p95 strictly below 0.300 seconds.
- Every sample: zero reservations, acquisitions, and sandboxes. Raw traces must
  also contain no attestation or execution event.

The v2 record and samples are stored under evidence/benchmarks. Each sample's
trace/counters are retained separately because an aggregate
reservation_count=0 cannot prove that every individual sample avoided
provisioning.

Failed and unavailable sample sets are retained with their cause and rerun
rule. Generated sandboxes, CAS blobs, build caches, and large artifacts remain
outside Git.

## Predeclared decision branches

### Native isolated default

Select when APFS clone passes all seven demonstrations, ambient-input behavior
matches the reported level, and warm sandbox creation is below 0.250 seconds.
Recommend it as the isolated local default, not as hermetic execution.

### Native fast but incomplete

Select when immutable bytes, writable isolation, cache ordering, attestation,
and latency pass, but native path/capability enforcement remains incomplete.
Report the lower attained level and require a stronger pooled container or VM
mode for stricter work.

### Pooled container for Linux

Select only when an actually exercised pooled-container candidate is the sole
mechanism satisfying isolation and the applicable latency budget. An installed
or documented container runtime is not evidence.

### Redesign profile identity

Select when any key component requires worker acquisition, or an attestation
mismatch changes the planned key. Stop before T2 and redesign profile
resolution/attestation.

### Local hit, remote miss

Select when the correct local miss path cannot meet 0.250 seconds but the ready
hit remains correct and below 0.300 seconds. Keep planning and hits local and
dispatch misses to a warm pool.

### Stop or narrow

Select when execution observes post-snapshot mutation, concurrent runs share
writable state, identity is incomplete before reservation, or no exercised
mechanism provides a credible bounded branch.

## Evidence integrity

Phase B evidence uses taskflow-e04-probe-evidence/v1 and retains:

- source, input, process, profile, policy, dependency, and output digests;
- requested and attained reproducibility levels;
- ordered lifecycle events and resource counters;
- exact preparation and sampled commands;
- environment, OS build, hardware, and toolchain metadata;
- the committed Phase A contract identity;
- a digest manifest of the implementation tree actually measured;
- explicit limitations and unavailable mechanisms.

protocol.json is the machine-readable authority. Its expected digest is:

43f024a1ceb74ec0a8b0d8341d74270116e0a268bc02bee2482c50c3ffe6f200

fixture-bindings.json is itself bound from protocol.json at:

23e578bf7499c3faae47d27d6037af7444987d44a984f460f45b79cb7f67b14e

## Limitations and threats to validity

- Phase A contains no implementation or result and makes no feasibility claim.
- W1 is deliberately tiny; latency remains a local mechanism measurement, not
  a full-project performance promise.
- A non-atomic walk of a live source directory may still capture mixed-time
  content. Phase B must state its capture boundary and must not generalize the
  post-capture immutability result into atomic snapshot semantics.
- Native sandbox-exec behavior is OS- and policy-specific. Presence of the
  binary does not prove enforcement.
- Detection is weaker than denial and cannot support a hermetic claim.
- APFS clone behavior on this one machine does not establish Linux overlay,
  remote worker, macOS VM, or cross-filesystem behavior.
- Cache-key completeness is evaluated against the six predeclared semantic
  groups, not against the unresolved E02 canonical plan format.
- The experiment does not establish planner security, daemon fairness,
  services, durable leases, or a stable worker protocol.
- Source manifest, profile, cache identity, event, and evidence formats are
  experimental and may not become production contracts.

## Verification

From the repository root:

    mise exec -- task --dir experiments/e04-source-sandbox-cache check

This validates the protocol checksum, fixture hashes and semantic anchors,
canonical requirement mapping, seven probes, metrics, branches, and the
Phase A-only file allowlist.

The reusable contract-only check, which remains valid after Phase B files
exist, is:

    mise exec -- task --dir experiments/e04-source-sandbox-cache check:contract

## Phase gate

The next action is review of this contract and explicit authorization to commit
it. Phase B mechanism work must not begin before that commit. No acceptance
criterion, definition-of-done item, final summary, or branch decision is
complete at this stage.

After Gate 1, this experiment remains disposable evidence. A selected concept
must be restated in an accepted ADR and reimplemented or deliberately promoted;
nothing here becomes production by import or convention.
