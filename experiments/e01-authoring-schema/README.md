# E01 typed authoring and schema ergonomics

Roadmap experiment: E01. Task: TF-003.06. Risks: R1, R2, R10.

Status: Phase B smoke implementation complete against the separately committed
Phase A contract (`1c88ddb`). Comparative measurement and the branch decision
remain owned by TF-003.07.

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

These are smoke and ergonomics results, not the E01 decision. TF-003.07 still
must run the predeclared warm/cold measurements and blinded agent trials, review
the generator/reflection/toolchain burdens, and apply the committed branch
rules. In particular, B's LOC advantage does not become a recommendation until
its other gates are assessed, and C cannot win under the contract even though
it is concise.

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

The next action is the TF-003.06 implementation review. TF-003.07 may measure
and decide only after these candidate implementations and their retained smoke
evidence are accepted. The W3 target remains hash-bound to its landed v1
specification, namespace examples, and conformance golden.

The W1 ergonomics result includes both discovery metadata and the authored fake
composition. A candidate that emits schema but does not author source ->
format/test/lint -> aggregate check cannot pass or exclude that missing body
from its line count.

## Removal and graduation

Everything here is disposable evidence. Gate 1 may cite a result or restate an
accepted concept in an ADR; nothing under `experiments/` becomes production by
import or convention.
