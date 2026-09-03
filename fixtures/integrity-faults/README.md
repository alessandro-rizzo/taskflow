# T1 integrity and source-mutation fault fixtures

Roadmap tranche: T1. Experiment input: E04. Workflows: W1-W2. Task: TF-002.07.

Fixture id: `t1-integrity-faults`. Version: `t1-integrity-faults-v1-experimental`.
Manifest schema version: `ManifestSchemaVersion` = `t1-integrity-faults-manifest/v1`
(roadmap section 3 rule 3a: frozen and reusable, not disposable, pre-Gate-1,
may change incompatibly).

Status: pre-Gate-1 experimental fixture. Not a production package, carries
no compatibility promise, and must not be imported by any production code.

> **Read this before treating anything below as E04 evidence.** This
> fixture's `Store.Lookup` reserves *before* it looks anything up - the
> same order TF-001.04 measured in the actual prototype today. **E04's own
> required demonstration #5 asks a correct future implementation to achieve
> the OPPOSITE order** (a cache hit performs *zero* provider
> reservations). Nothing in this fixture demonstrates, argues for, or
> should be read as progress toward that property. It exists solely so
> this toy store's event ordering doesn't silently contradict what T0
> already measured. See "What this is NOT" below for the rest of this
> fixture's boundaries.

## What this is

A real, isolated Go module (own `go.mod`, not wired into the root or into
`prototype/bootstrap`) implementing a small, deliberately toy reference
snapshot mechanism (`Snapshot`/`Take`) and cache store (`Store`), used to
**demonstrate** - not define - the source-mutation, cache-corruption, and
resume-integrity properties E04's required demonstrations 1, 4, and 7
(`docs/roadmap.md#e04-immutable-source-lightweight-sandbox-and-cache-identity`)
need falsifiable evidence for. Every test in this module actually runs
against real (if toy) code and is mutation-tested (see "Evidence" below) -
this ticket's outcome statement asks to "falsify" behaviour, which a JSON
specification alone cannot do.

