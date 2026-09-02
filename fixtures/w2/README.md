# W2 fixture: cross-target artifact pipeline

Roadmap tranche: T1. Workflow: W2. Task: TF-002.02.

Status: frozen fixture specification, experimental (`t1-w2-experimental-v1`),
per `docs/roadmap.md` section 3 rule 3a. This is a specification and a
provider-neutral graph definition, not a running system: no real remote
provider or daemon exists yet (T4-T6), so the fault scenarios below describe
what a future harness (TF-002.06, TF-002.07) or implementation (T3, T6) must
satisfy when exercised against this fixture - they are not executed here.

## Purpose (from roadmap section 4)

> Purpose: validate identity, transfer, remote placement, failure, and
> resume.
>
> ```text
> source -> Linux build -> Artifact[BackendBinary]
>                       -> Linux tests -> Report[GoTests]
>                       -> local package/inspection
> ```

Graph definition: [`graph.json`](graph.json) (schema `t1-w2-experimental-v1`).
It declares three abstract target roles (`linux-build`, `linux-test`,
`local-inspect`) and three nodes (`build`, `test`, `inspect`), matching the
shape above: `build` produces `Artifact[BackendBinary]`; `test` and `inspect`
both consume it independently (fan-out, not a chain) and produce
`Report[GoTests]` and a local inspection summary respectively.

The graph deliberately does **not** name a concrete provider (no
`prototype/bootstrap/target/ssh` or `target/local` reference). TF-001.02's
inventory (`docs/evidence/t0/package-inventory.md`) already classifies
`target/ssh` as "a deliberately crude SSH-shaped contract spike with no
production reconnection, pooling, credential, or fleet behavior" - binding
this fixture to it would make the fixture a claim about that spike, not about
W2 itself. `prototype/bootstrap/engine/runtime_integration_test.go`'s
`TestRuntimeTransfersDependencyArtifactsAcrossTargets` demonstrates the same
general shape (two targets, `Needs`, cross-target artifact transfer) against
the prototype's real machinery and was used as a reference pattern while
designing this graph, not reused directly.

## Required properties mapped to this fixture

From roadmap section 4's W2 required properties:

| Required property | How this fixture exercises it |
| --- | --- |
| Execution profile known before placement | Every target role in `graph.json` declares `required_capabilities` (os/toolchain) that must be resolvable and attested before a node is placed on it - not discovered after acquisition. This directly extends TF-001.04's finding that the current prototype resolves profile identity only *after* acquisition; this fixture's expectation is the target state, not a description of what the prototype does today. |
| Artifact manifest verified across targets | `build`'s `backend-binary` output declares a `manifest` block (digest algorithm, required fields) in `graph.json`. [`golden/corrupt-artifact.md`](golden/corrupt-artifact.md) specifies the required detection behavior when a manifest digest mismatch occurs at any downstream consumer. |
| A failed downstream node resumes on another compatible worker | [`golden/downstream-failure-resume.md`](golden/downstream-failure-resume.md): `test` fails on one `linux-test` worker instance and must resume on a distinct, capability-compatible one, without re-running `build`. |
| Successful work is not repeated | Cross-cutting assertion in `downstream-failure-resume.md` (exactly one `build` completion event regardless of `test` retries) and `cancellation.md` (already-completed `build` state survives cancellation for later reuse). |
| Provider outage and cancellation produce durable, explainable state | [`golden/provider-outage.md`](golden/provider-outage.md) (acquisition-time failure) and [`golden/cancellation.md`](golden/cancellation.md) (caller-initiated stop, two sub-cases) each require a distinct, durable, queryable outcome state - not a hang, crash, or silent loss. [`golden/worker-loss.md`](golden/worker-loss.md) covers the third failure shape (an acquired worker disappearing mid-execution), which the required-properties list implies but does not separately name; it is included because "a failed downstream node resumes on another compatible worker" only fully makes sense once worker loss itself is specified. |

## What is buildable now vs. deferred

**Buildable and included in this ticket:**

- The frozen, provider-neutral graph (`graph.json`).
- Golden behavioral specifications for all required fault/resume scenarios
  (`golden/*.md`), each with concrete assertions a future harness must
  implement.
- The property-to-specification mapping above.

**Explicitly deferred, not this ticket's scope:**

- Actual fault-injection *execution* against a real system. That is
  TF-002.06 (lifecycle fault-injection fixtures) and TF-002.07 (integrity and
  source-mutation fault fixtures) - second-wave T1 tickets that depend on
  this fixture existing first. Building fault-injection machinery here would
  duplicate their ownership.
- A concrete implementation that actually satisfies "execution profile known
  before placement" or "provider outage produces durable state" - no daemon,
  real remote provider, or profile-resolution redesign exists yet (T4-T6, and
  E04's charter per `docs/decisions/0003-g0-t0-exit.md`). Several golden
  files explicitly note where the current prototype would fail these
  assertions today (see `worker-loss.md`'s reservation-release assertion) so
  that gap is recorded rather than silently assumed away.
- Benchmark/timing metadata format (sample counts, median/p95, hardware
  profile) - that is TF-002.04's contract; this fixture's golden files defer
  to it for any numeric threshold rather than inventing one.

## Versioning

`graph.json`'s `fixture_schema_version` is `t1-w2-experimental-v1`. Per
`docs/roadmap.md` section 3 rule 3a, this fixture is frozen and reusable
(not disposable like `experiments/`), stays under this schema version until
explicitly revised, and graduates into any future production contract only
via an accepted decision record with an owner and tests (rule 4) - never
implicitly.
