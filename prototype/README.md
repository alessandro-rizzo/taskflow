# Prototypes

This directory preserves implementations that provide architectural evidence
but are not the current product foundation.

## `bootstrap`

[`bootstrap`](bootstrap/README.md) is the original Taskflow architecture
bootstrap. It demonstrates a compiled Go DAG, runner adapters, local and SSH
target contracts, parallel scheduling, durable journaled resume,
content-addressed artifacts, and a compiled project-driver protocol.

It is intentionally isolated:

- it has its own Go module, Taskfile, mise configuration, `.taskflow` project,
  tests, and historical documentation;
- new root product code must not import it;
- it should change only to keep the prototype reproducible, fix a serious
  defect that invalidates its evidence, or support a named comparison
  experiment;
- useful concepts may be reimplemented after a roadmap decision gate, but its
  APIs are not compatibility constraints.

Run its gate from the repository root with `task prototype:check` or from the
prototype directory with `mise exec -- task check`.
