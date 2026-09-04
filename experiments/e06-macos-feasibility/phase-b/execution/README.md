# E06 repository-only execution implementation

This subtree prepares an E06 runner without executing it. The runner remains
alive as the supervisor when the bounded caller child is terminated, persists
lease heartbeat/expiry state beneath the owned controller root, reaps only the
enumerated namespace and simulator, verifies the W3 caller-loss event order and
TTL-plus-30-second deadline, and then proves a clean retry.
It preserves three immutable anchors:

- Phase A: `098035bf29656c3fd3b3991224a98fdded3453b7`
- frozen Phase-B contract: `6decbbd1323fd9a69137129db234028d80b1151d`
- rejected approval audit: `83d36f8eea6ec818f41ed4fc376b85be2d48f1c3`

`expanded-ledger.json` enumerates every planned command and typed internal
effect for the frozen sample schedule. Every child command uses a deny-default
sandbox profile: reads, process execution/fork, required Mach lookup and POSIX
IPC are allowed, while writes are limited to the exact owned mutable root and
network access remains denied. Child HOME, TMPDIR, CF preferences, cache, and
configuration paths are rebuilt beneath that root rather than inherited from
the operator environment. Native viability of this policy is deliberately
unverified until the separately approved execution-window preflight.

Every ledger row carries a top-level namespace, repetition, and cleanup action.
Cleanup references may point only forward to an exact simulator delete or an
owned path removal that covers the row's target; failures retain the exact
owned target as an orphan and stop. Read-only assertions that observe live
owned state likewise retain that state on failure instead of claiming that no
orphan exists.

Native entry recomputes component bindings from the checkout. The execution
and fixture aggregate digests are SHA-256 of canonical JSON
(`sort_keys=true`, compact separators) shaped as
`{"format_version":"taskflow-e06-file-inventory/v1-experimental","files":[...]}`.
`files` uses the fixed lexicographically ordered path lists in `guard.py`, and
each entry binds both its repository-relative path and the SHA-256 of its exact
bytes. Separate named hashes bind the expanded ledger, fixture, sandbox/reset
policies, accepted manifest schema, and Phase-B frozen-artifact, protocol, and
scope controls. A changed byte, missing file, symlink, extra binding field, or
claim that does not match the recomputation rejects native entry.

The schedule re-attests the complete semantic host/toolchain profile before
each build set. Simulator readiness ends only after bootstatus, exact identity,
and a custom-device-set `listapps` installation-service probe. Build, install,
reset, and cleanup boundaries have explicit typed assertions. Terminal evidence
contains `taskflow-t1-benchmark/v2` records plus a deterministic mechanical
recommendation; correctness gates precede latency and concurrency branches,
and the runner never edits the decision ADR.

The Seatbelt profile constrains the invoked command process tree. It cannot by
itself prove where an already-running CoreSimulatorService writes after Mach
IPC. A future execution therefore also requires an approved attestation for a
dedicated ephemeral account or dedicated host, exact service-side write paths,
and a bound cleanup policy. Until that service-side boundary is resolved and
freshly approved, this ledger must not execute.

Runner-side sanitized evidence writes are not child writes. They form a second
explicit mutation boundary limited to
`experiments/e06-macos-feasibility/evidence/taskflow-e06-native-a`; the final
manifest must approve that path separately from the owned native root.

`scripts/runner.py` has a native backend,
but its execution path requires both a separately generated schema-valid
manifest and a commit-bound approval binding beneath the not-yet-created
`phase-b/execution-approval` directory. Describe, verify, tests, and recording
dry runs cannot instantiate that backend.

Repository verification uses only an in-memory recording backend. It patches
subprocess creation, process-group signals, and filesystem mutation to fail if they are
reached, asserts that no evidence or mutable experiment root is created, and
checks that the immutable anchors remain byte-identical.

Run from the repository root:

```sh
mise exec -- task --dir experiments/e06-macos-feasibility/phase-b/execution check
```

Passing this check is not execution approval.
