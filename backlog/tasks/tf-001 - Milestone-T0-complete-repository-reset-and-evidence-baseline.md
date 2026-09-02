---
id: TF-001
title: 'Milestone T0: complete repository reset and evidence baseline'
status: To Do
assignee: []
created_date: '2026-09-02 17:14'
updated_date: '2026-09-02 17:20'
labels:
  - milestone-t0
  - gate-g0
  - evidence
  - coordination-only
dependencies: []
references:
  - docs/roadmap.md#7-t0-repository-reset-and-prototype-baseline
  - prototype/bootstrap/docs/baseline.md
priority: high
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Roadmap tranche: T0; gate G0; risks R1-R12.
Outcome: close the remaining evidence gaps for the isolated bootstrap so later experiments start from a reproducible, explicit baseline.
Stable assumptions: docs is product truth; prototype/bootstrap is preserved evidence and cannot be imported by new production code.
Parallelism: TF-001.01 through TF-001.04 are independent after ownership paths are recorded; TF-001.05 is the convergence task.
Test and evidence: reproduce the prototype gates and capture the measurement and inventory artefacts required by roadmap section 7.
Rollback or removal: evidence-only additions can be reverted independently; do not alter prototype semantics merely to improve a baseline.
Versioned formats: none.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Every item in the T0 evidence-to-capture list has a reproducible artefact or an explicit justified gap
- [ ] #2 The isolated prototype passes its build, race-test, vet, and formatting gate
- [ ] #3 No root production package imports prototype/bootstrap
- [ ] #4 The G0 decision records experiment IDs, ownership, limitations, and the next allowed work
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Run TF-001.01 through TF-001.04 in parallel with disjoint evidence outputs.
2. Resolve any reproducibility gap without changing the prototype evidence being measured.
3. Run TF-001.05 after all four evidence tickets complete.
4. Close T0 only when the G0 criteria in the roadmap are evidenced.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Execution policy: implement every child ticket on its own branch in an isolated Git worktree created from current main. Record the branch, worktree path, and claimed files before editing; never share a worktree between agents. After acceptance and explicit landing authorisation, update against current main, rerun checks, merge serially to main, push, verify HEAD equals origin/main, then remove the worktree.
<!-- SECTION:NOTES:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All T0 child tickets are Done
- [ ] #2 G0 decision and raw evidence locations are linked
- [ ] #3 mise exec -- task check and git diff --check pass
- [ ] #4 Backlog acceptance criteria, notes, and final summary are current
<!-- DOD:END -->
