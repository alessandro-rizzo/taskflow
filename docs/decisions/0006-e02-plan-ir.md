# ADR 0006: E02 deterministic language-neutral plan IR

Status: accepted

Question: which E02 plan-IR branch should inform Gate 1: canonical JSON, a
schema-first encoding pivot, bounded dynamic expansion, or a value/schema
redesign?

Decision date: 2026-09-04

Task: TF-003.09. Roadmap references:
[E02 deterministic language-neutral plan IR](../roadmap.md#e02-deterministic-language-neutral-plan-ir),
[Gate 1](../roadmap.md#10-gate-1-product-and-architecture-convergence), and
[decision-record fields](../roadmap.md#21-decision-records).

## Context

TF-003.08 froze the E02 contract before implementing a disposable canonical
JSON candidate. The candidate lowers the accepted E01 Candidate B W1 trace and
experiment-local typed W2, W3, and synthetic graphs into a strict, versioned
plan containing JSON values only. A Python 3.9 standard-library reader with no
Taskflow Go imports independently validates, canonicalizes, digests, displays,
and compares the same plans.

The contract was corrected before accepted measurement to reconcile omitted
empty service, secret, and effect arrays with the bound T1 goldens, and to
classify Candidate B's unproduced optional diagnostics output as schema-only.
It was then amended at commit `6b98cada25439f66c75eaf3f5faea3d01dfdfade`
to bind the sole benchmark wrapper before collecting the accepted sample sets.
The final implementation manifest binds the exact candidate, reader, tests,
and wrapper bytes; the evidence manifest binds the retained raw results.

This decision evaluates risks R2 and R10 and product requirements PLAN-1
through PLAN-5. It does not select a production plan type, daemon transport,
public package, or compatibility policy. E03 separately decides the planner
trust boundary, and Gate 1 decides what may enter the clean foundation.

## Options considered

1. **Continue with canonical JSON** for the early driver/daemon boundary while
   retaining freedom to change transport and plan representation later.
2. **Pivot encoding** to a schema-first Protobuf or canonical-CBOR
   representation with a JSON diagnostic projection if canonicalization,
   strict validation, scale, or cross-language identity is fragile.
3. **Use bounded dynamic expansion** if a representative argument-dependent
   operation cannot produce a complete finite plan; never let the daemon call
   back into arbitrary project code.
4. **Stop and revise value/schema semantics** before T2 if language neutrality
   requires erasing typed artifact, optional-output, endpoint, or effect
   distinctions.

The frozen precedence is stop/revise, bounded expansion, encoding pivot, then
canonical JSON. All gates are conjunctive and unweighted.

## Predeclared thresholds

The correctness and safety gates required:

- W1, W2, W3, and the synthetic full-coverage plan to have zero T1 validation
  violations and zero structural differences;
- the synthetic plan to retain typed artifacts, optional output, planning and
  outcome conditions, resources, execution profile, cache policy, secret
  capability, endpoint, and effect distinctions;
- 20 fresh processes per fixture to produce one canonical byte sequence and
  one digest, with identical Go and Python canonical bytes and digests;
- all eleven schema-declared set-like paths to be reorder invariant without an
  open-ended key-name heuristic, while every other array remains ordered;
- planning-condition, execution-profile, output-type, and output-optionality
  mutations to alter identity and report only their predeclared semantic
  paths and before/after values;
- incompatible versions and root/nested unknown fields to fail at stable
  paths;
- `platform=ios` and `platform=android` to produce complete finite graphs,
  every other value to fail, and no serialized callback to appear; and
- zero worker acquisitions, provider calls, and secret resolutions, with all
  operation-body and file-write sentinels untouched.

The scale and performance gates required:

| Measure | Threshold | Accepted result | Verdict |
| --- | ---: | ---: | --- |
| Warm prebuilt W1 planning, 30 fresh processes | p95 < 250 ms | p95 10.366 ms | pass |
| 10,000-node canonical plan size | <= 16 MiB | 3,370,219 bytes | pass |
| Large generation plus canonicalization, 15 fresh processes | p95 < 2 s | p95 189.869 ms | pass |
| Independent-reader validation plus digest, 15 fresh processes | p95 < 2 s | p95 208.509 ms | pass |

Measurements had to run serially in the frozen order. Failed sets had to be
retained and could be restarted once from sample one after a documented
correction; individual samples, thresholds, and branch rules could not change.

## Evidence and raw-result locations

All paths are relative to the repository root:

- Frozen contract, machine-readable protocol and digest:
  `experiments/e02-plan-ir/{experiment-contract.md,protocol.json,protocol.sha256}`.
- Corrected Phase A scope binding: `experiments/e02-plan-ir/scope-hashes.json`
  and commit `6b98cada25439f66c75eaf3f5faea3d01dfdfade`.
- Candidate and independent reader:
  `experiments/e02-plan-ir/{candidate-json/,reader/}`.
- Result summary, complete gate score, measured-source binding, and retained
  evidence binding:
  `experiments/e02-plan-ir/evidence/{summary.md,scorecard.json,implementation-manifest.json,manifest.json}`.
- Raw emitted/canonical plans, digests, T1 comparisons, independent displays,
  determinism, reorder probes, mutation plans/diffs, rejection diagnostics,
  bounded-shape result, concept coverage, and sentinel observations:
  `experiments/e02-plan-ir/evidence/raw/`.
- Benchmark records and raw samples:
  `experiments/e02-plan-ir/evidence/raw/benchmarks/`; the manifest-bound timed
  commands are in `experiments/e02-plan-ir/scripts/run_benchmarks.py` because
  the T1 benchmark record schema stores preparation and samples but does not
  copy the timed command into each record.
- Invalidated pre-wrapper samples, retained only by digest and excluded from
  the decision: `experiments/e02-plan-ir/evidence/failures/prebinding-measurements.json`.
- Reproduction and verification commands:
  `experiments/e02-plan-ir/{Taskfile.yml,README.md}`. The decision revalidates
  preserved evidence with `mise exec -- task --dir experiments/e02-plan-ir check`;
  it does not regenerate or replace accepted measurements.

The four plans have zero T1 differences and matching Go/Python digests. Every
fixture's 20-process set collapses to one byte sequence and digest; all eleven
reorder probes pass; and the four meaningful mutations report these exact
paths:

- `$.nodes[id=lint].planning_condition.patterns`;
- `$.nodes[id=test].execution_profile.toolchain`;
- `$.artifacts[id=test-report].type`; and
- `$.artifacts[id=test-report].optional`.

Both readers reject the incompatible format at `$.format_version`, the root
unknown field at `$.unexpected`, and the nested field at
`$.nodes[id=test].unexpected`. The iOS and Android shape probes emit complete
finite plans, while the unsupported Windows value fails. Authority counters
are zero and every sentinel remains untouched.

## Decision

**Continue with canonical JSON.** Every frozen correctness, safety,
determinism, mutation, validation, scale, and performance gate passes.

Canonicalization is robust enough for the frozen strict grammar: object keys
are ordered by UTF-8 bytes, signed 64-bit integers have one representation,
and only eleven full schema paths have set semantics. This avoids the fragile
alternative of sorting arrays by field name alone. Canonical SHA-256 identity
matches across the Go producer and independent Python reader, and semantic-ID
resume differences explain meaningful mutations without array-index noise.

Language neutrality did not weaken the typed semantic model. Artifact types,
output optionality, endpoint/service capabilities, secrets, effects,
conditions, profiles, resources, and cache policy remain distinct in the
validated plan. The Python reader consumes those distinctions without Go
runtime values or Taskflow imports.

Bounded dynamic expansion is not selected now. The representative
argument-dependent `platform=ios|android` operation produces a complete finite
plan for each accepted value and rejects other values without serializing a
callback. This proves only bounded argument-driven graph selection; it does
not establish that arbitrary runtime-dependent graph shape is supported.

The chosen branch is an input to Gate 1, not permission to stabilize or reuse
the experiment implementation.

## Consequences and deliberately unsupported cases

- Gate 1 may consider strict versioned plan/condition values, schema-path-aware
  canonical JSON, SHA-256 structural identity, and semantic-ID resume
  explanations for the first planning boundary.
- Transport encoding remains separate from plan semantics. JSON is supported
  by this evidence, but Protobuf, CBOR, or another transport can still be
  selected later without reopening typed plan meaning by default.
- Canonicalization depends on an explicit schema. New set-like paths require a
  reviewed schema change; unknown fields and versions fail rather than being
  normalized heuristically or silently ignored.
- Candidate B's optional diagnostics output remains schema-only and
  unmaterialized because its trace has no producer. The synthetic plan, not
  W1, supplies the plan-level optional-artifact evidence.
- Python is the only non-Go reader tested. No second independent language,
  wire transport, endianness-sensitive binary representation, or long-term
  compatibility migration was evaluated.
- Arbitrary data-dependent or execution-dependent graph expansion is
  unsupported. The daemon must not invoke project code after accepting a plan.
- The `t1-plan-conformance-plan-v2` envelope, `e02-resume-diff-v1`, candidate
  APIs, canonicalizer, reader, and all source under the experiment remain
  disposable. Production code must not import them.
- The invalidated pre-wrapper measurements remain audit evidence only. They
  contribute no samples to the accepted performance verdicts.

## Trigger for revisiting this decision

- Another independent language cannot reproduce canonical bytes or semantic
  diffs for the accepted grammar.
- Correctness requires an open-ended key-name ordering heuristic, or a schema
  evolution makes set-versus-sequence meaning ambiguous.
- A representative operation cannot produce a complete finite graph from
  immutable planning inputs and therefore needs explicitly limited dynamic
  expansion.
- Language-neutral serialization erases or duplicates typed artifact,
  optional, endpoint, service, secret, condition, profile, cache, or effect
  semantics selected at Gate 1.
- Representative plans materially exceed the measured size/latency gates, or
  another target/runtime exposes canonical Unicode, integer, or validation
  differences not covered by this experiment.
- E03 shows that producing or validating this plan requires authority outside
  the accepted planner boundary.
- Gate 1 changes the E01 value/schema branch or requires a transport whose
  semantics cannot be separated cleanly from the plan model.

## Contracts now allowed to stabilize

None. No production plan encoding, public Go API, daemon transport, condition
schema, resume format, or compatibility promise stabilizes before Gate 1.

The following concepts are proposed as Gate 1 inputs only:

- a strict, independently validated, versioned language-neutral plan made of
  value data rather than Go runtime objects;
- schema-path-aware canonicalization and SHA-256 structural identity;
- preserved typed artifact, optional-output, endpoint/service, secret, effect,
  condition, profile, resource, and cache-policy distinctions;
- semantic-identifier paths for resume compatibility explanations; and
- complete finite planning for bounded argument-dependent graph selection,
  with arbitrary post-plan dynamic expansion excluded unless new evidence triggers
  the predeclared pivot.
