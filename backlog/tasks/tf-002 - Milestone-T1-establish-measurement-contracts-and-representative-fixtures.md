---
id: TF-002
title: 'Milestone T1: establish measurement contracts and representative fixtures'
status: To Do
assignee: []
created_date: '2026-09-02 17:15'
updated_date: '2026-09-02 17:20'
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
- [ ] #1 Frozen representative fixtures exist for W1, W2, and W3
- [ ] #2 The benchmark runner reports the full roadmap measurement metadata and raw-result location
- [ ] #3 Conformance, fault-injection, and malicious-planner fixtures cover every T1 deliverable
- [ ] #4 The exit review demonstrates comparable cold, warm, and cache-hit evidence for every Risk Lab experiment
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

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All T1 child tickets are Done
- [ ] #2 T1 exit decision and raw evidence locations are linked
- [ ] #3 mise exec -- task check and git diff --check pass
- [ ] #4 Backlog acceptance criteria, notes, and final summary are current
<!-- DOD:END -->
