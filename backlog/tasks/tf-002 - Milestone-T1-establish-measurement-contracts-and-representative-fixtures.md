---
id: TF-002
title: 'Milestone T1: establish measurement contracts and representative fixtures'
status: Done
assignee: []
created_date: '2026-09-02 17:15'
updated_date: '2026-09-03 12:45'
labels:
  - milestone-t1
  - measurement
  - fixtures
  - coordination-only
dependencies:
  - TF-001
references:
  - docs/roadmap.md#8-t1-measurement-contracts-and-representative-fixtures
  - docs/roadmap.md#20-critical-path-and-allowed-parallelism
priority: high
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Roadmap tranche: T1; gate T1 exit; workflows W1-W3; risks R1-R12.
Outcome: every Risk Lab experiment can run against representative fixtures, report comparable evidence, and distinguish cold, warm, and cache-hit paths.
Stable assumptions: G0 passed; the prototype remains evidence only; no production Go module exists before Gate 1.
Parallelism: TF-002.01 through TF-002.04 form the first parallel wave. TF-002.05 through TF-002.08 form a second parallel wave once their declared fixture and measurement dependencies complete. TF-002.09 converges the milestone.
Test and evidence: exercise benchmark metadata, deterministic goldens, required fault cases, and malicious planner abuse across W1-W3.
Rollback or removal: all T1 machinery remains fixture or harness infrastructure and must not force a production contract.
Versioned formats: benchmark and conformance artefacts must be explicitly versioned or declared pre-G1 experimental.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Frozen representative fixtures exist for W1, W2, and W3
- [x] #2 The benchmark runner reports the full roadmap measurement metadata and raw-result location
- [x] #3 Conformance, fault-injection, and malicious-planner fixtures cover every T1 deliverable
- [x] #4 The exit review demonstrates comparable cold, warm, and cache-hit evidence for every Risk Lab experiment
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. After G0, run TF-002.01 through TF-002.04 in parallel with disjoint fixture and harness ownership.
2. Run TF-002.05 through TF-002.08 in parallel once their fixture and benchmark dependencies are complete.
3. Keep all formats explicitly experimental and avoid production packages.
4. Run TF-002.09 to reproduce the evidence and decide whether T1 passes.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Execution policy: implement every child ticket on its own branch in an isolated Git worktree created from current main. Record the branch, worktree path, and claimed files before editing; never share a worktree between agents. After acceptance and explicit landing authorisation, update against current main, rerun checks, merge serially to main, push, verify HEAD equals origin/main, then remove the worktree.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Milestone T1 complete. All nine child tickets (TF-002.01-.09) are Done and merged.

Wave A - fixtures and the measurement contract:
- TF-002.01 fixtures/w1/: minimal standalone Go repo plus three single-fault variants (format/test/lint each broken independently), versioned manifest declaring expected graph, conditions, diagnostics, and execution states.
- TF-002.02 fixtures/w2/: provider-neutral cross-target graph plus five golden fault-scenario specs (corrupt artifact, downstream-failure resume, worker loss, provider outage, cancellation).
- TF-002.03 fixtures/w3/: specification-only native-mobile stack fixture (no W3 infrastructure exists yet), two-namespace concurrency model, six fault scenarios, dependency-free validator enforcing referential integrity and cross-namespace uniqueness.
- TF-002.04 fixtures/t1-benchmark-harness/: versioned benchmark record schema, validator that recomputes statistics rather than trusting them, and the t1bench runner with per-sample state preparation.

Wave B - fault and abuse harnesses:
- TF-002.05 fixtures/t1-plan-conformance/: canonicalisation, digest, validation and structural-diff library plus t1conform CLI, with plan and schema goldens for W1-W3 and a synthetic full-coverage golden.
- TF-002.06 fixtures/t1-lifecycle-faults/: abstract durable-lifecycle simulation with process-crash, daemon-restart, worker-loss, cancellation and lease-expiry scenarios, each with before/after injection points, and a real serialize/reload boundary proving no committed event is lost across a restart.
- TF-002.07 fixtures/integrity-faults/: toy content-addressed snapshot and cache store demonstrating six independently mutation-tested integrity checks, including genuine stale-entry rejection via source provenance.
- TF-002.08 fixtures/malicious-planner/: six-category synthetic attack catalogue with enforced per-attempt and suite timeouts, panic recovery, secret redaction, and the attackcat runner.

Gate:
- TF-002.09 docs/decisions/0004-t1-exit.md: T1 exit decision, all four criteria pass, E01-E08 each mapped to a representative fixture and comparable result path, four non-blocking residual gaps recorded.

Process note: every wave-B ticket went through independent Codex CLI adversarial review, one or more fix rounds, and independent Opus-model verification of the fixes. Two were initially rejected outright by review (TF-002.06 "does not meet"; TF-002.08 "not safe to run repeatedly in any environment") and passed only after mechanism-level fixes - a real daemon-restart persistence boundary, and removing ambient-environment inheritance, a TOCTOU dial race, and cooperative-only timeouts respectively. Wave A was reviewed as a batch after landing and required a follow-up fix round of its own.

T1 is now the gate that unblocks Risk Lab experiments E01-E08 per the G0 decision's wave ordering.
<!-- SECTION:FINAL_SUMMARY:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [x] #1 All T1 child tickets are Done
- [x] #2 T1 exit decision and raw evidence locations are linked
- [x] #3 mise exec -- task check and git diff --check pass
- [x] #4 Backlog acceptance criteria, notes, and final summary are current
<!-- DOD:END -->
