# E01 predeclared measurement and decision contract

Status: proposed Phase A contract, frozen before candidate implementation.

Roadmap: E01. Task: TF-003.06. Decision owner after candidate completion:
TF-003.07.

## 1. Hypothesis and decision boundary

At least one non-reflection Go approach can make W1 materially more concise
than an equivalent low-level graph while preserving compile-time composition,
complete agent discovery, deterministic language-neutral schema, useful
diagnostics, and cached discovery below the T1 150 ms p95 budget.

This experiment can recommend A, recommend B, trigger the bounded TypeScript
pivot, or recommend narrowing/stopping. It cannot stabilize a public SDK,
schema, generator, Go package, or daemon protocol. Candidate execution may be
fake. E02, not E01, owns plan IR and executable graph semantics.

## 2. Fixed comparison scope

`scope/targets.json` binds the comparison to the current SHA-256 digest of each
frozen T1 schema golden. A candidate must derive, rather than read or copy at
runtime, these three documents:

| Workflow | Required surface | Authoritative target |
| --- | --- | --- |
| W1 | `check`; verbosity and changed-only arguments; enum/default; required and optional reports; filesystem-read capability; typed fake format/test/lint composition and aggregate | `fixtures/t1-plan-conformance/goldens/schema/w1-fast-project-check.schema.json` plus the logical authoring shape in `scope/targets.json` |
| W2 | `build-and-verify`; backend artifact, Go-test report, and local inspection outputs; Linux profile capability | `fixtures/t1-plan-conformance/goldens/schema/w2-cross-target-artifact-pipeline.schema.json` |
| W3 | `mobile-e2e`; report output; Linux, macOS, and simulator capabilities | `fixtures/t1-plan-conformance/goldens/schema/w3-isolated-native-mobile-stack.schema.json` |

W1 is the ergonomics workload. W2 is limited to typed build/artifact authoring.
W3 is limited to the public authoring surface and typed endpoint composition.
No candidate may claim that these schema exercises implement planning,
placement, services, native execution, authorization, or effects.

The W1 logical authoring shape is an experiment-only comparison oracle. Every
candidate must author a fake operation body that:

1. obtains one typed source value;
2. passes that source into distinct format, test, and lint child work;
3. obtains a required `Report[GoTests]` handle from test;
4. passes the three typed child values into an aggregate `check`;
5. exposes the required test report and optional aggregate diagnostics.

The manifest spells out the child records and six typed-handle relationships.
A candidate-local test must normalize its fake composition trace to that exact
shape. The trace has no runner invocation, profile, condition, cache, stable
node identity, canonical digest, or execution semantics; it is not E02 plan IR.

The W3 binding includes the landed v1 specification and both canonical
namespace examples as well as the v1 conformance schema golden. TF-003.05 added
the required consumer identity and updated the separately owned plan/schema
goldens only at their fixture-version boundary; the public E01 schema surface
is otherwise unchanged. The manifest verifies all four W3 bindings so a
later fixture or golden change fails Phase A verification explicitly.

All three W1-W3 goldens have an empty `required_effects` array. Exact
conformance therefore cannot positively demonstrate effect discovery. The
separate `e01-effect-probe` is deliberately synthetic and requires:

- `environment`, a required string enum (`staging` or `production`);
- `channel`, an optional string enum with default `beta`;
- a non-optional `Effect[PublishedRelease]` output;
- the `publish-release` effect request;
- signing-secret and App Store network capability requests.

The probe is not a fourth roadmap workflow and cannot graduate independently.

## 3. Candidate isolation and comparison interface

Phase B candidates use separate subdirectories, modules, dependency locks,
build caches, output directories, tests, and verification commands. They may
duplicate small mechanics. They must not import or read implementation code
from another candidate, `prototype/bootstrap`, or `fixtures`. There is no
shared authoring/schema library in this experiment.

The experiment-level Taskfile may orchestrate candidate-local commands and
compare completed JSON outputs. That orchestration has no schema-building
logic and is not a dependency of a candidate.

Each candidate must later publish an evidence manifest containing literal
commands for:

