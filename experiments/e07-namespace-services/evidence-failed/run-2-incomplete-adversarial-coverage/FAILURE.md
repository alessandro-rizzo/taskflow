# Retained invalidated E07 evidence set 2

The run and fail-closed verifier passed every frozen numeric gate, but final
self-review against the approved implementation plan found two omitted
adversarial observations: a guessed credential sent directly to the internal
loopback service, and the slow-health timeout mode. The evidence is therefore
retained but excluded from the decision.

The correction adds both observations, changes no threshold, workload count,
ordering rule, or decision precedence, and restarts the full run from sample
one. Direct guesses must receive HTTP 403 and count as zero successes; slow
health joins unhealthy and early-exit evidence under the unchanged two-second
drain bound.
