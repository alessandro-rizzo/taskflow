# T1 plan-schema conformance harness

Roadmap tranche: T1. Task: TF-002.05.

Status: pre-Gate-1 experimental fixture/harness. This is not a production
package, carries no compatibility promise, and must not be imported by any
production code (`docs/roadmap.md` section 3, rule 3a).

**Revision note:** an independent Codex peer review of the first version of
this harness found real gaps - it covered only plan documents despite the
ticket's AC #1 requiring both candidate schema and plan coverage, a W3
golden that didn't match the real `fixtures/w3` fixture, a number-precision
bug in canonicalization, and several validation-strictness gaps. This
version restructures around an explicit `document_kind` (`plan` |
`schema`), fixes the number bug, tightens validation, corrects the goldens,
and enriches diff evidence. See the "Fixed after review" section below for
specifics.

## Question

E01 and E02 (`docs/roadmap.md` section 9) both need a way to compare a
candidate typed-authoring/plan-IR implementation's output against a
deterministic, versioned expectation for W1, W2, and W3 - not a convenient
toy case each experiment picks for itself. E01 produces a **schema**
(agent-discoverable operations: arguments, outputs, effects, capabilities,
without evaluating privileged work); E02 produces a **plan** (the concrete
DAG a schema's operation lowers to when invoked). The question this harness
answers: what does "conformant" mean precisely enough - for *both* document
kinds - that two independent candidates (or the same candidate run twice,
in two processes) can be checked against the same yardstick?

## Fixture / workload

A Go library (`conformance` package: `plan.go`, `decode.go`,
`canonicalize.go`, `digest.go`, `validate.go`, `compare.go`) plus a CLI
(`cmd/t1conform`) that validates a candidate document, canonicalizes it and
a golden, compares their structural digests, and on mismatch reports every
difference with a semantic path.

Documents are **plain JSON, not Go types**: no schema or plan IR may
stabilize before Gate 1 (`docs/roadmap.md` section 3 rule 3a, section 24
item 8). Defining Go structs for `Plan`/`Schema`/`Node`/`Artifact` would
itself constitute such a contract, so `conformance` operates on generically
decoded JSON (`map[string]any` / `[]any` / `json.Number`) throughout.

Every document declares `document_kind: "plan"` or `"schema"` explicitly;
`Validate` dispatches on it rather than guessing from shape, so a malformed
document that is neither gets a precise `/document_kind` rejection.

### Goldens (`goldens/plan/`, `goldens/schema/`)

Every golden carries the same `fixture_id`/`fixture_version`/`status`
header convention `fixtures/w1/w2/w3` use, plus `document_kind` and
`format_version` (`t1-plan-conformance-plan-v2` / `-schema-v1`).

**Plan goldens** (`goldens/plan/`):

| Golden | References | Covers |
| --- | --- | --- |
| `w1-fast-project-check.plan.json` | `fixtures/w1/manifest.yaml` | format/test/lint -> aggregate check; lint's planning condition explicitly excludes `_test.go`-only changes (matching `manifest.yaml`'s own `lint-replan-on-source-change` rule - the first version of this golden got this wrong) |
| `w2-cross-target-artifact-pipeline.plan.json` | `fixtures/w2/graph.json` | build -> test + inspect; each node's `execution_profile` carries a `target_role` (`linux-build`/`linux-test`/`local-inspect`) preserving the distinct-worker-role distinction the source fixture cares about; `inspection-summary` is not marked optional, matching `graph.json` (the first version wrongly marked it optional) |
| `w3-isolated-native-mobile-stack.plan.json` | `fixtures/w3/spec.md` + `examples/namespace-a.json` | source -> linux-api-build/macos-xcode-build (both explicit build edges), a `simulator-session` artifact, and `mobile-e2e` consuming the endpoint + iOS artifact + simulator - **not** the raw Linux service directly, matching `mobile_e2e_report.consumes` in the real fixture. The endpoint is modeled as a typed `Endpoint[API]` artifact co-produced by `linux-api-build`, not an orphaned top-level `services` entry (the first version had all three of these wrong: missing simulator, wrong consumer, an unreferenced service) |
| `synthetic-full-coverage.plan.json` | none (`fixture_id: "synthetic"`, its own real `fixture_version`, not the placeholder `"n/a"` the first version used) - not tied to any real W-fixture | every field E02's own plan-fixture requirement lists: typed artifacts, an optional output, a planning condition, an outcome condition, resource requirements, an execution profile, a cache policy, a secret capability reference, a service endpoint, and an effect |

**Schema goldens** (`goldens/schema/`) - new in this revision, closing AC
#1's previously-entirely-absent "candidate schema" half:

| Golden | Operation | Covers |
| --- | --- | --- |
| `w1-fast-project-check.schema.json` | `check` | two outputs (one optional), two arguments (one with an `enum`+`default`, proving argument coverage is genuinely exercised, not just allowlisted in code), a required capability |
| `w2-cross-target-artifact-pipeline.schema.json` | `build-and-verify` | three outputs, a required capability |
| `w3-isolated-native-mobile-stack.schema.json` | `mobile-e2e` | one output, three required capabilities (Linux + macOS + simulator) |