1. its complete verification gate;
2. build or type-check;
3. schema discovery for each scope id;
4. argument validation without operation invocation;
5. positive and negative composition checks;
6. W1 logical-composition trace verification;
7. clean and prewarmed preparation;
8. the exact user-authored and generated path sets used by counting.

Generation is audited from a standalone candidate export with an empty working
directory. Go dependency inventories, TypeScript dependency locks, source
inspection, and file-access evidence must show that frozen goldens are not
generation inputs. This detects ordinary copying but is not claimed to be a
hostile-code sandbox; that trust boundary belongs to E03.

## 4. Hard candidate gates

A candidate is viable only if every applicable gate passes. An infeasible
candidate instead preserves the failed command, environment, output, and a
specific limitation; it must not silently omit a test.

| Gate | Predeclared threshold |
| --- | --- |
| W1-W3 completeness | Each generated document has zero T1 validation violations and zero structural diffs from its bound golden. |
| W1 logical composition | Candidate authoring source constructs the exact manifest shape with typed fake handles: source into format/test/lint, all three child values into aggregate check, required test report from test, and optional diagnostics from the aggregate. Its candidate-local normalized trace must match the Phase A oracle. A schema-only descriptor is a failure. |
| Positive effect discovery | The generated effect probe is canonically equal to the Phase A probe and contains every field listed in section 2. |
| Cross-candidate comparability | All viable candidates produce canonically equal documents for all four scope ids. |
| Process determinism | Ten fresh-process emissions per scope are byte-identical before canonicalization. |
| Body non-evaluation | Ten fresh-process discovery runs and every argument-validation case complete without triggering a panic and file-write sentinel embedded in each operation body. |
| Typed composition | Every candidate type-checks positive controls and fails semantic type checking for both an `Artifact[BackendBinary]` passed as `Artifact[IOSApp]` and an `Endpoint[API]` passed as a different endpoint type. The failure must name the authored fixture and conflicting type names; exact compiler prose is not frozen. Go candidates use the pinned Go compiler and TypeScript D uses its pinned semantic checker. |
| Argument diagnostics | Unknown argument, wrong scalar kind, invalid enum member, and missing required effect-probe argument all fail before body evaluation. Machine output identifies operation, argument path, expected constraint, and actual value/kind; human output is non-empty. |
| Candidate isolation | No forbidden import/read, no dependency on another candidate, and one candidate-local verification command. |
| Schema source | Schema is derived from the candidate authoring declarations/metadata. A hand-written JSON document embedded or copied as the discovery implementation is a failure. |

Reflection-heavy C is still required to use typed generic handles for the two
compile-fail cases. Reflection is being compared as a schema-discovery
mechanism, not offered an exemption from typed composition.

TypeScript D must type-check its positive controls and fail both negative
composition cases with a candidate-local pinned semantic checker. Bun
transpilation alone is not type checking. If the pinned dependency cannot be
installed reproducibly, D records the install command, lock state, environment,
and failure as infeasibility rather than reporting a downgraded pass.

## 5. Ergonomics counting

### 5.1 Authored lines

The headline authored-line count includes every non-blank, non-comment line a
project author must maintain to declare W1, author its complete logical fake
composition, and emit its complete schema: operation code, source acquisition,
format/test/lint child calls or definitions, typed value flow into the
aggregate, operation registration, argument/output descriptors, tags,
directives, and W1-specific helpers. Imports, package declarations, tests,
candidate SDK internals, generic generator implementation, generated files,
and CLI bootstrap are excluded from the headline but reported separately.

Rules preventing easy gaming:

- apply the candidate language standard formatter before counting;
- count all user-authored regions named in the evidence manifest;
- count a helper outside the region when it contains W1-specific data or is
  referenced only by W1;
- require the counted path/range closure to cover every element and relation in
  the manifest's W1 logical authoring shape;
- do not compress several logical declarations onto one line;
- do not move W1 literals into candidate SDK internals;
- report annotation/directive lines, generic implementation lines, generator
  lines, generated lines, tests, and bootstrap as separate columns;
- retain the counting script output and reviewed path manifest.

