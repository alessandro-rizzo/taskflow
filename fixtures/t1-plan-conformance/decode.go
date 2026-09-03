package conformance

import (
	"bytes"
	"encoding/json"
	"fmt"
)

// decodeAny decodes raw JSON into a generic any value with json.Number used
// for every number literal (via json.Decoder.UseNumber()), instead of the
// default float64. Plain json.Unmarshal into any silently loses precision
// for integers beyond float64's 53-bit mantissa (e.g. 9007199254740993 and
// 9007199254740992 both decode to the same float64), which would let two
// structurally distinct plan/schema documents canonicalize to the same
// bytes - exactly the kind of collision Canonicalize/Digest exist to rule
// out. Every decode path in this package (Canonicalize, Validate, Compare)
// must go through this helper, not json.Unmarshal directly.
func decodeAny(raw []byte) (any, error) {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var doc any
	if err := dec.Decode(&doc); err != nil {
		return nil, fmt.Errorf("decoding JSON: %w", err)
	}
	return doc, nil
}

// decodeObject is decodeAny specialized for the common case of a top-level
// JSON object, returning a clear error if the document is not one.
func decodeObject(raw []byte) (map[string]any, error) {
	doc, err := decodeAny(raw)
	if err != nil {
		return nil, err
	}
	obj, ok := doc.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("top-level document must be a JSON object")
	}
	return obj, nil
}

// Envelope is a best-effort, non-validating read of a document's identity
// fields, for callers (e.g. cmd/t1conform's diff evidence) that want to
// label a result without duplicating Validate's strict rules. Any field
// that is absent or the wrong type comes back as an empty string; use
// Validate for actual enforcement.
type Envelope struct {
	DocumentKind   string
	FormatVersion  string
	FixtureID      string
	FixtureVersion string
	Status         string
}

// ReadEnvelope extracts Envelope from raw JSON, ignoring any error from a
// malformed document (returning a zero Envelope in that case) since it is
// diagnostic, not authoritative.
func ReadEnvelope(raw []byte) Envelope {
	doc, err := decodeObject(raw)
	if err != nil {
		return Envelope{}
	}
	return Envelope{
		DocumentKind:   stringField(doc, "document_kind"),
		FormatVersion:  stringField(doc, "format_version"),
		FixtureID:      stringField(doc, "fixture_id"),
		FixtureVersion: stringField(doc, "fixture_version"),
		Status:         stringField(doc, "status"),
	}
}

func stringField(doc map[string]any, key string) string {
	s, _ := doc[key].(string)
	return s
}
