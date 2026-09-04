# E03 project-planner trust boundary

Roadmap experiment: E03. Ticket: TF-003.10. Risks: R3 and R11.

Status: Phase A contract only. This directory currently contains no planner
sandbox implementation, attack result, benchmark sample, or security finding.
Everything here is disposable pre-Gate-1 evidence and carries no compatibility
promise.

## Question

Can compiled project code emit an independently validated W1 plan without
receiving daemon filesystem access, ambient credentials, network authority,
unbounded process/resource power, or the ability to authorize its own plan?

The experiment compares four branches:

1. a restricted native subprocess supervised outside the project process;
2. a warm minimal container, but only if a real daemon is reachable;
3. an already-authorized helper VM, but only if a real endpoint exists; and
4. a reduced-execution static descriptor that runs no project code.

An installed command is not evidence. An unavailable candidate remains
unavailable, and a native weakness is recorded as a trusted-local limitation
rather than silently counted as an agent-safe pass.

## Phase A contract

The machine-readable authority is `protocol.json`. It fixes:

- the threat model and trusted computing base;
- exact read-only E01, E02, and T1 input hashes;
- the malicious-case matrix in `attacks.json`;
- native, container, helper-VM, and static-descriptor candidate definitions;
- process, memory, file-descriptor, output, plan-size, and time limits;
- the independent validator policy;
- the warm W1 measurement boundary and sample count;
- complete-set rerun rules; and
- the native, container, VM, descriptor, and stop branches.

`protocol.sha256` binds the protocol bytes. `scope-hashes.json` binds every
other Phase A contract file and every referenced repository input. Phase B
must name the full contract commit and verify the exact committed snapshot
before it can run an attack or collect a sample.

The two orchestration scripts are inert in Phase A. Their `--describe` mode is
used by the contract check; any execution mode requires a full contract commit
and Phase B binaries that do not exist in this tree.

## Frozen thresholds

| Boundary | Threshold |
| --- | ---: |
| Per executable attempt wall time | at most 2 s |
| Complete candidate attack suite | at most 30 s |
| CPU hard limit | 1 s |
| Address-space hard limit | 256 MiB where supported |
| File-descriptor hard limit | 64 |
| Combined captured stdout/stderr | 1 MiB |
| Accepted W1 plan | 1 MiB |
| Descendant cleanup verification | within 1 s |
| Warm W1 planning | 30 serial samples; p95 strictly below 250 ms |

Every case must be blocked, bounded, or explicitly classified as
`trusted_local_limitation`. The latter cannot qualify a candidate for
untrusted agent planning. No synthetic canary value, or its hex/base64
encoding, may reach planner-visible state or retained evidence.

## Requirement correction

The ticket mentions SEC-1 through SEC-6, but
`docs/product-specification.md` defines only SEC-1, SEC-2, and SEC-3. This
contract preserves the ticket wording as provenance and tests SEC-1 through
SEC-3 together with PLAN-2, PLAN-5, and AGENT-6. It does not invent SEC-4
through SEC-6 aliases.

## Verification

From the repository root:

```sh
mise exec -- task --dir experiments/e03-planner-trust check:contract
```

The check validates JSON without accepting duplicate members, verifies every
hash and fixed threshold, checks the attack catalogue mapping and wrapper
descriptions, and rejects any file outside the Phase A allowlist.

After the check, stop for review. The contract must be explicitly authorized
and committed before Phase B implementation or any attack/benchmark execution.
