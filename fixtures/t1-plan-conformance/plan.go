// Package conformance defines the T1 conformance checker for both candidate
// schema documents (E01) and candidate plan documents (E02): canonical
// encoding, structural digesting, strict validation, and semantic-path
// diffing against frozen W1/W2/W3 goldens (see docs/roadmap.md section 9's
// E01/E02 requirements, and README.md in this directory for scope and
// status).
//
// Documents are plain JSON, not Go types: no schema or plan IR may
// stabilize before Gate 1 (docs/roadmap.md section 3 rule 3a, section 24
// item 8), so this package operates on generically decoded JSON
// (map[string]any / []any / json.Number) rather than typed Plan/Schema
// structs that would themselves constitute such a contract.
package conformance

// DocumentKind distinguishes the two document types this package checks.
// Every document declares its kind explicitly via the required
// document_kind field, rather than having its kind inferred from shape, so
// a malformed document that is neither gets a precise rejection instead of
// silently matching the wrong validator.
type DocumentKind string

const (
	DocumentKindPlan   DocumentKind = "plan"
	DocumentKindSchema DocumentKind = "schema"
)

// CurrentPlanFormatVersion and CurrentSchemaFormatVersion are the only
// format_version values Validate accepts for each DocumentKind. Pre-Gate-1
// formats carry no compatibility promise (roadmap section 2.6): a breaking
// change bumps the relevant string. CurrentPlanFormatVersion is v2 because
// an independent Codex peer review found v1 had no schema-side coverage at
// all (only plan documents existed) and used float64-lossy number decoding;
// both are breaking changes to the envelope, not additive ones.
const (
	CurrentPlanFormatVersion   = "t1-plan-conformance-plan-v2"
	CurrentSchemaFormatVersion = "t1-plan-conformance-schema-v1"
)

// unorderedArrayKeys names JSON object keys whose array value is a list of
// objects treated as an unordered set during canonicalization: declaration
// order in the source document must not affect the structural digest (E02:
// "declaration reordering that is semantically irrelevant does not alter
// the structural digest"). Each value names the field used to sort the
// array's elements. Key names are unique across both document kinds -
// "effects" (plan-level effect objects) and schema's per-operation
// "required_effects" (a scalar array) are deliberately different key names
// to avoid ambiguity in this key-name-only dispatch.
var unorderedArrayKeys = map[string]string{
	// Plan documents.
	"nodes":     "id",
	"artifacts": "id",
	"services":  "id",
	"secrets":   "id",
	"effects":   "id",
	// Schema documents.
	"operations": "id",
	"outputs":    "id",
	"arguments":  "name",
}

// unorderedScalarArrayKeys names JSON object keys whose array value is a
// list of plain strings (not objects) treated as an unordered set.
var unorderedScalarArrayKeys = map[string]bool{
	// Plan documents.
	"needs":    true,
	"consumes": true,
	"produces": true,
	// Schema documents.
	"required_effects":      true,
	"required_capabilities": true,
}

// knownEnvelopeFields are required/allowed on every document regardless of
// kind. knownPlanTopLevelFields and knownSchemaTopLevelFields extend it
// with kind-specific top-level fields.
var knownEnvelopeFields = map[string]bool{
	"document_kind":   true,
	"format_version":  true,
	"fixture_id":      true,
	"fixture_version": true,
	"status":          true,
}

var knownPlanTopLevelFields = unionFields(knownEnvelopeFields, map[string]bool{
	"nodes":     true,
	"artifacts": true,
	"services":  true,
	"secrets":   true,
	"effects":   true,
})

var knownSchemaTopLevelFields = unionFields(knownEnvelopeFields, map[string]bool{
	"operations": true,
})

var knownNodeFields = map[string]bool{
	"id":                 true,
	"needs":              true,
	"consumes":           true,
	"produces":           true,
	"planning_condition": true,
	"outcome_condition":  true,
	"resources":          true,
	"execution_profile":  true,
	"cache_policy":       true,
}

var knownArtifactFields = map[string]bool{
	"id":       true,
	"type":     true,
	"optional": true,
}

var knownServiceFields = map[string]bool{
	"id":    true,
	"name":  true,
	"route": true,
}

var knownSecretFields = map[string]bool{
	"id":          true,
	"capability":  true,
	"resolved_by": true,
}

var knownEffectFields = map[string]bool{
	"id":               true,
	"kind":             true,
	"target":           true,
	"idempotency_key":  true,
	"authorized_actor": true,
}

var knownOperationFields = map[string]bool{
	"id":                    true,
	"description":           true,
	"arguments":             true,
	"outputs":               true,
	"required_effects":      true,
	"required_capabilities": true,
}

var knownArgumentFields = map[string]bool{
	"name":     true,
	"type":     true,
	"default":  true,
	"enum":     true,
	"required": true,
}

func unionFields(a, b map[string]bool) map[string]bool {
	out := make(map[string]bool, len(a)+len(b))
	for k := range a {
		out[k] = true
	}
	for k := range b {
		out[k] = true
	}
	return out
}
