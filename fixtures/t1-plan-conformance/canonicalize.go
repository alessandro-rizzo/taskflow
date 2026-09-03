package conformance

import (
	"encoding/json"
	"fmt"
	"sort"
)

// Canonicalize decodes raw JSON (preserving exact number literals via
// decodeAny/json.Number - see decode.go), normalizes unordered arrays (see
// unorderedArrayKeys/unorderedScalarArrayKeys) so semantically-irrelevant
// declaration order does not affect the result, and re-marshals
// deterministically (encoding/json sorts object keys for map[string]any by
// construction, so no separate key-sorting step is needed, and marshals
// json.Number verbatim rather than lossily through float64). It does not
// validate the document; call Validate first if that matters to the
// caller.
func Canonicalize(raw []byte) ([]byte, error) {
	doc, err := decodeAny(raw)
	if err != nil {
		return nil, err
	}
	normalized := normalize(doc, "")
	out, err := json.Marshal(normalized)
	if err != nil {
		return nil, fmt.Errorf("re-marshaling: %w", err)
	}
	return out, nil
}

// normalize walks doc recursively, sorting any array found under a key
// named in unorderedArrayKeys/unorderedScalarArrayKeys.
func normalize(v any, key string) any {
	switch val := v.(type) {
	case map[string]any:
		out := make(map[string]any, len(val))
		for k, vv := range val {
			out[k] = normalize(vv, k)
		}
		return out
	case []any:
		normalized := make([]any, len(val))
		for i, vv := range val {
			normalized[i] = normalize(vv, key)
		}
		if idField, ok := unorderedArrayKeys[key]; ok {
			sortObjectsByField(normalized, idField)
		} else if unorderedScalarArrayKeys[key] {
			sortScalars(normalized)
		}
		return normalized
	default:
		return val
	}
}

func sortObjectsByField(items []any, field string) {
	sort.Slice(items, func(i, j int) bool {
		return idOf(items[i], field) < idOf(items[j], field)
	})
}

func idOf(item any, field string) string {
	m, ok := item.(map[string]any)
	if !ok {
		return ""
	}
	s, _ := m[field].(string)
	return s
}

// sortScalars gives items a deterministic total order regardless of scalar
// type, by comparing each element's own canonical JSON encoding rather than
// assuming every element is a string. The previous version type-asserted
// directly to string, so a non-string scalar (e.g. a json.Number) silently
// produced "" on both sides of every comparison - sort.Slice then leaves
// such elements in their original declaration order instead of actually
// sorting them, which broke the reordering-invariance guarantee for any
// unordered scalar array that happened to contain non-strings (an
// independent Codex peer review found this: {"required_capabilities":[3,1,2]}
// and {"required_capabilities":[1,2,3]} canonicalized to different digests).
// Validate now also rejects non-string entries in these fields directly
// (see checkStringArrayField in validate.go), but this fix does not depend
// on Validate having run first - Canonicalize is exported and callable on
// its own.
func sortScalars(items []any) {
	sort.Slice(items, func(i, j int) bool {
		return scalarSortKey(items[i]) < scalarSortKey(items[j])
	})
}

func scalarSortKey(v any) string {
	b, err := json.Marshal(v)
	if err != nil {
		return fmt.Sprintf("%v", v)
	}
	return string(b)
}
