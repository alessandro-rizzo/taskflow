# Malicious-planner abuse fixture

Roadmap tranche: T1. Experiment input: E03. Task: TF-002.08.

Status: pre-Gate-1 experimental fixture. This is not a production package,
carries no compatibility promise, and must not be imported by any production
code (`docs/roadmap.md` section 3, rule 3a).

## Critical framing: this is not a security boundary

**No planner and no sandbox exists anywhere in this repository yet.**
`docs/roadmap.md`'s E03 experiment (project-planner trust boundary) - which
this fixture exists to feed - has not run. There is nothing in
`prototype/bootstrap` or elsewhere that this fixture attacks, and nothing
here proves anything about the safety of this repository, this machine, or
any real system.

What this fixture actually is: a versioned **catalogue** of the attack
attempts E03 must eventually run against a real candidate planner sandbox
(native subprocess with OS sandbox controls, a pooled minimal
planning sandbox/container, a microVM, or a declarative/code-generated
registration path - see roadmap section 9's E03 "Approaches to compare"),
plus a **safe, synthetic self-test** standing in for each attempt today.
Every self-test targets only resources this fixture creates and owns
itself:

- filesystem attempts read/write only inside a throwaway temp directory the
  run creates and removes;
- the environment attempt reads and writes only a synthetic env var this run
  owns, capturing and restoring any pre-existing value of that exact name
  afterward - never a real ambient variable, and never left altered;
- the network attempt opens a loopback listener on `127.0.0.1` and dials it
  **while still holding it open** (never close-then-dial - see "Safety
  bounds" below for why), so a successful connect can only ever reach this
  self-test's own listener, never a real external host or an unrelated local
  service;
- the process attempt spawns exactly one known-safe trivial child, resolved
  by stat-ing a fixed list of absolute paths itself (never PATH/shell
  lookup, which an attacker-controlled `PATH` could hijack), run with an
  explicit minimal environment (never this process's real ambient
  environment, which could otherwise contain real credentials), and reaps it
  immediately;
- the resource attempt allocates at most 1 MiB across at most 1000
  iterations, never growing without bound;
- the output attempt embeds only a synthetic, obviously-fake secret marker
  this run generates itself, never a real credential.

**A note on scope:** the guarantees above cover the six synthetic attempts
above only. `attackcat`'s own CLI conveniences - resolving `--source-revision`
by shelling out to `git rev-parse HEAD` in the real current directory, and
writing to whatever `--out` path is given - operate on real ambient state
(the actual repository, an arbitrary real file path) by design, since the
CLI needs to record where it ran and where to write its output. This is an
explicit, intentional exception outside the "only resources it creates"
guarantee, not an oversight.

Running `attackcat` today proves the catalogue is well-formed, deterministic,
non-hanging, and non-leaking. It does **not** prove any real planner sandbox
correctly blocks, bounds, or limits these attacks - that verification can
only happen once E03 has a real candidate to run this catalogue against.

## Catalogue

`attack.go`'s `Catalogue()` returns six entries, one per category AC #1
requires, mapped 1:1 to `docs/roadmap.md`'s E03 "Attack fixture attempts"
list:

| ID | Category | What a real planner sandbox must guarantee |
| --- | --- | --- |
| `fs-read-outside-source` | filesystem | reject any read outside the declared source view |
| `env-read-ambient` | environment | not expose the daemon's ambient process environment or credentials |
| `net-dial-loopback` | network | deny outbound network/local socket access unless explicitly authorized |
| `process-spawn-and-persist` | process | ensure no spawned descendant outlives the planning invocation |
| `resource-unbounded-growth` | resource | enforce CPU/memory/file-descriptor/output/wall-time limits |
| `output-secret-leak` | output | ensure no secret material or unsafe path ever appears in the emitted plan |

Each entry's `ExpectedOutcome` uses E03's own vocabulary from roadmap section
9's continue criteria - `blocked`, `bounded`, or `trusted_local_limitation`
- not a bare allow/deny, since some attempts (e.g. process lifecycle,
resource caps) are naturally about bounding rather than outright denial.

`CatalogueVersion` (`t1-malicious-planner-v1-experimental`) and
`ResultEnvelopeVersion` are versioned independently, per roadmap rule 3a and
because a result format can evolve without the attack catalogue itself
changing.

## Safety bounds

Every `Attempt.Run` is bounded by its own 2-second `context.WithTimeout`
(`perAttemptTimeout`); the entire `RunSuite` call is additionally bounded by
one 30-second suite-level timeout (`suiteTimeout`) regardless of how many
attempts the catalogue grows to contain. These bounds are enforced, not
cooperative: `runOneAttemptBounded` runs each `Attempt.Run` in its own
goroutine and `select`s between it finishing and the per-attempt deadline
firing, so an attempt that ignores `ctx` entirely and never returns is still
correctly reported as `timed_out` instead of blocking `RunSuite` -
`attack_test.go`'s `TestAttemptThatIgnoresContextIsReportedAsTimedOut`
verifies this directly with a `Run` that deliberately `select{}`s forever.
The one honest caveat: Go has no way to forcibly kill a goroutine, so a
genuinely hung `Run` still leaks that one goroutine for the life of the
process - what's guaranteed is that `RunSuite` itself never blocks past its
bounds and never reports a result it did not actually observe within them.

Every `Attempt.Run` also executes under `recover()`
(`runAttemptRecoveringPanics`): a panic inside any attempt - including one
that panics with the run's own secret marker in its message - is caught,
redacted like any other error text, and recorded as that attempt's failure,
rather than crashing the whole suite or reaching stderr unredacted.
`TestPanickingAttemptIsRecoveredAndRedacted` verifies both the recovery and
the redaction together.

`attack_test.go`'s `TestEveryAttemptCompletesWithinItsBound` and
`TestRunSuiteCompletesWellWithinSuiteTimeout` assert the normal (non-hung,
non-panicking) case completes well within bounds empirically, not just by
inspection. In practice the whole suite completes in well under a second.

## Synthetic secrets and redaction

`RunSuite` generates one fresh, `crypto/rand`-backed secret marker per run,
in a fixed, obviously-fake format
(`SYNTHETIC-TEST-SECRET-<16 hex chars>-DO-NOT-USE`) that never resembles a
real API key, token, or password format. Only the `output-secret-leak`
attempt deliberately embeds it in its own diagnostic text - this is
intentional: it exists so `Redact` (applied to every attempt's diagnostic
and error text before persistence, regardless of category) is exercised
against a real occurrence of the secret, not only asserted to exist in the
abstract. `attack_test.go`'s `TestRunSuiteNeverPersistsSecret` runs the real
suite, asserts the generated secret does not appear anywhere in the
persisted result (scanning the full serialized JSON envelope, not just one
field), and asserts `SuiteResult.AnySecretLeak` - the suite's own runtime
self-check of the same property - agrees.

`Redact`'s scope is deliberately narrow: it replaces exact, complete,
verbatim occurrences of the secret string only. It does not detect a secret
split across multiple fields, partially truncated, or transformed (e.g.
base64-encoded) before being embedded. This is an accepted limitation, not
an oversight: every `Run` in this catalogue generates and embeds the secret
as one atomic Go string via `fmt.Sprintf`, never splitting or re-encoding
it, so exact-match redaction is sufficient for every attempt this fixture
currently defines. A future attempt that transforms the secret before
embedding it would need its own redaction handling.

## Running it

```sh
cd fixtures/malicious-planner
mise trust
mise install
mise exec -- task check
```

Or directly:

```sh
go run ./cmd/attackcat --out /tmp/malicious-planner-result.json
```

`attackcat` exits nonzero if any self-test errors, times out, or leaks the
run's secret marker into persisted evidence.

## Limitations and open questions

- This fixture cannot and does not evaluate whether a real planner sandbox
  correctly enforces the boundaries in the table above - there is no real
  sandbox yet. It is a target catalogue for E03, not a completed security
  test.
- The catalogue's six attempts are a starting set matching AC #1's required
  categories, not an exhaustive attack surface. E03 is expected to extend it
  (parser/version-ambiguity exploitation and privileged-target/effect
  requests, both named in roadmap section 9's E03 attack list, are not yet
  separately modeled here beyond what `output-secret-leak`/`env-read-ambient`
  imply) as real candidate sandboxes reveal gaps.
- `ExpectedOutcome` values are this fixture's own judgment call about which
  E03 continue-criteria category each attempt belongs to; E03's own decision
  record may reclassify any of them with evidence.
- Only macOS and Linux were exercised while building this fixture; the
  self-tests use only POSIX-portable Go stdlib calls (`os`, `net`,
  `os/exec`), so no platform-specific behavior is expected, but this has not
  been verified on Windows.

## Recommendation

Adopt this catalogue as E03's starting attack-fixture set. When E03 selects
a candidate planner-sandboxing approach, replace each attempt's synthetic
`Run` self-test with one that actually drives that candidate and asserts its
`ExpectedOutcome`, keeping the same `ID`/`DiagnosticAssertion` so results
stay comparable across candidates.

## Verification command

```sh
cd fixtures/malicious-planner
mise trust
mise install
mise exec -- task check
```
