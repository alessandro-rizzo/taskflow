# E02 deterministic plan IR experiment contract

Roadmap experiment: E02. Task: TF-003.08. Risks: R2 and R10. Product
requirements: PLAN-1 through PLAN-5.

Status: Phase A contract only. No candidate implementation or result has been
collected. This document, `protocol.json`, its digest, and the files named in
`scope-hashes.json` must be accepted and committed before Phase B begins.

## Question and boundary

E02 asks whether authored operations can lower to an immutable, deterministic,
language-neutral plan which contains no Go runtime values and is sufficient for
independent validation, display, structural identity, and resume explanation.

Everything under `experiments/e02-plan-ir/` is disposable pre-Gate-1 evidence.
This experiment does not select a production plan type, public Go package,
daemon transport, RPC protocol, durable state schema, or compatibility promise.
It must not create a production Go module or import `prototype/bootstrap`.

The W1 bridge is read-only and binds the accepted E01 Candidate B source and
`ComposeW1` trace. Candidate B remains experiment evidence, not a stable SDK.
Its W1 trace proves typed-handle composition only; it does not already contain
conditions, profiles, cache semantics, runner invocations, or plan identity.
E01 supplied only public schema surfaces for W2 and W3, so E02 must define
disposable local typed fixtures for their concrete graphs and for the synthetic
full-coverage plan. It must not claim those graphs came from E01.

The four T1 plan goldens are comparison outputs, never generation inputs.
Candidate generation must still succeed when the golden directory is
unavailable. Comparison occurs only after emission.

## Frozen candidate grammar

The candidate envelope version is `t1-plan-conformance-plan-v2`. Its exact
object fields and value constraints are listed in `protocol.json`. Documents
contain JSON values only. Functions, interfaces, pointers, closures, executable
callbacks, secret values, provider handles, worker handles, and host-derived
ambient values are forbidden.

The grammar preserves the T1 envelope and its explicit node, artifact, service,
secret-capability, and effect declarations. Conditions, resources, execution
profiles, and cache policies receive an E02-local strict experimental grammar;
this does not promote T1's deliberately opaque nested objects into production
types. Unknown fields fail at every object level. Duplicate object names,
duplicate identifiers, duplicate set members, invalid references, incompatible
versions, non-scalar Unicode strings, non-integer numbers, and integers outside
signed 64-bit range fail before canonicalization.

Secret declarations contain only an opaque capability reference and
`resolved_by: daemon`; no secret value may appear. Planning must not acquire a
worker, contact a provider, resolve a secret, or execute an operation body.

## Frozen canonical JSON

Canonical bytes are compact UTF-8 JSON with no BOM or trailing newline.

- Object members are sorted by the lexicographic order of their UTF-8 key
  bytes.
- Strings contain Unicode scalar values and use the shortest JSON escape:
  `\"`, `\\`, `\b`, `\f`, `\n`, `\r`, and `\t` where applicable; remaining
  U+0000 through U+001F controls use lowercase `\u00xx`; all other scalars are
  emitted as UTF-8 without ASCII-only or HTML escaping.
- Numbers are signed 64-bit integers rendered in base ten with no leading zero,
  explicit plus sign, exponent, fraction, or negative zero.
- `true`, `false`, and `null` use those exact lowercase spellings.
- Arrays retain order unless their full schema path is named in the frozen
  set-like path table. Set-like values reject duplicates, normalize their
  elements recursively, then sort by UTF-8 identifier or scalar bytes as the
  table specifies. No key-name-only or open-ended path heuristic is allowed.

The structural digest is lowercase hexadecimal SHA-256 of those exact
canonical bytes. All values and arrays not named as set-like remain byte-
meaningful after canonical encoding.

Resume explanations use the separately versioned `e02-resume-diff-v1`
projection defined in `protocol.json`. Paths identify declarations by semantic
ID, never by incidental array position. Cosmetic descriptions and future retry
tuning are outside this experiment because neither is present in the frozen
plan grammar.

## Frozen evidence and gates

Phase B must retain raw plans, canonical plans, digests, validation/display
output, structural comparisons, mutation reports, rejection diagnostics,
sentinel observations, benchmark samples, environment metadata, and all failed
sample sets beneath `experiments/e02-plan-ir/evidence/`. The protocol gives
their exact locations.

All hard gates are conjunctive:

1. W1, W2, W3, and synthetic documents validate and have zero structural
   differences from their bound T1 goldens.
2. The synthetic document visibly covers typed artifacts, an optional output,
   planning and outcome conditions, resources, execution profile, cache policy,
   secret capability reference, endpoint, and effect.
3. Twenty fresh processes per fixture emit identical canonical bytes and
   digests. Go and the independent Python 3.9 standard-library reader produce
   identical canonical bytes and digests.
4. Every frozen set-like path is exercised by a two-or-more-element case and is
   reorder invariant. Every other array remains ordered.
5. The condition, execution-profile, output-type, and output-optionality
   mutations change identity and produce exactly their predeclared semantic
   paths and before/after values.
6. Incompatible versions and root/nested unknown fields fail with the stable
   paths in the protocol.
7. The bounded `platform=ios|android` shape probe produces a complete finite
   graph for either argument and rejects all other values without serializing
   a callback.
8. Worker/provider/secret access counters remain zero and all operation-body
   and file-write sentinels remain untouched.

The W1 decision benchmark uses 30 warm, prebuilt, fresh-process samples and the
T1 benchmark-v2 statistics. Its p95 must be strictly below 0.250 seconds. The
deterministic 10,000-node plan must be at most 16 MiB of compact canonical JSON.
Fifteen warm fresh-process samples each for generation plus canonicalization and
independent-reader validation plus digest must have p95 strictly below 2.000
seconds. Measurements are serial and may not overlap other Taskflow benchmark
work.

Failed sample sets are retained whole. After documenting the cause and exact
correction, the entire set may be rerun once; individual samples may never be
dropped or replaced. A second failed set fails the gate. Thresholds and branch
rules are never relaxed in response to results.

## Decision branches

- **Continue with canonical JSON:** only when every correctness, safety,
  determinism, scale, and performance gate passes.
- **Pivot encoding:** retain the failure and compare schema-first Protobuf or
  canonical CBOR with a JSON diagnostic projection if cross-language bytes,
  reorder invariance, strict validation, size, or latency fails, or correctness
  needs an open-ended key-name heuristic.
- **Bounded dynamic expansion:** retain the static-shape failure and prototype
  explicitly limited expansion if a representative argument-dependent graph
  cannot become a complete finite plan. The daemon must never call back into
  arbitrary project code.
- **Stop and revise semantics:** if language neutrality requires erasing typed
  artifact, optional, endpoint, or effect distinctions, revise E01/value
  semantics before T2.

When more than one failure applies, stop/revise takes precedence, followed by
bounded dynamic expansion, then encoding pivot. No successful branch selects a
production protocol before Gate 1.

## Contract integrity and Phase A exit

`protocol.sha256` binds the protocol bytes. `scope-hashes.json` binds this
contract, the protocol and digest, the Phase A verifier/test/Taskfile bytes, the
accepted E01 W1 import surface and trace, all four T1 goldens, and the exact T1
benchmark-v2 runner source used later. If Phase B adds a measurement wrapper,
its bytes must be added to the scope manifest and reviewed before any sample is
collected; thresholds, sample counts, order, and rerun rules may not change.

Phase A verification command:

```sh
cd experiments/e02-plan-ir
mise exec -- task check:contract
```

The verifier also rejects any Phase B candidate, reader, mutation artifact, or
result file while the protocol status remains `phase-a-contract-only`.
