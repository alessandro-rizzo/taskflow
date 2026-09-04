# E05 decision: stop-narrow

The frozen decision matrix selects **stop-narrow** at precedence
order 6. The shared weighted-aging scheduler
passes safety, fairness, durability, attachment, cleanup, and simulator-proxy
operations gates, but it does not meet the predeclared material scheduling
benefit at either four or twenty agents. Thresholds were not changed after
results were observed.

Key observed decision inputs:

- material benefit at 20 agents: `false`
- material benefit at 4 or 20 agents: `false`
- SQLite durability gate: `true`
- weighted safety: `true`
- operations proxy: `true`
- unique full-run ownership passing results: `2`

This is a Gate 1 experiment recommendation, not a production architecture or
permission to stabilize a daemon API. The result says the tested shared
controller adds trustworthy ownership semantics, but the frozen workload does
not justify its breadth on scheduling efficiency alone. Narrower ownership
mechanisms should be considered at convergence.
