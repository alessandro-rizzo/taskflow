# Roadmap

The roadmap is ordered around correctness invariants rather than provider
novelty.

## Milestone 0: architecture bootstrap

- [x] Typed Go DAG.
- [x] Stable runner invocation and adapter registry.
- [x] Taskfile, Just, and direct-command adapters.
- [x] Stable target acquire/execute/release contract.
- [x] Local target.
- [x] Parallel scheduler.
- [x] Compatible-run resume behavior.
- [x] Atomic file state store.
- [x] Content-addressed cache blob store.
- [x] Structured event stream and terminal renderer.
- [ ] Cache coordinator and deterministic output archives.
- [ ] Persistent project driver and CLI loader.

## Milestone 1: excellent local runner

- `taskflow run`, `list`, `graph`, `status`, and `resume`.
- Cached compilation of project-local typed definitions.
- Source/input hashing with useful cache-explanation output.
- Output archive restore and publication.
- Resource-aware parallel scheduler.
- Signal handling and crash-recovery tests.
- Quiet, normal, verbose, and trace terminal modes.
- Shell completion.
- End-to-end Taskfile and Just fixtures.

Exit criterion: Taskflow is nicer than invoking the same local aggregate Task
directly, even without a remote target.

## Milestone 2: Fly Sprite provider

- Source snapshot transfer.
- Sprite acquire/wake/create lifecycle.
- Streaming command execution and cancellation.
- Persistent warm workspace policy.
- Checkpoint integration independent of result caching.
- Network policy and secret injection.
- Linux integration test matrix.

Exit criterion: a failed multi-node Linux pipeline resumes locally or on a
different Sprite without repeating successful cacheable work.

## Milestone 3: Tart/Orchard provider

- Orchard capability discovery and authentication.
- OCI image selection.
- Resource and label placement.
- SSH/Orchard execution transport.
- macOS/Xcode image fingerprinting.
- Explicit same-VM placement groups for simulators.
- Scaleway host bootstrap documentation.

Exit criterion: an iOS pipeline can run on a remote Mac, preserve useful
toolchain caches, and resume at a failed node.

## Milestone 4: hardening and public release

- Versioned extension compatibility policy.
- Cache schema migration policy.
- Secret redaction and threat model.
- Retry/backoff and provider outage behavior.
- Artifact retention and garbage collection.
- Performance benchmarks.
- Cross-platform packaging.
- Contributor documentation and release process.

## Non-goals before v1

- Hosted Taskflow service.
- Browser UI or full-screen terminal UI.
- Managed CI integrations.
- Windows remote provider.
- Dynamic Go plugins.
- Compatibility with arbitrary GitHub Actions workflows.
