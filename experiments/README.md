# Experiments

This directory is reserved for short-lived, decision-oriented spikes from the
[risk-first roadmap](../docs/roadmap.md).

An experiment must have one question and an explicit deadline. Its directory
name uses the roadmap identifier, for example `e01-authoring-plan-ir`.

Every experiment must contain a README recording:

1. hypothesis and competing options;
2. representative fixture or workload;
3. measurement method and raw results;
4. pass, pivot, and stop thresholds established before implementation;
5. limitations and threats to validity;
6. recommendation and the decision/ADR it informs;
7. a single verification command.

Experiment code may copy the smallest useful idea from
`prototype/bootstrap`, but it must not import the prototype Go module. Shared
production packages must not be created inside `experiments`.

After a decision gate, an experiment is either retained as evidence, reduced
to a regression fixture, or removed. It does not silently become production
code.
