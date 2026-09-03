package conformance

import (
	"os"
	"path/filepath"
	"testing"
)

func readFile(t *testing.T, path string) []byte {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(filepath.FromSlash(path)))
	if err != nil {
		t.Fatalf("reading %s: %v", path, err)
	}
	return data
}

func hasViolationAtPath(violations []Violation, path string) bool {
	for _, v := range violations {
		if v.Path == path {
			return true
		}
	}
	return false
}

func hasViolationWithMessage(violations []Violation, message string) bool {
	for _, v := range violations {
		if v.Message == message {
			return true
		}
	}
	return false
}

// --- Plan document tests ---

func TestPlanConformantCandidateMatchesGolden(t *testing.T) {
	candidate := readFile(t, "testdata/plan/conformant.json")
	golden := readFile(t, "goldens/plan/w1-fast-project-check.plan.json")

	violations, err := Validate(candidate)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if len(violations) != 0 {
		t.Fatalf("expected no violations, got: %v", violations)
	}

	candidateCanonical, err := Canonicalize(candidate)
	if err != nil {
		t.Fatalf("Canonicalize candidate: %v", err)
	}
	goldenCanonical, err := Canonicalize(golden)
	if err != nil {
		t.Fatalf("Canonicalize golden: %v", err)
	}
	if Digest(candidateCanonical) != Digest(goldenCanonical) {
		diffs, _ := Compare(candidateCanonical, goldenCanonical)
		t.Fatalf("expected matching digest, got diffs: %v", diffs)
	}
}

func TestPlanReorderedButEquivalentMatchesGoldenDigest(t *testing.T) {
	candidate := readFile(t, "testdata/plan/reordered-but-equivalent.json")
	golden := readFile(t, "goldens/plan/w1-fast-project-check.plan.json")

	candidateCanonical, err := Canonicalize(candidate)
	if err != nil {
		t.Fatalf("Canonicalize candidate: %v", err)
	}
	goldenCanonical, err := Canonicalize(golden)
	if err != nil {
		t.Fatalf("Canonicalize golden: %v", err)
	}
	if Digest(candidateCanonical) != Digest(goldenCanonical) {
		t.Fatal("expected declaration reordering to not affect the structural digest (E02), but digests differ")
	}
}

func TestPlanConditionChangeAltersDigest(t *testing.T) {
	candidate := readFile(t, "testdata/plan/condition-changed.json")
	golden := readFile(t, "goldens/plan/w1-fast-project-check.plan.json")

	candidateCanonical, err := Canonicalize(candidate)
	if err != nil {
		t.Fatalf("Canonicalize candidate: %v", err)
	}
	goldenCanonical, err := Canonicalize(golden)
	if err != nil {
		t.Fatalf("Canonicalize golden: %v", err)
	}
	if Digest(candidateCanonical) == Digest(goldenCanonical) {
		t.Fatal("expected a meaningful outcome_condition change to alter the digest (E02), but it did not")
	}
	diffs, err := Compare(candidateCanonical, goldenCanonical)
	if err != nil {
		t.Fatalf("Compare: %v", err)
	}
	// Deliberately asserted on diff content rather than a hand-guessed path
	// index (canonicalization sorts nodes by id, so the exact index depends
	// on sort order and previously caused a wrong assertion during
	// development - this form does not silently pass if that sort order
	// ever changes).
	found := false
	for _, d := range diffs {
		if d.Golden == "always" && d.Candidate == "only-on-format-pass" {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected a diff changing outcome_condition.type from \"always\" to \"only-on-format-pass\", got: %v", diffs)
	}
}

func TestPlanMissingFormatVersionRejected(t *testing.T) {
	candidate := readFile(t, "testdata/plan/missing-version.json")
	violations, err := Validate(candidate)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if !hasViolationAtPath(violations, "/format_version") {
		t.Fatalf("expected a violation at /format_version, got: %v", violations)
	}
}

