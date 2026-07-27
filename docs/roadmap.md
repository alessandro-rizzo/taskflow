# Roadmap

The roadmap is ordered around correctness invariants rather than provider
novelty.

## Milestone 0: architecture bootstrap

- [x] Typed Go DAG.
- [x] Stable runner invocation and adapter registry.
- [x] Taskfile, Just, and direct-command adapters.
- [x] Resource-aware reserve/acquire/transfer/execute/release contract.
- [x] Local target.
- [x] Parallel scheduler.
- [x] Compatible-run resume behavior.
- [x] Revisioned transition journal with exclusive run locking.
- [x] Content-addressed cache blob store.
- [x] Structured event stream and terminal renderer.
- [x] Cache coordinator and deterministic output archives.
- [x] Compiled project driver, cached CLI loader, and version handshake spike.
- [x] Crude SSH provider that exercises the remote contract.

## Milestone 1: excellent local runner

- [x] `taskflow run`, `list`, `graph`, and `resume`.
- [ ] `taskflow status`.
- [x] Cached compilation of project-local typed definitions.
- [ ] Recursively fingerprint local driver extension dependencies.
- [x] Source/input hashing.
- [ ] Useful cache-explanation output.
- [x] Output archive restore, publication, and manifest verification.
- [x] Resource-aware, per-provider admission.
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
- State/cache schema migration registries and compatibility policy.
- Provider outage and reconnection behavior.
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
