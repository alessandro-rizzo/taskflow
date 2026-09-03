---
id: TF-003
title: 'Risk Lab and Gate 1: converge Taskflow product architecture'
status: To Do
assignee: []
created_date: '2026-09-03 13:53'
labels:
  - risk-lab
  - gate-g1
  - coordination-only
dependencies:
  - TF-002
references:
  - docs/roadmap.md#9-risk-lab-experiments
  - docs/roadmap.md#10-gate-1-product-and-architecture-convergence
priority: high
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Roadmap tranche: Risk Lab and Gate 1; experiments E01-E08; risks R1-R12.
Outcome: coordinate bounded architecture experiments, preserve competing evidence, and reach an explicit continue, pivot, or stop decision before any production Go module is created.
Stable assumptions: T1 fixtures are experimental inputs; docs remain product truth; experiments are disposable; no schema, SDK, provider, cache, or daemon contract stabilizes before Gate 1.
Parallelism: coordination-only milestone. Agents claim leaf tickets with disjoint experiment or fixture paths; accepted merges are serialized.
Test and evidence: every experiment retains predeclared thresholds, raw evidence, limitations, recommendation, and one verification command.
Observability: experiment results use the T1 benchmark/conformance formats where applicable and record deviations explicitly.
Rollback or removal: experiments are retained as evidence, reduced to regression fixtures, or removed only by the Gate 1 decision.
Versioned formats: all formats remain explicitly experimental until Gate 1 names what may stabilize.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 E01-E06 each end in an evidence-backed branch decision, with E07/E08 tracked to their allowed completion point
- [ ] #2 Gate 1 records continue, pivot, or stop/narrow against the predeclared criteria
- [ ] #3 No production Go module or stabilized public package is created before Gate 1 accepts the semantic model and trust boundaries
- [ ] #4 Parallel work has explicit dependencies, disjoint ownership surfaces, and a serialized convergence path
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 Every child experiment and gate ticket has current evidence, limitations, and verification commands
- [ ] #2 The Gate 1 ADR is accepted before any T2 implementation ticket becomes actionable
- [ ] #3 Root and task-specific checks pass at the final convergence revision
- [ ] #4 Backlog status and final summary reflect the actual gate outcome
<!-- DOD:END -->
