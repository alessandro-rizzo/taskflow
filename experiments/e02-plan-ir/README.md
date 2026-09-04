# E02 deterministic language-neutral plan IR

Roadmap experiment: E02. Ticket: TF-003.08. Status: Phase B evidence ready
for review. Everything here remains disposable pre-Gate-1 evidence.

## Result

The frozen gates select `continue-canonical-json` as an input to Gate 1. This
does not select a production protocol, public package, or compatibility
promise.

The Go candidate lowers the accepted E01 Candidate B W1 trace and local typed
W2/W3 builders into the same versioned plan shape. A Python 3.9 standard-library
reader independently validates, canonicalizes, digests, displays, and explains
resume incompatibilities without importing Go or Taskflow packages.

All four emitted plans match the bound T1 goldens with zero validation or
structural differences. Twenty fresh processes per fixture produce one byte
sequence and digest, Go and Python canonical bytes match, all eleven set-like
paths are reorder invariant, and the four meaningful mutations produce their
predeclared semantic paths.

`evidence/implementation-manifest.json` binds the exact candidate, reader,
tests, and frozen benchmark-wrapper bytes that produced the retained evidence;
the evidence manifest then binds that source manifest and every result file.

Measured results and the full scorecard are in `evidence/summary.md` and
`evidence/scorecard.json`. The 10,000-node canonical plan is represented by its
size and digest rather than committed as a large generated artifact.

## Compatibility correction

The original Phase A contract required empty service, secret, and effect arrays
even though the bound W1/W2/W3 goldens omit them. Commit `713aa13` corrects that
contradiction without changing thresholds: these declarations may be omitted
only when empty and remain strict when present.

Candidate B also exposes optional `diagnostics`, but its trace has no producing
work item and the W1 golden omits it. E02 classifies it as a schema-only,
unmaterialized output instead of inventing a producer. The synthetic plan proves
plan-level optional artifact semantics. Gate 1 must revisit this operation-
output versus materialized-artifact boundary.

## Verification

```sh
cd experiments/e02-plan-ir
mise exec -- task check
```

Regenerate the complete evidence set with:

```sh
mise exec -- task evidence:generate
```

The live Phase B verifier first materializes commit `6b98cada` and runs the
corrected Phase A verifier against that immutable snapshot. It then verifies
the retained evidence manifest, exact semantic paths, thresholds, sample
statistics, and decision. `check:phase-a` is retained as a historical boundary
check and intentionally rejects a live tree containing Phase B files.

## Limitations

- The independent reader comparison covers Python, not multiple non-Go
  languages or a wire transport.
- The candidate and reader are deliberately experiment-local and disposable.
- Preliminary samples collected before the measurement wrapper was bound are
  retained only as a hashed invalidation record and do not contribute to the
  result. All accepted sets were recollected after commit `6b98cada`. A still
  earlier set also completed but the T1 harness rejected its auto-detected
  zero-RAM metadata before writing a record.
- Runtime-dependent graph shape is tested only through the bounded
  `platform=ios|android` probe; arbitrary dynamic expansion remains unsupported.
