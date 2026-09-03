# ADR 0005: E01 typed authoring and schema derivation

Status: proposed

Question: which E01 authoring/schema branch should inform Gate 1: explicit Go
registration (A), generated Go declarations (B), reflection-heavy Go (C), a
bounded TypeScript pivot (D), or stopping/narrowing typed authoring?

Decision date: 2026-09-03

Task: TF-003.07. Roadmap references:
[E01 typed authoring and schema ergonomics](../roadmap.md#e01-typed-authoring-and-schema-ergonomics),
[Gate 1](../roadmap.md#10-gate-1-product-and-architecture-convergence), and
[decision-record fields](../roadmap.md#21-decision-records).

## Context

TF-003.06 separately committed the E01 comparison contract (`1c88ddb`) before
implementing four disposable candidates (`ca87b81`). Each candidate expresses
the same typed W1 source-to-format/test/lint-to-check composition, W2
build/artifact surface, W3 public endpoint surface, and synthetic positive
effect probe. Each derives the same provisional language-neutral schema
without invoking operation bodies.

TF-003.07 bound its execution protocol to those commits and recorded protocol
SHA-256 `4b77693a513a4fe7d74500f52eae5fccd339af59666ec3773a60d6946e4a02c2`
before collecting latency or agent results. This ADR decides only which E01
branch enters Gate 1. E02 still owns plan IR, E03 owns the planner trust
boundary, and Gate 1—not this ADR—decides whether any SDK concept may become
production work.

## Options considered

1. **A wins** — use generic Go values with explicit typed operation
   registration as the first SDK direction.
2. **B wins** — use generic Go values plus generation from Go declarations,
   and require generator/version ergonomics to be specified before foundation
   work.
3. **C only works: stop and redesign** — reflection may remain comparison
   evidence but cannot be the only stable protocol-identity source.
4. **Bounded TypeScript pivot** — keep the Go core hypothesis, freeze only
   shared schema concepts, and time-box a TypeScript-first authoring experiment
   before T2.
5. **Stop or narrow** — do not build a typed module ecosystem if typed
   authoring provides no material benefit or requires a copied parallel schema.

## Predeclared thresholds

Hard gates were not weighted. A viable candidate had to:

- emit canonically equal W1-W3 and positive-effect schemas with zero T1
  conformance diffs;
- author the exact typed W1 logical composition and trace;
- reject Artifact and Endpoint misuse semantically before execution;
- return stable diagnostics for four invalid-argument classes;
- remain byte-identical over ten fresh processes and never evaluate operation
  bodies during discovery or validation;
- remain isolated from fixtures, the prototype, and other candidates as an
  implementation dependency;
- use no more than 42 authored W1 lines and seven low-level concepts; and
- complete warm W1 discovery at p95 strictly below 150 ms.

The schema-only agent trial required two of two fresh sessions to discover W3,
repair invalid W1 arguments, and invoke the fake W1 interface without reading
candidate implementation source.

If A and B both passed, B won only if it was at or below `floor(A * 0.85)` on
authored lines or concepts, rejected stale generated output, and mapped
generator failures to authored declarations. Otherwise A's simpler toolchain
won. C could not win. D triggered a pivot only if A and B failed.

## Evidence and raw-result locations

All evidence is relative to the repository root:

- Frozen protocol and digest:
  `experiments/e01-authoring-schema/measurements/{protocol.json,protocol.sha256}`.
- Candidate hard-gate and burden audit:
  `experiments/e01-authoring-schema/measurements/candidate-audit.json`.
- Sixteen T1 v2 benchmark records and raw samples:
  `experiments/e01-authoring-schema/measurements/results/primary/<candidate>/<metric>/`.
- Deterministic execution order, reverse-run decision, and machine/toolchain
  record: `measurements/results/{execution.json,environment.json}` under the
  same experiment.
- Rejected RAM auto-detection attempt and dated correction:
  `measurements/failures/` and `measurements/amendments/`.
- Sealed-bundle manifest, Seatbelt preflight/profile, two counted JSONL
  transcripts, final answers, repaired inputs, invocation results, interface
  audit logs, and attempt metadata:
  `experiments/e01-authoring-schema/agent-trials/results/`.
- Pre-inference response-schema and nested-sandbox setup failures:
  `experiments/e01-authoring-schema/agent-trials/setup-failures/`.
- Machine-readable score and raw-file digests:
  `experiments/e01-authoring-schema/measurements/{scorecard.json,evidence-manifest.json}`.

### Candidate gates and authoring burden

All four candidates passed every common hard gate and the 42-line/seven-concept
material threshold.

| Candidate | Authored W1 LOC | Low-level concepts | Separate burden |
| --- | ---: | ---: | --- |
| A explicit Go | 31 | 4 | explicit schema registration |
| B generated Go | 21 | 3 | 7 annotation lines, 171 generator LOC, 158 generated LOC, 1 tag-reflection site |
| C reflection Go | 30 | 4 | 4 tag lines, 13 reflection sites |
| D TypeScript | 35 | 4 | locked TypeScript checker, 3 nominal-typing phantom members |

B's counted-region manifest initially retained a stale reference to a removed
W1-specific trace helper. TF-003.07 corrected only that evidence pointer before
timing; the helper had already become candidate-generic, and the authored code,
21 LOC result, thresholds, and candidate output did not change.

### Performance

The primary order was deterministically fixed as C, D, B, A. Each candidate
has 30 warm-discovery samples and 15 samples for cold discovery, cold driver
build/type-check, and warm driver build/type-check. Candidate-specific Go/Bun
cache paths prevented cross-candidate compiler/transpiler cache reuse. No set
ran concurrently.

| Candidate | Warm discovery median | Warm discovery p95 | 150 ms budget |
| --- | ---: | ---: | --- |
| A | 6.56 ms | 10.81 ms | pass |
| B | 6.63 ms | 8.57 ms | pass |
| C | 6.30 ms | 6.70 ms | pass |
| D | 18.30 ms | 19.50 ms | pass |

No result was within 10 ms of the 150 ms boundary, so the predeclared reverse
run did not trigger. Cold discovery and cold/warm driver build/type-check
results are descriptive and remain in the scorecard; they had no pass budget.

The pre-result protocol digest binds candidate inputs, states, order, sample
counts, cache-isolation method, thresholds, and rerun behavior, but it does not
separately hash the runner script bytes. Each accepted T1 record retains its
literal preparation and timed commands. This is a reproducibility limitation,
not hidden certainty; the warm p95 values are all more than 130 ms below the
decision boundary, so no plausible rounding or minor wrapper difference
changes the pass/fail result. A future experiment should bind its runner bytes
with its protocol before sampling.

The first C warm set produced no accepted record because managed-sandbox RAM
auto-detection returned zero. The T1 validator rejected it before writing
samples. The failure was retained, current non-unique hardware metadata was
supplied explicitly, and the complete primary sequence restarted under the
predeclared failed-set rule. No command under test or threshold changed.

### Independent agent trial

Two fresh, sequential, ephemeral Codex sessions used the same source-free
sealed bundle digest
`dbc05e5d86ecf0237bbc0c8102ea46b0f91685bee9918908b65c123300746261`.
Both sessions:

- identified `mobile-e2e`, `Report[MobileE2E]`, and all three W3 capabilities;
- diagnosed unknown `unknown`, invalid `verbosity`, and non-boolean
  `changed-only` W1 arguments;
- wrote and successfully validated a repaired argument object;
- invoked the fake `check` operation and reported required
  `Report[GoTests]` plus optional `Report[Diagnostics]`; and
- made no source-read attempt.

The retained Seatbelt profile denied reads/writes to the primary repository,
every known Taskflow worktree, and Codex memory. The preflight proved those
paths unreadable while the sealed binary remained executable. The two counted
attempts took 49.36 and 44.26 seconds.

Two pairs of setup failures are deliberately retained but not counted: two
requests rejected before inference by an invalid strict response schema, and
two agents whose shell commands could not start under nested macOS sandboxes.
The dated amendments explain the bounded setup corrections. Neither correction
changed the task prompt, operation schemas, invalid inputs, or success criteria.

## Decision

**B wins.** A and B both pass every hard, material-improvement, warm-discovery,
and shared agent gate. B then satisfies the frozen further-improvement rule:

- authored W1 code falls from A's 31 lines to 21, a 32.3% reduction and below
  the required maximum of `floor(31 * 0.85) = 26`; and
- low-level concepts fall from four to three, a 25% reduction and exactly at
  the passing maximum of `floor(4 * 0.85) = 3`.

B also rejects stale generated output and maps malformed declaration metadata
to the authored source. Its 171-line generator and 158 generated lines are a
real maintenance cost, not hidden from the score. They are acceptable for the
E01 branch recommendation because the generator is narrow, standard-library
only, deterministic, and guarded by both required failure modes. They are not
accepted as a production implementation or stable format.

Warm-discovery differences do not choose B: every candidate is far below the
budget, and the observed single-machine millisecond differences are too small
and irrelevant to override the frozen ergonomics rule. The shared agent trial
validates the common schema, not B's source authoring experience.

## Consequences and deliberately unsupported cases

- Gate 1 should evaluate a Go-first SDK direction where a narrow generator
  derives language-neutral operation schema from typed Go declarations.
- Before any clean foundation work, the generator/version ergonomics must
  specify invocation, stale-output handling, source diagnostics, deterministic
  output, version skew, and the boundary between authored and generated code.
- A remains the documented fallback if E02/E03 shows generation creates an
  unacceptable plan or trust-boundary coupling. C remains comparison evidence
  only. D does not trigger a TypeScript pivot because both non-reflection Go
  candidates passed.
- This decision does not validate plan IR, inferred executable edges, runner
  semantics, planning isolation, daemon loading, policy enforcement, effects,
  services, native execution, cache identity, or result compatibility.
- The agent trial establishes two basic successes on one schema and one model
  family; it is not population-level reliability evidence and does not compare
  source-authoring UX between candidates.
- All candidate code and trial interfaces remain disposable under
  `experiments/`. Production code must not import them.

## Trigger for revisiting this decision

- E02 cannot lower generated declarations to deterministic language-neutral
  plan IR without copying schema, evaluating privileged operation bodies, or
  weakening typed value semantics.
- E03 finds generated discovery requires authority or source access that the
  accepted planner boundary cannot safely provide.
- A representative real-project edit study shows stale-output workflow,
  annotation duplication, or generator diagnostics make B less understandable
  than explicit A despite the measured W1 reduction.
- Generator/schema version skew cannot fail clearly before execution or cannot
  be migrated without hand-editing generated data.
- Linux/amd64 reproduction materially contradicts the macOS/arm64 discovery or
  build characteristics used here.

## Contracts now allowed to stabilize

None. E01 permits these concepts to inform Gate 1 and later experiments:

- generic typed value categories for Source, Artifact, Endpoint, Check, Report,
  and Effect;
- typed composition that rejects incompatible artifacts/endpoints before
  execution;
- static derivation of operation arguments, defaults, enums, typed outputs,
  effects, and capability requests without operation-body evaluation; and
- a narrow Go declaration-to-schema generation direction with explicit stale
  output and source-diagnostic requirements.

The exact Go types/signatures, tags/comments, generator CLI and implementation,
schema version/encoding, W1 trace, fake invocation interface, and all candidate
source remain provisional. No production Go module or public SDK is authorized
before Gate 1.
