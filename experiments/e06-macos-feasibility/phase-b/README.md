# E06 Phase B execution contract

Task: TF-003.14. Roadmap experiment: E06. Risks: R4, R8, R9.

Status: repository-only execution preparation. No candidate has been executed,
no external mutation is approved, and no E06 branch has been selected.

This subtree extends the accepted Phase-A inventory without changing it. The
accepted bytes remain anchored at commit
`098035bf29656c3fd3b3991224a98fdded3453b7`. `scripts/verify_phase_b.py`
reconstructs that exact Phase-A tree, runs its original verifier, and compares
every frozen live file before checking this contract.

## Current outcome

Four worker candidates are rejected before execution from accepted inventory:
the three VM shapes have no pinned controller, immutable image, or reservation,
and the coarse external runner has no endpoint, credential mediator, profile,
quota, reset API, or reservation. The trusted native host is the only remaining
conditional candidate, but it is blocked pending an exclusive window, a fully
resolved manifest, explicit command-level approval, and CoreSimulator access
that never touches the default device set.

The simulator order is frozen as fresh-create-boot, erase-reset, then
clone-from-golden. This ordering and every Phase-A sample count, metric
boundary, hard gate, and threshold are immutable.

## Safety boundary

The guard and runner in this repository-only phase cannot execute subprocesses,
send signals, create or delete lifecycle resources, invoke
Xcode/CoreSimulator, or access a provider or network. `runner.py` exposes only
a deterministic description. `guard.py` validates the proposed paths and
command ledger and rejects execution. The verifier may invoke only fixed,
read-only `git show` commands to reconstruct the accepted Phase-A snapshot.

The planned mutable root is `/private/tmp/taskflow-e06-native-a`. Every future
simulator command must pass the custom device set beneath that root. Existing
devices, the default simulator set, user workspaces and DerivedData, immutable
images, and unrecorded processes are forbidden targets.

Plan approval and approval of these repository changes are not execution
approval. Before any external command runs, the implementation must be
committed, all implementation/profile digests must be filled, the exclusive
window and approval identity must be supplied, and the complete schema-valid
manifest plus command/mutation/cleanup ledger must receive fresh approval.

## Verification

From the repository root:

```sh
mise exec -- task --dir experiments/e06-macos-feasibility/phase-b check
```

The check uses only Python's standard library and reads repository state. It
does not invoke the prepared native toolchain.
