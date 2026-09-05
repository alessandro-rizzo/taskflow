# E08 three-shape Phase B evidence

The same typed core now drives the in-process adapter, a real ARM64 Linux/OpenSSH worker hosted in an isolated local Colima VM, and the non-mutating E06-shaped macOS stub. All 390 retained fault rows pass: 300 executable/typed rows and 90 explicitly labelled analysis-only rows. All 13 benchmark sets pass their frozen thresholds.

The SSH/Linux records include 125 manifest-bound connections across benchmark and fault evidence, strict host-key and experiment-key authentication, digest-verified materialization, command allowlisting, persistent operation replay across new SSH connections, two compatible worker identities, exact cleanup, and orphan query. Cache hits and TryReserve open zero SSH connections.

Frozen precedence still selects `state-machine-first-transport-deferral`: six SSH fault cases per repetition remain analysis-only or boundary-only, and local VM evidence cannot prove WAN/provider/credential-broker/physical-host-loss/cross-host behavior. See `limitations.md`, `scorecard.json`, `ssh-linux/`, `raw/`, and `benchmarks/`.
