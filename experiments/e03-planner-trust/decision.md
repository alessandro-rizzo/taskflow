# E03 planner trust-boundary decision

Status: proposed for Gate 1

Date: 2026-09-04

## Question

Can compiled project code emit a plan for an untrusted agent without inheriting
daemon filesystem, credential, network, process, resource, or authorization
power?

## Decision

Select **static descriptors for untrusted planning** at Gate 1. The descriptor
path runs no project code, preserves the hash-bound E01 schema and E02 canonical
W1 plan, passes the independent policy validator, and meets the warm planning
budget. Keep compiled planning as a research-only trusted-local possibility;
none of the executable candidates qualified in this environment.

This is a narrow decision, not a stabilized format or permanent rejection of a
sandboxed planner. Arbitrary runtime-dependent graph construction remains
unsupported for untrusted callers.

## Evidence by candidate

- **Restricted native process:** unavailable. The frozen macOS Seatbelt profile
  failed its benign positive control with `SIGABRT`, and Darwin could not apply
  the predeclared 256 MiB `RLIMIT_AS` ceiling. No attack result was credited.
- **Pooled minimal container:** exercised. Seventeen cases were blocked and
  seven were bounded; the outside canary was unchanged, no listener accepted a
  connection, and no synthetic parent marker was retained. Docker supplied an
  undeclared default `HOME`, so one case is a `trusted_local_limitation`. Under
  the frozen branch rules that single limitation disqualifies the candidate
  from untrusted-agent planning and from performance measurement.
- **Helper VM:** unavailable because no already-authorized dedicated endpoint
  existed. No VM was created or started.
- **Static descriptor:** exercised. All 25 executable abuse cases were blocked
  by not running project code. The independent validator accepted the known-good
  W1 plan and rejected all 19 parser, path, resource, target, network, secret,
  effect, and self-authorization mutations at their predeclared semantic paths.
  Thirty serial warm samples recorded median 109.754 ms and p95 118.060 ms,
  passing the strict p95-below-250-ms gate.

## Branch-rule application

Correctness and authority isolation take precedence over latency. Native did
not pass its positive control; the pooled container had a security-relevant
trusted-local limitation; and the helper VM was unavailable. The static
descriptor passed correctness and latency, so the frozen priority order selects
`static-descriptor`, not `stop-or-narrow-on-latency`.

## Consequences

- Gate 1 may rely on a hash-bound schema/descriptor plus independent validation
  for untrusted agent discovery and planning.
- Executable project planning must be opt-in trusted-local research until a
  candidate passes every hard gate without limitations.
- The daemon remains the only authority that validates targets, routes,
  secrets, effects, resources, paths, and versions.
- A planner-emitted policy or approval field is untrusted input and fails
  closed.
- The descriptor path cannot represent arbitrary dynamic code execution. A
  future bounded expansion design needs separate evidence.

## Unsupported cases and limitations

See `limitations.md`. This experiment does not prove Linux host isolation,
production Docker operation, microVM behavior, multi-tenant resistance, or a
production policy language.

## Revisit triggers

- A native profile passes a benign positive control and every frozen abuse case
  with an enforceable memory ceiling.
- A minimal container eliminates all undeclared ambient environment while
  retaining the same no-network, read-only, dropped-capability boundary.
- An approved helper VM becomes available and meets the same safety and latency
  gates.
- Representative project semantics cannot be expressed by a finite static
  descriptor from immutable inputs.
- A second independent validator disagrees on acceptance or semantic paths.

## Contracts allowed to stabilize

None before Gate 1. The selected branch and its evidence are Gate 1 inputs only.