func TestPlanIncompatibleFormatVersionRejected(t *testing.T) {
	candidate := readFile(t, "testdata/plan/incompatible-version.json")
	violations, err := Validate(candidate)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	found := false
	for _, v := range violations {
		if v.Path == "/format_version" && v.Message != "required" {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected a version-mismatch violation (not just 'required') at /format_version, got: %v", violations)
	}
}

func TestPlanMissingFixtureIDRejected(t *testing.T) {
	candidate := readFile(t, "testdata/plan/missing-fixture-id.json")
	violations, err := Validate(candidate)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if !hasViolationAtPath(violations, "/fixture_id") {
		t.Fatalf("expected a violation at /fixture_id, got: %v", violations)
	}
}

func TestPlanUnknownNodeFieldRejected(t *testing.T) {
	candidate := readFile(t, "testdata/plan/unknown-field.json")
	violations, err := Validate(candidate)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if !hasViolationAtPath(violations, "/nodes/1/priority") {
		t.Fatalf("expected an unknown-field violation at /nodes/1/priority, got: %v", violations)
	}
}

func TestPlanInvalidReferenceRejected(t *testing.T) {
	candidate := readFile(t, "testdata/plan/invalid-reference.json")
	violations, err := Validate(candidate)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if !hasViolationWithMessage(violations, `references unknown artifact id "nonexistent-input"`) {
		t.Fatalf("expected a dangling-reference violation naming nonexistent-input, got: %v", violations)
	}
}

func TestPlanNonStringReferenceRejected(t *testing.T) {
	candidate := readFile(t, "testdata/plan/non-string-reference.json")
	violations, err := Validate(candidate)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if !hasViolationWithMessage(violations, "must be a string") {
		t.Fatalf("expected a 'must be a string' violation for the non-string reference entry, got: %v", violations)
	}
}

func TestPlanWronglyTypedNodesFieldRejected(t *testing.T) {
	candidate := readFile(t, "testdata/plan/wrongly-typed-nodes.json")
	violations, err := Validate(candidate)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if !hasViolationAtPath(violations, "/nodes") {
		t.Fatalf("expected a violation at /nodes for a non-array value, got: %v", violations)
	}
}

func TestPlanDuplicateNodeIDRejected(t *testing.T) {
	candidate := readFile(t, "testdata/plan/duplicate-node-id.json")
	violations, err := Validate(candidate)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	found := false
	for _, v := range violations {
		if v.Path == "/nodes" {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected a duplicate-id violation at /nodes, got: %v", violations)
	}
}

func TestPlanDuplicateArtifactIDRejected(t *testing.T) {
	candidate := readFile(t, "testdata/plan/duplicate-artifact-id.json")
	violations, err := Validate(candidate)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	found := false
	for _, v := range violations {
		if v.Path == "/artifacts" {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected a duplicate-id violation at /artifacts, got: %v", violations)
	}
}

func TestPlanRepeatedCanonicalizationIsByteEquivalent(t *testing.T) {
	golden := readFile(t, "goldens/plan/w1-fast-project-check.plan.json")
	first, err := Canonicalize(golden)
	if err != nil {
		t.Fatalf("Canonicalize (1st): %v", err)
	}
	second, err := Canonicalize(golden)
	if err != nil {
		t.Fatalf("Canonicalize (2nd): %v", err)
	}
	if string(first) != string(second) {
		t.Fatal("expected repeated canonical encoding to be byte-equivalent (AC #2)")
	}
}

func TestAllPlanGoldensValidateAndCanonicalizeCleanly(t *testing.T) {
	for _, name := range []string{
		"w1-fast-project-check.plan.json",
		"w2-cross-target-artifact-pipeline.plan.json",
		"w3-isolated-native-mobile-stack.plan.json",
		"synthetic-full-coverage.plan.json",
	} {
		t.Run(name, func(t *testing.T) {
			golden := readFile(t, "goldens/plan/"+name)
			violations, err := Validate(golden)
			if err != nil {
				t.Fatalf("Validate: %v", err)
			}
			if len(violations) != 0 {
				t.Fatalf("golden itself should have no violations, got: %v", violations)
			}
			if _, err := Canonicalize(golden); err != nil {
				t.Fatalf("Canonicalize: %v", err)
			}
		})
	}
}

// --- Schema document tests (AC #1's previously-absent "candidate schema"
// half) ---

func TestSchemaConformantCandidateMatchesGolden(t *testing.T) {
	candidate := readFile(t, "testdata/schema/conformant.json")
	golden := readFile(t, "goldens/schema/w1-fast-project-check.schema.json")

	violations, err := Validate(candidate)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if len(violations) != 0 {
		t.Fatalf("expected no violations, got: %v", violations)
	}

	candidateCanonical, err := Canonicalize(candidate)
	if err != nil {
		t.Fatalf("Canonicalize candidate: %v", err)
	}
	goldenCanonical, err := Canonicalize(golden)
	if err != nil {
		t.Fatalf("Canonicalize golden: %v", err)
	}
	if Digest(candidateCanonical) != Digest(goldenCanonical) {
		diffs, _ := Compare(candidateCanonical, goldenCanonical)
		t.Fatalf("expected matching digest, got diffs: %v", diffs)
	}
}

func TestSchemaReorderedOutputsMatchGoldenDigest(t *testing.T) {
	candidate := readFile(t, "testdata/schema/reordered-but-equivalent.json")
	golden := readFile(t, "goldens/schema/w1-fast-project-check.schema.json")

	candidateCanonical, err := Canonicalize(candidate)
	if err != nil {
		t.Fatalf("Canonicalize candidate: %v", err)
	}
	goldenCanonical, err := Canonicalize(golden)
	if err != nil {
		t.Fatalf("Canonicalize golden: %v", err)
	}
	if Digest(candidateCanonical) != Digest(goldenCanonical) {
		t.Fatal("expected reordering an operation's outputs array to not affect the structural digest, but digests differ")
	}
}

// TestSchemaArgumentTypeChangeAltersDigest is the schema-side equivalent of
// TestPlanConditionChangeAltersDigest: proves a meaningful schema change (an
// argument's type) alters the digest and produces a diff naming the exact
// path. An independent Opus verification pass found the first revision had
// no schema-side analogue of this - the single most important property
// this harness exists to prove was untested on the schema side.
func TestSchemaArgumentTypeChangeAltersDigest(t *testing.T) {
	candidate := readFile(t, "testdata/schema/argument-type-changed.json")
	golden := readFile(t, "goldens/schema/w1-fast-project-check.schema.json")

	candidateCanonical, err := Canonicalize(candidate)
	if err != nil {
		t.Fatalf("Canonicalize candidate: %v", err)
	}
	goldenCanonical, err := Canonicalize(golden)
	if err != nil {
		t.Fatalf("Canonicalize golden: %v", err)
	}
	if Digest(candidateCanonical) == Digest(goldenCanonical) {
		t.Fatal("expected a meaningful argument type change to alter the digest, but it did not")
	}
	diffs, err := Compare(candidateCanonical, goldenCanonical)
	if err != nil {
		t.Fatalf("Compare: %v", err)
	}
	found := false
	for _, d := range diffs {
		if d.Golden == "string" && d.Candidate == "int" {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected a diff changing the verbosity argument's type from \"string\" to \"int\", got: %v", diffs)
	}
}

// TestSchemaMissingOperationAltersDigest proves dropping an entire
// operation is a meaningful change too, not just a change within one.
func TestSchemaMissingOperationAltersDigest(t *testing.T) {
	candidate := readFile(t, "testdata/schema/missing-operation.json")
	golden := readFile(t, "goldens/schema/w1-fast-project-check.schema.json")

	candidateCanonical, err := Canonicalize(candidate)
	if err != nil {
		t.Fatalf("Canonicalize candidate: %v", err)
	}
	goldenCanonical, err := Canonicalize(golden)
	if err != nil {
		t.Fatalf("Canonicalize golden: %v", err)
	}
	if Digest(candidateCanonical) == Digest(goldenCanonical) {
		t.Fatal("expected a missing operation to alter the digest, but it did not")
	}
	diffs, err := Compare(candidateCanonical, goldenCanonical)
	if err != nil {
		t.Fatalf("Compare: %v", err)
	}
	if len(diffs) == 0 {
		t.Fatal("expected at least one diff for a missing operation")
	}
}

func TestSchemaDuplicateArgumentNameRejected(t *testing.T) {
	candidate := readFile(t, "testdata/schema/duplicate-argument-name.json")
	violations, err := Validate(candidate)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	found := false
	for _, v := range violations {
		if v.Path == "/operations/0/arguments" {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected a duplicate-name violation at /operations/0/arguments, got: %v", violations)
	}
}

func TestSchemaMissingArgumentNameRejected(t *testing.T) {
	candidate := readFile(t, "testdata/schema/missing-argument-name.json")
	violations, err := Validate(candidate)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if !hasViolationAtPath(violations, "/operations/0/arguments/0/name") {
		t.Fatalf("expected a violation at /operations/0/arguments/0/name, got: %v", violations)
	}
}

func TestSchemaNonStringCapabilityRejected(t *testing.T) {
	candidate := readFile(t, "testdata/schema/non-string-capability.json")
	violations, err := Validate(candidate)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if !hasViolationAtPath(violations, "/operations/0/required_capabilities/1") {
		t.Fatalf("expected a violation at /operations/0/required_capabilities/1, got: %v", violations)
	}
}

func TestSchemaMissingFormatVersionRejected(t *testing.T) {
	candidate := readFile(t, "testdata/schema/missing-version.json")
	violations, err := Validate(candidate)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if !hasViolationAtPath(violations, "/format_version") {
		t.Fatalf("expected a violation at /format_version, got: %v", violations)
	}
}

func TestSchemaIncompatibleFormatVersionRejected(t *testing.T) {
	candidate := readFile(t, "testdata/schema/incompatible-version.json")
	violations, err := Validate(candidate)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	found := false
	for _, v := range violations {
		if v.Path == "/format_version" && v.Message != "required" {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected a version-mismatch violation at /format_version, got: %v", violations)
	}
}

func TestSchemaUnknownOperationFieldRejected(t *testing.T) {
	candidate := readFile(t, "testdata/schema/unknown-field.json")
	violations, err := Validate(candidate)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if !hasViolationWithMessage(violations, "unknown field") {
		t.Fatalf("expected an 'unknown field' violation on the operation object, got: %v", violations)
	}
}

func TestAllSchemaGoldensValidateAndCanonicalizeCleanly(t *testing.T) {
	for _, name := range []string{
		"w1-fast-project-check.schema.json",
		"w2-cross-target-artifact-pipeline.schema.json",
		"w3-isolated-native-mobile-stack.schema.json",
	} {
		t.Run(name, func(t *testing.T) {
			golden := readFile(t, "goldens/schema/"+name)
			violations, err := Validate(golden)
			if err != nil {
				t.Fatalf("Validate: %v", err)
			}
			if len(violations) != 0 {
				t.Fatalf("golden itself should have no violations, got: %v", violations)
			}
			if _, err := Canonicalize(golden); err != nil {
				t.Fatalf("Canonicalize: %v", err)
			}
		})
	}
}

// --- Cross-cutting ---

func TestUnrecognizedDocumentKindRejected(t *testing.T) {
	raw := []byte(`{"document_kind": "not-a-real-kind", "format_version": "x"}`)
	violations, err := Validate(raw)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if !hasViolationAtPath(violations, "/document_kind") {
		t.Fatalf("expected a violation at /document_kind, got: %v", violations)
	}
}

func TestMissingDocumentKindRejected(t *testing.T) {
	raw := []byte(`{"format_version": "x"}`)
	violations, err := Validate(raw)
	if err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if !hasViolationAtPath(violations, "/document_kind") {
		t.Fatalf("expected a violation at /document_kind, got: %v", violations)
	}
}

// TestNonStringScalarArrayReorderingIsCanonicalizedConsistently is a direct
// regression test for the exact case an independent Opus verification pass
// found: sortScalars previously type-asserted each element directly to
// string, so a non-string scalar (e.g. json.Number) always compared as ""
// on both sides and was silently left in its original position -
// {"required_capabilities":[3,1,2]} and {"required_capabilities":[1,2,3]}
// canonicalized to different digests despite representing the same set.
// This operates below Validate (which now separately requires these
// specific fields to be all-strings) to prove Canonicalize itself is
// robust, since it is exported and callable without validating first.
func TestNonStringScalarArrayReorderingIsCanonicalizedConsistently(t *testing.T) {
	a := []byte(`{"required_capabilities":[3,1,2]}`)
	b := []byte(`{"required_capabilities":[1,2,3]}`)

	ca, err := Canonicalize(a)
	if err != nil {
		t.Fatalf("Canonicalize a: %v", err)
	}
	cb, err := Canonicalize(b)
	if err != nil {
		t.Fatalf("Canonicalize b: %v", err)
	}
	if Digest(ca) != Digest(cb) {
		t.Fatalf("expected reordering a non-string unordered scalar array to not change the digest, got %s (%s) vs %s (%s)", ca, Digest(ca), cb, Digest(cb))
	}
}

// TestLargeIntegersSurviveCanonicalization proves the number-precision fix:
// json.Unmarshal into `any` decodes numbers as float64 by default, which
// loses precision above 2^53 and can make two distinct large integers
// canonicalize identically. An independent Codex peer review found exactly
// this bug; Canonicalize now decodes via json.Decoder.UseNumber() (see
// decode.go) to preserve exact digit sequences.
func TestLargeIntegersSurviveCanonicalization(t *testing.T) {
	a := []byte(`{"n": 9007199254740993}`)
	b := []byte(`{"n": 9007199254740992}`)

	ca, err := Canonicalize(a)
	if err != nil {
		t.Fatalf("Canonicalize a: %v", err)
	}
	cb, err := Canonicalize(b)
	if err != nil {
		t.Fatalf("Canonicalize b: %v", err)
	}
	if Digest(ca) == Digest(cb) {
		t.Fatalf("expected two distinct large integers to canonicalize differently, got identical digests (got %s and %s)", ca, cb)
	}
}
