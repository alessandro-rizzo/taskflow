# E01 typed authoring and schema ergonomics

Roadmap experiment: E01. Task: TF-003.06. Risks: R1, R2, R10.

Status: TF-003.07 comparative measurement and the proposed E01 decision are
complete against the separately committed Phase A contract (`1c88ddb`). The
result is awaiting review and has not been accepted or committed.

Time-box: Phase B stops when all four candidate verification results exist or
after five working days from the Phase A commit, whichever comes first.
TF-003.07 must then record the branch decision before Gate 1.

## Question

Can a concise typed project API emit a complete, language-neutral operation
schema without evaluating operation bodies or inheriting privileged execution
authority?

The experiment contains four disposable approaches:

- A: generic Go values with explicit typed operation registration;
- B: generic Go values plus code generation from Go declarations;
- C: reflection-heavy Go registration;
- D: a minimal TypeScript comparison emitting the same provisional schema.

This experiment does not select an SDK, define a production package, or create
a new root Go module.

## Phase B smoke results

All four candidates emit canonically identical W1-W3 and synthetic-effect
schemas, reproduce the corrected W1 typed composition trace, reject both
artifact and endpoint misuse, return the required argument diagnostics, remain
byte-deterministic over ten fresh processes, and avoid evaluating operation
bodies during discovery or validation.

| Candidate | W1 authored LOC | Low-level concepts | Separately reported burden |
| --- | ---: | ---: | --- |
| A explicit Go | 31 | 4 | explicit schema registration |
| B generated Go | 21 | 3 | 7 annotation lines, 171 generator LOC, 158 generated LOC, 1 tag-reflection site |
| C reflected Go | 30 | 4 | 4 tag lines, 13 reflection sites |
| D TypeScript | 35 | 4 | locked TypeScript checker and 3 nominal-typing phantom members |

These Phase B values are inputs rather than a decision on their own. TF-003.07
has now measured latency, run the blinded agent trials, reviewed the separate
burdens, and applied the committed branch rules.

## TF-003.07 measured result

All candidates pass the strict warm-discovery p95 budget:

| Candidate | Warm discovery p95 |
| --- | ---: |
| A explicit Go | 10.81 ms |
| B generated Go | 8.57 ms |
| C reflected Go | 6.70 ms |
| D TypeScript | 19.50 ms |

Two of two fresh, source-confined agents also completed the shared schema
discovery, invalid-argument repair, and fake invocation tasks. See
[`measurements/summary.md`](measurements/summary.md) for the complete cold/warm
results and [`agent-trials/`](agent-trials/) for the sealed-bundle protocol and
raw transcripts.

The frozen branch rule therefore recommends **B**: it passes every common and
generator-specific gate and reduces A's 31 authored W1 lines to 21 (32.3%) and
four low-level concepts to three (25%). The proposed decision is
[`ADR 0005`](../../docs/decisions/0005-e01-authoring-schema.md). This does not
stabilize B's implementation, tags, generator, schema, or any public SDK.

## Phase A contents

- [`measurement-contract.md`](measurement-contract.md) fixes the comparison
  rules, thresholds, measurement protocol, and decision branches.
- [`scope/targets.json`](scope/targets.json) binds W1-W3 to the exact frozen T1
  schema goldens without copying them into a second contract, and freezes the
  candidate-neutral W1 logical authoring shape that every candidate must
  express with typed fake values.
- [`scope/effect-probe.schema.json`](scope/effect-probe.schema.json) supplies
  the one positive effect-bearing schema case absent from W1-W3.
- [`scope/w1-low-level-control.go.txt`](scope/w1-low-level-control.go.txt) is a
  syntactically parseable and gofmt-stable, but deliberately non-type-checking,
  experiment-only control used for authoring-size comparison.
- [`scripts/verify-phase-a.py`](scripts/verify-phase-a.py) checks only the
  contract, frozen hashes, control counts, and absence of candidate code. It
  is not an authoring or schema implementation.

## Verification

From the repository root:

```sh
mise exec -- task --dir experiments/e01-authoring-schema check
```

The check runs every standalone candidate gate and then compares completed
outputs through the T1 conformance harness and the candidate-neutral Phase A
oracles. Each candidate retains its own schemas, W1 trace, type-failure logs,
diagnostic results, dependency/count manifest, and limitations.

## Phase gate

The next action is review of TF-003.07's measurements, retained setup failures,
generator-burden assessment, and proposed ADR. Acceptance permits the B branch
to inform Gate 1; it does not authorize a production Go module or public SDK.

The W1 ergonomics result includes both discovery metadata and the authored fake
composition. A candidate that emits schema but does not author source ->
format/test/lint -> aggregate check cannot pass or exclude that missing body
from its line count.

## Removal and graduation

Everything here is disposable evidence. Gate 1 may cite a result or restate an
accepted concept in an ADR; nothing under `experiments/` becomes production by
import or convention.