This module went through one round of independent adversarial review
(Codex) after its first implementation, which found the original "stale
entry" test was not actually testing staleness (see AC #3 below for what
changed) and that altered-but-present outputs were not detected at all
(see AC #1 below). Both are fixed and re-verified; see "Evidence".

## What this is NOT

- **Not the future production cache-key algorithm.** `Store.Lookup` takes a
  caller-supplied `identity` string; this package does not compute or
  define how a real implementation should derive one from source, inputs,
  process, profile, policy, and dependency manifests (that is exactly
  E04's own open question, per `docs/decisions/0003-g0-t0-exit.md`'s
  "Open questions handed to E04" #1).
- **Not evidence that reservation-before-lookup is correct, or any kind of
  progress toward E04's required demonstration #5** ("a cache hit performs
  zero provider reservations/acquisitions") - see the banner at the top of
  this file. This fixture's ordering is deliberately consistent with what
  TF-001.04 measured in the prototype today (`reserve` precedes
  lookup/verification), which is the *opposite* of what E04 needs a future
  implementation to achieve. This is stated in three places on purpose
  (here, in `store.go`'s `Event kinds` doc comment, and the banner above)
  because it is the single easiest thing about this fixture to
  misrepresent by omission.
- **Not proof that a real execution consumes frozen source content rather
  than a live, mutable root.** `Snapshot.Take` freezes *identity metadata*
  - a digest and a path->digest map, computed once - and
  `TestSourceMutationAfterSnapshotDoesNotAlterDeclaredSource` proves that
  metadata cannot be retroactively altered by a later filesystem mutation.
  It does **not** prove, and this fixture does not attempt to prove, that
  any hypothetical execution step reads from the frozen digest'd content
  rather than re-reading the (possibly-since-mutated) live directory -
  that would require an actual execution/materialization mechanism, which
  does not exist in this fixture or anywhere in this repository yet. The
  claim is narrower than it may look at a glance: *the declared identity
  is immutable*, not *the bytes an eventual execution consumes are
  immutable*. E04's required demonstration #1 is broader than what this
  fixture alone establishes.
- **Not a real filesystem sandbox, namespace, or process isolation
  mechanism.** `Snapshot.Take` reads files once and never touches the
  filesystem again; it does not create a copy-on-write workspace, overlay,
  or any of E04's actual candidate approaches (Merkle/CAS, namespace/
  overlay, APFS clone, pooled container/microVM).

## Structure

- `snapshot.go` / `snapshot_test.go` - `Take(dir) Snapshot`: content-addressed,
  point-in-time directory digest. Demonstrates AC #2 (identity-freezing
  only - see "What this is NOT").
- `store.go` / `store_test.go` - `Store`: toy in-memory cache with `Put`/
  `Lookup`, ordered per-call `Event` logging (`EventsForCall`), and six
  independent verification checks: manifest schema version, source
  freshness, content digest, manifest size, declared-output presence,
  declared-output content. Demonstrates AC #1, #3, #4.

## Evidence

### Manifest schema version is actually enforced

An independent Opus review (checking the Codex-review fixes above) found
that `ManifestSchemaVersion`'s doc comment claimed this package "accepts"
only that version, while nothing in `Lookup` actually checked it - a probe
entry with `SchemaVersion: "totally-bogus/v99"` looked up successfully.
Fixed: `Lookup` now checks `Manifest.SchemaVersion` first, before any other
verification step, and rejects with `ErrManifestSchemaVersion` if it does
not match. `TestLookupRejectsUnrecognizedManifestSchemaVersion` proves
this, and the check was mutation-tested the same way as every other check
below (disabled, confirmed the test then fails with `got: <nil>`, restored).

### AC #1: independently corrupt artifact content, manifest metadata, and resume output presence (missing OR altered)

Four dedicated tests, each corrupting exactly one dimension while leaving
the others valid:

| Test | Corrupts | Leaves valid | Error |
| --- | --- | --- | --- |
| `TestLookupDetectsCorruptContentIndependentlyOfManifest` | one content byte, same length | manifest | `ErrContentCorrupt` |
| `TestLookupDetectsCorruptManifestIndependentlyOfContent` | `Manifest.SizeBytes` only | content bytes and their digest | `ErrManifestCorrupt` |
| `TestLookupDetectsMissingDeclaredOutput` | omits one of two declared outputs from `Outputs` entirely | content, manifest, the other output | `ErrOutputMissing` |
| `TestLookupDetectsAlteredDeclaredOutputIndependentlyOfMissing` | replaces a *present* output's bytes after its `DeclaredOutput.Digest` was computed from the original | content, manifest, output presence | `ErrOutputAltered`, and confirmed distinct from `ErrOutputMissing` |

The last row closes a gap an independent Codex review found in this
fixture's first implementation: the original `DeclaredOutputs []string`
only checked output *names* were present, so a present-but-mutated output
silently passed. `DeclaredOutputs` is now `[]DeclaredOutput{Name, Digest}`,
and `Lookup` verifies each declared output's actual content digest, not
just its presence.

**Mutation-tested, not just passing by construction**: each of the six
`Store.Lookup` checks (schema version, source, content, manifest,
output-missing, output-altered) was temporarily disabled (via a throwaway
`if false && ...` patch to its guard clause, reverted immediately after)
and its corresponding test was confirmed to fail with `got: <nil>` - i.e.
the disabled check let a corrupted/stale/unrecognized entry through as a
success - before the fix was restored and the full suite re-verified
green. This is direct evidence the six checks are genuinely independent,
not merely tests that happen to fail for the same underlying reason. Example for the
content check (the other four were verified the same way, each with its
own guard clause):

```sh
python3 - <<'PY'
with open('store.go') as f: c = f.read()
c = c.replace('if contentDigest != e.Manifest.Digest {',
              'if false && contentDigest != e.Manifest.Digest {')
open('store.go', 'w').write(c)
PY
go test -run TestLookupDetectsCorruptContentIndependentlyOfManifest -v ./...
# -> FAIL: expected ErrContentCorrupt, got: <nil>
# restore store.go from the pre-patch copy, then:
go build ./... && go vet ./... && gofmt -l . && go test ./...   # confirm clean again
```

An earlier version of the content-corruption test used replacement content
of a *different length* than the original, which happened to also trip the
manifest size check - caught by this same disable-and-rerun method
(disabling only the content check still made that version of the test
fail, but for the wrong, masked reason). The test was rewritten to flip
one byte in place, preserving length, before this evidence was recorded.

### AC #2: source mutation after snapshot cannot alter the declared run source

`TestSourceMutationAfterSnapshotDoesNotAlterDeclaredSource`: takes a
snapshot, copies its `Digest`/`Files` by value, mutates the live source
directory (edits an existing file, adds a new one), then asserts the
original `Snapshot` value is still byte-for-byte identical to what it was
immediately after `Take` returned. A companion assertion confirms a *fresh*
`Take` of the now-mutated directory legitimately produces a *different*
digest, ruling out a test that would pass even if `Take` were broken (e.g.
always returning a constant). See "What this is NOT" above for exactly
what this test does and does not establish.

### AC #3: a stale or corrupt ready-cache entry is rejected before returning success

**This AC required a real fix, not just new evidence.** The first
implementation's "stale entry" test stored an entry under an OLD identity
key and looked up a NEW, different identity key, asserting `ErrMiss` - an
independent Codex review correctly identified that this is an ordinary
cache miss on a different key, not a demonstration that a *stale* entry is
*rejected*. The root cause: `Manifest` had no source-provenance field, so
there was no way to represent "this entry is found under its own key, and
is otherwise well-formed, but is stale relative to what the source now
is" - exactly the scenario that matters.

Fixed by adding `Manifest.SourceDigest` (the `Snapshot.Digest` an entry was
produced from) and a `currentSourceDigest` parameter to `Lookup`.
`TestLookupRejectsStaleEntryUnderSameIdentityAfterSourceMutation` now:

1. stores an entry under identity `X`, produced from source snapshot `A`;
2. confirms it is a genuinely valid hit against snapshot `A` (so the later
   rejection is attributable to staleness, not some other defect);
3. mutates the source to snapshot `B` via the real `Take` mechanism;
4. looks up the SAME identity `X`, declaring the CURRENT source digest is
   `B`;
5. asserts `ErrStaleSource`, that `lookup-hit` still appears in the event
   trail (the entry genuinely IS found, distinguishing this from an
   ordinary miss), and that the rejection happens before any success event.

The original scenario is kept as
`TestLookupMissOnDifferentIdentityIsOrdinaryNotStale` - a real, useful, but
more modest property (different keys don't collide), explicitly
distinguished in its own doc comment from the staleness test above so the
two are not conflated again.

`assertRejectedBeforeSuccess` (used by every corruption/staleness test)
checks the call-scoped `Event` trail directly via `EventsForCall`:
`EventSuccess` never appears, and the specific failing `verify-*-fail`
event immediately precedes the final `EventReject`. This is checked
against the actual recorded event order, not inferred from the returned
error alone.

### AC #4: evidence records identity inputs, lookup/reservation ordering, and precise rejection diagnostics

Every `Store.Lookup` call is assigned a `CallID` and appends an ordered
per-call `[]Event` (`reserve`, `lookup-start`, `lookup-hit`/`miss`,
`verify-start`, `verify-{source,content,manifest,output}-{ok,fail}`,
`reject`/`success`), retrievable in isolation via `EventsForCall(callID)`.
Each `Event` carries the `identity` it was for and a human-readable
`Detail` string (e.g. `"content digest %s != manifest digest %s"`, `"entry
source digest %s != current source digest %s"`) naming the exact values
that disagreed, not just that a mismatch occurred. Scoping by `CallID`
(rather than one global `Store.Events` log, which the first implementation
used) matters once a test performs more than one `Lookup` in sequence -
`TestLookupRejectsStaleEntryUnderSameIdentityAfterSourceMutation` does
exactly that (a confirming hit, then the staleness-triggering call), and an
assertion scanning the whole store's history could not cleanly distinguish
one call's outcome from the other's.

## Verification command

```sh
cd fixtures/integrity-faults
mise trust
mise install
mise exec -- task check
```

## Limitations and open questions

- Single-process, in-memory only. Does not exercise real filesystem
  concurrency, process crashes, or network transfer corruption.
- `Store.Lookup`'s reservation-before-lookup ordering is deliberately
  consistent with TF-001.04's measured prototype ordering; per the banner
  at the top of this file, it is the opposite of what E04 needs and must
  not be read as evidence toward E04's demonstration #5.
- `Snapshot.Take` freezes identity metadata, not proof that any execution
  consumes frozen content rather than a live root - see "What this is NOT".
- Identity and source-digest binding in this fixture are always bare
  strings the caller supplies directly; real cache identity (source +
  inputs + process + profile + policy + dependency manifests, per E04's
  required demonstration #4) is an open design question this fixture does
  not answer.
- Open question for TF-002.09 (T1 exit convergence): whether E04 should
  extend this toy `Store`/`Snapshot` pair directly as scaffolding for its
  own experiment code, or treat it purely as a fault-catalogue reference
  and build its own instrumented harness against a real candidate
  mechanism (Merkle/CAS, overlay, APFS clone, etc.) - this fixture does not
  decide that, per AGENTS.md ("Coordinate shared contracts through the
  owning ticket").
