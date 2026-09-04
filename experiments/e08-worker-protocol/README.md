# E08 minimal remote-worker protocol contract

Roadmap experiment: E08. Ticket: TF-003.16. Risks: R5 and R9.

Status: frozen Phase A contract only. There is no worker, adapter, transport,
SSH connection, execution evidence, or selected decision branch in this tree.

## Question

What is the smallest provider-neutral worker protocol that can preserve
cache-before-reservation, exact profile attestation, immutable transfer,
execution and log continuity, atomic publication, bounded cleanup, reconnect,
and orphan reconciliation across an in-process worker, remote Linux over SSH,
and the worker/sandbox/session shape established by E06 for macOS?

Phase A fixes the question, state machines, typed operation envelopes,
thresholds, fault cases, and decision precedence before any candidate is
implemented. Every format is experimental. Nothing here is a production Go
package or a compatibility promise.

## Frozen inputs

`fixture-bindings.json` binds:

- the complete W2 v1 graph and all five golden lifecycle scenarios;
- the complete accepted integrity-fault fixture;
- the E04 profile/cache protocol and retained evidence for pre-reservation
  identity, ready hits, attestation mismatch, and cache-class separation;
- the accepted E06 Phase A contract, macOS lifecycle shape, candidate matrix,
  measurement plan, and infrastructure blocker; and
- the T1 benchmark-v2 record and validator used by later timing evidence.

The product specification contains no `REM-*` identifiers. `REM-1` through
`REM-5` remain ticket provenance only. `contract.json` maps the experiment to
the current `EXEC`, `REP`, `AGENT`, and `DUR` requirements without aliases.

## Semantic boundary

The contract separates controller node state from reservation, worker,
sandbox, session, publication, and cleanup ownership. The common surface is a
typed operation/event vocabulary, not a universal environment object. macOS
may require a session; stateless Linux does not acquire one. Provider details
remain behind versioned capability extensions and cannot appear as an open
options map in project plans.

The ready-result path terminates after verified artifact-handle return. It has
no reservation, wake, acquisition, attestation, sandbox, session, execution,
publication, or cleanup transition. A cache miss may reserve capacity, but
`TryReserve` itself returns an immediate typed disposition and never performs
worker acquisition in the scheduler call.

## Phase boundary and SSH blocker

Phase A is repository-only. It must not implement adapters, create a Go
module, execute a worker, open a network connection, inspect SSH configuration
or credentials, contact a provider, or mutate local/remote infrastructure.

Before Phase B can use SSH, `ssh-availability-manifest.schema.json` requires a
fresh manifest pinning the endpoint, host key, approved identity mediator,
Linux profile and runner digests, experiment-owned remote root, capacity,
command/fault scope, cleanup allowlist, evidence destination, and explicit
execution approval. Unknown host keys, interactive prompts, ambient SSH
configuration or agent identities, `sudo`, installation, broad process kills,
shared roots, and cleanup outside the exact allowlist fail closed.

No such manifest or approval exists. Without a representative approved Linux
endpoint, later local/stub results remain partial: acceptance criterion 1 and
the one-core success branch cannot pass.

## Predeclared measurements and gates

`thresholds.json` fixes sample counts, timing boundaries, hard-zero counters,
cleanup and cancellation bounds, replay correctness, and the serial rerun
policy. `fault-matrix.json` maps every fault to its exact expected state,
events, retry rule, ownership result, and future raw-evidence path.

The decision precedence is fail closed:

1. stop or narrow on a correctness, integrity, ownership, or cleanup failure;
2. defer transport when semantics pass but representative transport evidence
   is absent or transport concerns dominate;
3. separate worker, sandbox, and session protocols if the E06 session shape
   leaks into stateless Linux semantics; otherwise
4. retain one typed core with typed capability extensions only if all three
   adapter shapes and every hard gate pass.

Even the final branch freezes no transport or wire encoding for production.

## Verification

From the repository root:

```sh
mise exec -- task --dir experiments/e08-worker-protocol check:phase-a
```

The check uses Python 3 standard-library code only. It verifies the complete
Phase A fileset, frozen hashes, bound repository inputs, state-machine and
operation semantics, thresholds, fault coverage, SSH safeguards, and decision
precedence, then runs mutation tests. It rejects Phase B source/evidence and a
selected decision.
