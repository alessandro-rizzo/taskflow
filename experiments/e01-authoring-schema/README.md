# E01 typed authoring and schema ergonomics

Roadmap experiment: E01. Task: TF-003.06. Risks: R1, R2, R10.

Status: Phase A measurement contract only. No authoring candidate exists in
this directory yet.

Time-box: Phase B stops when all four candidate verification results exist or
after five working days from the Phase A commit, whichever comes first.
TF-003.07 must then record the branch decision before Gate 1.

## Question

Can a concise typed project API emit a complete, language-neutral operation
schema without evaluating operation bodies or inheriting privileged execution
authority?

The later implementation phase will compare four disposable approaches:

- A: generic Go values with explicit typed operation registration;
- B: generic Go values plus code generation from Go declarations;
- C: reflection-heavy Go registration;
- D: a minimal TypeScript comparison emitting the same provisional schema.

This experiment does not select an SDK, define a production package, or create
a new root Go module. Candidate code may begin only after the Phase A contract
has been reviewed and committed separately.

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

The check validates the Phase A files, passes the synthetic schema through the
T1 conformance validator, checks the W1 schema/control against the logical
authoring shape, and fails if a candidate directory exists before the contract
commit.

## Phase gate

The next action is review, not candidate implementation. Reviewers should
decide whether the selected defaults in the contract are acceptable,
especially the 25% authored-line reduction, 30% low-level-concept reduction,
A-versus-B tie-break, synthetic effect shape, and two-trial agent protocol.
The typing bar is no longer asymmetric: TypeScript D must use a pinned semantic
checker for the same positive controls and Artifact/Endpoint negative cases as
the Go candidates, or record reproducible infeasibility.
The W3 target is now bound to the landed v1 specification, namespace examples,
and v1 conformance golden. Only an explicitly approved, standalone Phase A
commit unlocks Phase B.

The W1 ergonomics result includes both discovery metadata and the authored fake
composition. A candidate that emits schema but does not author source ->
format/test/lint -> aggregate check cannot pass or exclude that missing body
from its line count.

## Removal and graduation

Everything here is disposable evidence. Gate 1 may cite a result or restate an
accepted concept in an ADR; nothing under `experiments/` becomes production by
import or convention.