### Self-test candidates (`testdata/plan/`, `testdata/schema/`)

No real E01/E02 candidate implementation exists yet, so the checker proves
itself against purpose-built candidates (mirroring how `fixtures/w1`
shipped three deliberately-broken repo variants to prove its own gate
isolates failures correctly), all derived programmatically from the
corresponding golden so they stay in sync with it:

| Candidate (plan) | Proves |
| --- | --- |
| `conformant.json` | A byte-identical candidate passes: same digest, zero violations |
| `reordered-but-equivalent.json` | Declaration reordering (nodes array reversed, a multi-entry `needs` list reordered) does **not** change the digest (E02) |
| `condition-changed.json` | A meaningful `outcome_condition` change **does** change the digest, with a diff naming the exact path |
| `missing-version.json` | An absent `format_version` is rejected, naming the field |
| `incompatible-version.json` | A present-but-wrong `format_version` is rejected with a version-mismatch message, not just "required" |
| `missing-fixture-id.json` | An absent `fixture_id` is rejected |
| `unknown-field.json` | An undeclared node field is rejected |
| `invalid-reference.json` | A `consumes` reference to a nonexistent artifact id is rejected, naming the dangling reference |
| `non-string-reference.json` | A non-string entry in a reference array (e.g. a number where an id string is expected) is rejected, not silently skipped |
| `wrongly-typed-nodes.json` | A `nodes` field that is present but not an array (e.g. a string) is rejected, not silently treated as zero nodes |
| `duplicate-node-id.json` / `duplicate-artifact-id.json` | Two entries sharing the same `id` are rejected |
| (a `conformance_test.go` test) | Canonicalizing the same golden twice produces byte-identical output (AC #2's repeat-generation determinism) |
| (a `conformance_test.go` test) | Two distinct large integers (`9007199254740993` vs `9007199254740992`, both beyond float64's exact-integer range) canonicalize to different digests - the number-precision fix |

| Candidate (schema) | Proves |
| --- | --- |
| `conformant.json` | Matches the W1 schema golden exactly |
| `reordered-but-equivalent.json` | Reordering an operation's `outputs` *and* `arguments` arrays does not change the digest |
| `argument-type-changed.json` | A meaningful change (the `verbosity` argument's type) **does** change the digest, with a diff naming the exact path - the schema-side equivalent of `condition-changed.json` |
| `missing-operation.json` | Dropping an operation entirely changes the digest |
| `duplicate-argument-name.json` | Two arguments sharing the same `name` are rejected |
| `missing-argument-name.json` | An argument with no `name` field is rejected |
| `non-string-capability.json` | A non-string entry in `required_capabilities` is rejected |
| `missing-version.json` / `incompatible-version.json` | Same version-enforcement coverage as the plan side |
| `unknown-field.json` | An undeclared operation field is rejected |
| (a `conformance_test.go` test) | `{"required_capabilities":[3,1,2]}` and `{"required_capabilities":[1,2,3]}` canonicalize identically (the `sortScalars` fix below), reproducing the exact case an independent Opus verification pass found |

## Verification command

```sh
cd fixtures/t1-plan-conformance
mise trust
mise install
mise exec -- task check
```

`go build ./... && go vet ./... && gofmt -l . && go test ./...` is the
underlying task-by-task equivalent. `cmd/t1conform` was also smoke-tested
manually end to end for both document kinds: `conformant.json`/
`reordered-but-equivalent.json` both produce the golden's exact digest and
exit 0; `condition-changed.json` exits 1 with a precise diff and, given
`--diff-out`, writes `diff.json` (now including both sides' fixture
id/version, both input paths, and a `reproduction_command` string) plus
copies of both inputs for reproducible offline inspection.

## Fixed after review

An independent Codex peer review of the first version found:

- **High:** AC #1's schema half was entirely absent - only plan documents
  existed. Fixed by the `document_kind` restructuring above plus three new
  schema goldens.
- **High:** the W3 golden didn't match `fixtures/w3` (missing simulator,
  `mobile-e2e` consuming the wrong artifact, an unreferenced service
  entry). Fixed - see the W3 golden's table row above.
- **High:** `json.Unmarshal` into `any` decodes numbers as float64,
  collapsing distinct large integers. Fixed via `decode.go`'s
  `json.Decoder.UseNumber()`-based decoding, used throughout
  `Canonicalize`/`Validate`/`Compare`; verified with a dedicated test.
- **Medium:** three golden/source mismatches (W1's lint condition, W2's
  collapsed target roles, W2's wrongly-optional output) - fixed, see the
  plan goldens table.
- **Medium:** version enforcement was untested and fixture-identity fields
  were unvalidated; the synthetic golden's version was a placeholder
  `"n/a"`. Fixed: `validateEnvelope` now requires and checks
  `fixture_id`/`fixture_version`/`status`, with dedicated tests for both
  missing and incompatible versions on both document kinds; the synthetic
  golden has a real version string.
- **Medium:** validation silently accepted wrongly-typed arrays,
  non-string references, and duplicate ids, and only checked unknown
  fields shallowly. Fixed: `typedArray`/`checkRefs`/`collectIDs` in
  `validate.go` now report each of these explicitly, extended to
  artifacts/services/secrets/effects/operations/arguments, not just nodes.
- **Medium:** `diff.json` evidence lacked fixture identity, input paths,
  and a reproduction command. Fixed - see `cmd/t1conform/main.go`'s
  `evidence` struct.

A second, independent Opus verification pass confirmed the W3-golden and
number-precision fixes above were genuine, but found the schema-side fix
was incomplete on its own terms:

- Every `arguments` array across all schema goldens/testdata was still
  empty (`[]`) - `default`/`enum` were allowlisted in code but never
  exercised anywhere. Fixed: the W1 schema golden now has two real
  arguments, one with `enum`+`default`.
- There was no schema-side analogue of the plan-side `condition-changed`
  test - nothing proved a meaningful schema change actually altered the
  digest with a named diff path, the single most important property this
  harness exists to prove. Fixed: `argument-type-changed.json` and
  `missing-operation.json` plus their tests.
- An operation with duplicate argument names, or an argument missing
  `name` entirely, produced zero violations. Fixed: `collectIdentifiers`
  (generalized from the former `collectIDs`) now requires and
  duplicate-checks arguments by `name`, the same way nodes/artifacts are
  checked by `id`.
- A genuinely new bug: `Canonicalize`'s unordered-scalar-array sort
  (`sortScalars`) type-asserted each element directly to `string`, so a
  non-string scalar (e.g. `json.Number`) always compared as `""` on both
  sides and was silently left in its original position -
  `{"required_capabilities":[3,1,2]}` and
  `{"required_capabilities":[1,2,3]}` canonicalized to *different*
  digests, violating AC #2's reordering-invariance guarantee. Fixed two
  ways: `sortScalars` now sorts by each element's own canonical JSON
  encoding (works for any scalar type, not just strings) rather than
  silently no-op'ing on the wrong type; and `checkStringArrayField` in
  `validate.go` separately rejects non-string entries in
  `required_effects`/`required_capabilities` at the validation layer.
  Both are tested directly.

## Limitations and open questions

- `Compare`'s structural diff is a generic recursive tree diff (map keys,
  then array-by-index after canonicalization's sort), not a
  Taskflow-domain-aware diff. It reports exactly what changed and where,
  not why it matters to a human reader - sufficient for AC #4's "identify
  the semantic path," not a polished UX.
- Reference-checking in `Validate` follows plan-side `needs`/`consumes`/
  `produces` and validates every `artifacts`/`services`/`secrets`/
  `effects`/`operations`/`arguments` entry's own fields and identifier
  uniqueness, but does not cross-check `effects[].target` against
  `services[].id` or similar inter-array references. Both the second
  Opus verification pass and the original Codex review flagged this as
  worth doing but not blocking; adding it is straightforward (the same
  `checkRefs`-style pattern already used for node references) if E01/E02
  need it, but nothing in this ticket's acceptance criteria requires it
  today.
- Nested free-form objects (`planning_condition`, `outcome_condition`,
  `resources`, `execution_profile`, `cache_policy`) are intentionally
  *not* checked for unknown fields the way top-level/node/artifact/
  operation/argument objects are - they remain opaque descriptive blobs
  by design, since their internal shape is exactly the kind of thing
  E01/E02 are still deciding, not something this harness should freeze
  prematurely. This means a typo inside e.g. `execution_profile` is not
  caught by `Validate`; it would still show up as a `Compare` diff
  against a golden, just not as a strict-schema violation on its own.
  Flagged (not blocking) by the same review pass as the item above.
- The goldens are hand-authored best guesses at what a correct future
  candidate's output should contain for each W-fixture, informed by
  `fixtures/w1/w2/w3`'s own declared expectations - they are not derived
  from any running implementation (none exists) and may need revision once
  E01/E02 actually produce something to compare.
- This ticket does not itself decide E02's "canonical JSON is sufficient
  vs. canonicalization is fragile" branch (`docs/roadmap.md` section 9); it
  demonstrates one working canonical-JSON approach (now with exact-number
  preservation) as a candidate input to that decision, not the decision
  itself.

## Recommendation

Once E01/E02 begin, point their candidate schema/plan output at
`cmd/t1conform --candidate <candidate output> --golden
goldens/<schema|plan>/<workflow>.<kind>.json` (or call the `conformance`
package directly) as the first comparability check, per the G0 decision's
(`docs/decisions/0003-g0-t0-exit.md`) direction that T1 harnesses are what
those experiments measure against.
