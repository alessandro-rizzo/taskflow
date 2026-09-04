# E08 partial Phase B evidence

The approved in-process and non-mutating macOS-stub scope passed. The retained set contains 260 fault rows: 200 executable/typed-core rows and 60 explicitly labelled state-machine-analysis rows. No analysis-only row is treated as transport evidence. All 8 applicable local benchmark sets passed their frozen thresholds.

The representative SSH/Linux adapter was not available or approved. No SSH availability manifest exists, no network connection was opened, and no VM, simulator, provider, or shared host resource was mutated. Therefore AC #1 and every all-three-adapter gate remain unpassed. Frozen precedence mechanically selects `state-machine-first-transport-deferral`.

See `limitations.md`, `scorecard.json`, `raw/`, and `benchmarks/`.