The low-level control uses the same rule between its `E01-COUNT-BEGIN` and
`E01-COUNT-END` markers. It is valid Go syntax and must produce no diff from
`gofmt -d`; undefined placeholder types keep it deliberately non-type-checking
so it cannot become a fifth implementation candidate. `scope/targets.json`
records the verified baseline.

### 5.2 Author-visible concepts

A concept is counted once when the W1 author must understand or name it,
regardless of occurrence count. Every candidate supplies a ledger with a
file/line example for each concept. Synonyms count as the same concept;
wrapping a concept behind a W1-specific helper does not remove it.

The control fixes ten low-level concepts:

1. operation registration;
2. argument schema;
3. output schema;
4. capability request;
5. graph builder;
6. runner binding;
7. node definition;
8. source selection;
9. dependency edge;
10. aggregate join.

Project-domain concepts such as `Check`, `Report[GoTests]`, and
`Artifact[BackendBinary]` are listed in the ledger but do not count as
low-level leakage. The reviewer, not candidate code, resolves disputed
classification before TF-003.07 scores the results.

### 5.3 Material improvement threshold

A or B must have both:

- at least 25% fewer user-authored W1 lines than the verified control, rounded
  down to the largest passing integer; and
- at least 30% fewer low-level concepts, which means at most seven of the
  control's ten concepts.

The threshold is deliberately conjunctive: a compact registration blob that
still exposes the whole kernel is not materially simpler, and an abstraction
that saves concepts by adding substantial metadata is not materially shorter.
A schema descriptor plus an uncounted or absent operation body fails the hard
logical-composition gate before its LOC result is considered.

## 6. Performance protocol

TF-003.07 performs the measurements through
`fixtures/t1-benchmark-harness` schema v2. It records the source revision,
machine, OS build, toolchains, preparation command, primary state, secondary
cache dimensions, every sample, median, p95, and raw output location.

### 6.1 Cached W1 discovery decision metric

- Unit: one fresh process emits the W1 schema to stdout; redirection to
  `/dev/null` is inside the timed command so serialization is included.
- Samples: 30 per candidate.
- Before every sample: run the candidate's declared prewarm command untimed,
  including one successful W1 discovery.
- State: `warm`; record driver binary/runtime/compiler cache dimensions
  explicitly. No candidate may call an already-running server.
- Order: choose one recorded deterministic permutation of viable candidates,
  execute complete sample sets without other Taskflow work, then repeat the
  candidates in reverse order if any result lies within 10 ms of the budget.
- Pass: p95 strictly below 0.150 seconds. The budget is not relaxed if every
  candidate misses.

This measures cached project discovery, not daemon RPC, planning, or a cache
hit after planning.

### 6.2 Descriptive build and discovery measurements

Record 15 samples for each applicable state, without adding a pass threshold:

- cold driver build/type-check: candidate output absent before every sample;
  candidate compiler/package caches freshly prepared and declared;
- warm driver build/type-check: candidate output absent but language/compiler
  caches prewarmed before every sample;
- cold discovery: built dependency closure available, process and relevant
  discovery cache cold according to the literal preparation command;
- warm discovery: the decision metric above, with the first 15 also usable as
  this descriptive set.

If a language has no separate build artifact, record `not-applicable` with a
reason instead of inventing an equivalent. A single fully cold toolchain
anchor may be retained separately but is not mixed into the 15-sample driver
statistics.

No candidate measurements may run concurrently. Each candidate gets distinct
temporary build/cache paths. A failed sample set is retained and rerun only
after the cause and rerun rule are recorded.

## 7. Blinded agent protocol owned by TF-003.07

Create one candidate-neutral sealed bundle from canonically identical emitted
schema plus invocation help. It contains no candidate source, generated code,
repository documentation, or unrestricted repository path.

Two independent fresh agent sessions receive the same three tasks:

1. identify the W3 operation, output, and capabilities;
2. diagnose and repair invalid W1 argument JSON;
3. invoke the fake operation interface with valid arguments and report the
   typed outputs without inspecting implementation source.

Success requires two of two sessions to finish all three tasks, use only the
sealed bundle, and make no blocked source-read attempt. Preserve the exact
prompt, bundle digest, transcript, exit status, elapsed time, and filesystem
access controls. Because candidate schemas must be canonically identical, the
trial is run once against the shared schema, not repeated as artificial
candidate-specific UX evidence.

## 8. Decision branches

Hard gates are not points in a weighted score. Missing one requires the
corresponding branch or an explicitly approved contract revision before seeing
candidate results.

- **A wins:** A passes every hard gate, material-improvement threshold, warm
  discovery budget, and agent trial; B either fails or improves neither
  authored lines nor concepts by a further 15% relative to A. Prefer the
  simpler explicit toolchain when results are otherwise close.
- **B wins:** B passes the same gates and either A fails the material threshold
  or B improves authored lines or low-level concepts by at least a further 15%
  relative to A. B must also fail verification on stale generated output and
  map generator diagnostics to authored declarations.
- **C only works:** stop and redesign. Reflection may provide comparison
  evidence but cannot be the sole stable protocol-identity source.
- **Bounded TypeScript pivot:** A and B fail while D passes schema, safety,
  diagnostics, ergonomics, warm discovery, type checking, and the agent trial.
  Keep the Go core hypothesis but authorize only a time-boxed second-SDK
  experiment before T2.
- **Stop or narrow:** no candidate makes typed authoring materially better, or
  schema discovery/typing requires copying a parallel schema. Narrow Taskflow
  to an execution engine or stop the module-ecosystem branch.

If both A and B pass and B's further improvement is exactly on the 15%
boundary, B wins; there is no post-result tie-break adjustment. For integer
counts, “at least 15%” means B is no greater than `floor(A * 0.85)` for the
relevant metric.

## 9. Evidence retained by Phase B and TF-003.07

Per candidate retain emitted documents, ten-run determinism hashes, dependency
inventory, forbidden-read audit, compile positive/negative logs, body-sentinel
results, diagnostic JSON and human output, exact verification command,
limitations, and tool versions. TF-003.07 additionally retains benchmark v2
records, authored-line/concept ledgers, agent-trial bundles/transcripts, the
scorecard, and the ADR selecting a roadmap branch.

## 10. Threats to validity and deliberate limitations

- T1 goldens are provisional and structurally shallow. Passing them proves
  comparable discovery output, not a complete future SDK schema.
- The low-level control is a syntactically valid, gofmt-stable,
  experiment-local comparator with intentionally undefined placeholder types,
  not runnable prototype code. Review must judge whether its semantics and
  verbosity are fair before this contract is committed.
- Authored LOC remains formatter- and language-sensitive; concept leakage and
  separate burden columns guard against treating it as the sole result.
- File/dependency auditing is not a security sandbox. E03 owns hostile planner
  confinement.
- Fake invocation cannot validate execution, services, placement, policy, or
  native-mobile feasibility.
- The normalized W1 trace proves only that comparable typed fake composition
  was authored. It deliberately omits stable node IDs, conditions, plan
  canonicalization, scheduling, and execution, all of which remain E02 or
  later-tranche concerns.
- The synthetic effect probe demonstrates metadata only; it cannot authorize
  or perform an external mutation.
- One machine and modest sample counts can establish budget conformance, not a
  product-wide latency distribution.
- Two agent sessions test basic schema usability, not population-level agent
  reliability.

## 11. Review questions before the Phase A commit

The selected defaults are intentionally explicit so they can be changed now,
not after results exist:

1. Is 25% fewer authored lines and 30% fewer low-level concepts sufficiently
   material, or should either threshold be stricter?
2. Should A remain the default when A and B are within 15%, or should code
   generation win on any measurable authoring reduction?
3. Is the synthetic publish probe an acceptable positive effects test, or
   should AC #3 be interpreted as merely exposing an empty effects field?
4. Is one two-agent trial over canonically identical schema honest, or should
   each candidate undergo separate trials despite identical inputs?

The TypeScript checker question is settled for this contract: D may install
one candidate-local pinned semantic checker from a locked dependency, and an
unavailable reproducible installation makes D infeasible rather than exempt.

Any change is valid before the Phase A commit. After that commit, changing a
threshold requires a dated amendment explaining why the evidence remains
unbiased; a missed result alone is not a reason.
