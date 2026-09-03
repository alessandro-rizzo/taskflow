package conformance

import (
	"fmt"
)

// Violation is one Validate failure, naming a semantic JSON-Pointer-style
// path (e.g. "/nodes/2/needs/0") and a human-readable message (AC #4:
// "failures identify the semantic path").
type Violation struct {
	Path    string `json:"path"`
	Message string `json:"message"`
}

func (v Violation) String() string {
	return fmt.Sprintf("%s: %s", v.Path, v.Message)
}

// Validate decodes raw JSON (via decodeObject, preserving exact numbers)
// and checks it against every explicit rule this harness enforces. It
// dispatches on the required document_kind field to either validatePlan or
// validateSchema; an absent or unrecognized document_kind is itself a
// Violation rather than silently defaulting to one kind. It does not check
// candidate content against any golden; use Compare for that.
func Validate(raw []byte) ([]Violation, error) {
	doc, err := decodeObject(raw)
	if err != nil {
		return nil, err
	}

	kindStr, kindIsString := doc["document_kind"].(string)
	switch {
	case !kindIsString || kindStr == "":
		return []Violation{{Path: "/document_kind", Message: "required"}}, nil
	case DocumentKind(kindStr) == DocumentKindPlan:
		return validatePlan(doc), nil
	case DocumentKind(kindStr) == DocumentKindSchema:
		return validateSchema(doc), nil
	default:
		return []Violation{{
			Path:    "/document_kind",
			Message: fmt.Sprintf("must be %q or %q, got %q", DocumentKindPlan, DocumentKindSchema, kindStr),
		}}, nil
	}
}

// validateEnvelope checks the fields every document kind shares:
// format_version (against the kind-specific expected value), and the
// non-empty fixture_id/fixture_version/status trio every fixture-referencing
// document must carry. An independent Codex peer review found these
// fixture identity fields were previously neither required nor validated.
func validateEnvelope(doc map[string]any, expectedFormatVersion string) []Violation {
	var violations []Violation

	version, _ := doc["format_version"].(string)
	if version == "" {
		violations = append(violations, Violation{Path: "/format_version", Message: "required"})
	} else if version != expectedFormatVersion {
		violations = append(violations, Violation{
			Path:    "/format_version",
			Message: fmt.Sprintf("want %q, got %q", expectedFormatVersion, version),
		})
	}

	for _, field := range []string{"fixture_id", "fixture_version", "status"} {
		if s, ok := doc[field].(string); !ok || s == "" {
			violations = append(violations, Violation{Path: "/" + field, Message: "required"})
		}
	}

	return violations
}

func validatePlan(doc map[string]any) []Violation {
	violations := validateEnvelope(doc, CurrentPlanFormatVersion)
	violations = append(violations, checkUnknownTopLevelFields(doc, knownPlanTopLevelFields)...)

	nodes, nodeViolations := typedArray(doc, "nodes")
	violations = append(violations, nodeViolations...)
	artifacts, artifactViolations := typedArray(doc, "artifacts")
	violations = append(violations, artifactViolations...)
	services, serviceViolations := typedArray(doc, "services")
	violations = append(violations, serviceViolations...)
	secrets, secretViolations := typedArray(doc, "secrets")
	violations = append(violations, secretViolations...)
	effects, effectViolations := typedArray(doc, "effects")
	violations = append(violations, effectViolations...)

	nodeIDs := collectIdentifiers(&violations, nodes, "/nodes", knownNodeFields, "id")
	artifactIDs := collectIdentifiers(&violations, artifacts, "/artifacts", knownArtifactFields, "id")
	collectIdentifiers(&violations, services, "/services", knownServiceFields, "id")
	collectIdentifiers(&violations, secrets, "/secrets", knownSecretFields, "id")
	collectIdentifiers(&violations, effects, "/effects", knownEffectFields, "id")

	for i, n := range nodes {
		node, ok := n.(map[string]any)
		if !ok {
			continue // already reported by collectIDs's own type check
		}
		path := fmt.Sprintf("/nodes/%d", i)
		checkRefs(&violations, node, "needs", path, nodeIDs, "node")
		checkRefs(&violations, node, "consumes", path, artifactIDs, "artifact")
		checkRefs(&violations, node, "produces", path, artifactIDs, "artifact")
	}

	return violations
}

func validateSchema(doc map[string]any) []Violation {
	violations := validateEnvelope(doc, CurrentSchemaFormatVersion)
	violations = append(violations, checkUnknownTopLevelFields(doc, knownSchemaTopLevelFields)...)

	operations, opViolations := typedArray(doc, "operations")
	violations = append(violations, opViolations...)
	collectIdentifiers(&violations, operations, "/operations", knownOperationFields, "id")

	for i, o := range operations {
		op, ok := o.(map[string]any)
		if !ok {
			continue
		}
		path := fmt.Sprintf("/operations/%d", i)

		outputs, outViolations := typedArrayField(op, "outputs", path)
		violations = append(violations, outViolations...)
		collectIdentifiers(&violations, outputs, path+"/outputs", map[string]bool{"id": true, "type": true, "optional": true}, "id")

		args, argViolations := typedArrayField(op, "arguments", path)
		violations = append(violations, argViolations...)
		// Arguments are identified by "name", not "id" - collectIdentifiers
		// requires it, reports duplicates, and checks unknown fields, which
		// an independent Codex/Opus review found the previous version did
		// not do at all for arguments (an operation with duplicate argument
		// names, or an argument missing "name" entirely, produced zero
		// violations).
		collectIdentifiers(&violations, args, path+"/arguments", knownArgumentFields, "name")

		checkStringArrayField(&violations, op, "required_effects", path)
		checkStringArrayField(&violations, op, "required_capabilities", path)
	}

	return violations
}

// checkUnknownTopLevelFields reports every doc key not in known.
func checkUnknownTopLevelFields(doc map[string]any, known map[string]bool) []Violation {
	var violations []Violation
	for k := range doc {
		if !known[k] {
			violations = append(violations, Violation{Path: "/" + k, Message: "unknown top-level field"})
		}
	}
	return violations
}

// typedArray returns doc[key] as []any. If the key is absent, it returns
// (nil, nil) - the field is optional at this layer. If the key is present
// but not a JSON array, it returns a Violation instead of silently
// treating it as absent (an independent Codex peer review found the
// previous version did exactly that, via a discarded type-assertion ok
// value).
func typedArray(doc map[string]any, key string) ([]any, []Violation) {
	raw, present := doc[key]
	if !present {
		return nil, nil
	}
	arr, ok := raw.([]any)
	if !ok {
		return nil, []Violation{{Path: "/" + key, Message: "must be an array"}}
	}
	return arr, nil
}

// typedArrayField is typedArray for a field nested under an already-known
// object path (used for per-operation "outputs"/"arguments").
func typedArrayField(obj map[string]any, key, parentPath string) ([]any, []Violation) {
	raw, present := obj[key]
	if !present {
		return nil, nil
	}
	arr, ok := raw.([]any)
	if !ok {
		return nil, []Violation{{Path: parentPath + "/" + key, Message: "must be an array"}}
	}
	return arr, nil
}

// collectIdentifiers walks items (each expected to be a map[string]any with
// a string identifying field named idField - "id" for nodes/artifacts/
// services/secrets/effects/operations/outputs, "name" for arguments),
// reports a Violation for any item that is not an object, any item
// missing/with a non-string identifier, any unknown field per knownFields,
// and any duplicate identifier (an independent Codex/Opus review found
// duplicate ids, and separately duplicate/missing argument names
// specifically, were previously silently accepted). It returns the set of
// valid, unique identifiers found, for reference-checking by callers.
func collectIdentifiers(violations *[]Violation, items []any, arrayPath string, knownFields map[string]bool, idField string) map[string]bool {
	ids := map[string]bool{}
	seen := map[string]int{}
	for i, item := range items {
		path := fmt.Sprintf("%s/%d", arrayPath, i)
		obj, ok := item.(map[string]any)
		if !ok {
			*violations = append(*violations, Violation{Path: path, Message: "must be an object"})
			continue
		}
		for k := range obj {
			if !knownFields[k] {
				*violations = append(*violations, Violation{Path: path + "/" + k, Message: "unknown field"})
			}
		}
		id, idIsString := obj[idField].(string)
		if !idIsString || id == "" {
			*violations = append(*violations, Violation{Path: path + "/" + idField, Message: "required"})
			continue
		}
		seen[id]++
		ids[id] = true
	}
	for id, count := range seen {
		if count > 1 {
			*violations = append(*violations, Violation{Path: arrayPath, Message: fmt.Sprintf("duplicate %s %q (%d occurrences)", idField, id, count)})
		}
	}
	return ids
}

// checkStringArrayField verifies obj[field] (if present) is an array whose
// every entry is a string - used for operation.required_effects and
// operation.required_capabilities. A present-but-non-string entry is
// reported explicitly rather than silently accepted: Canonicalize's
// unordered-scalar-array sort (sortScalars in canonicalize.go) is now
// robust to non-string scalars regardless, but these two fields are
// semantically meant to be capability/effect name strings, and accepting
// e.g. a bare number there would be a meaningless document that still
// passed validation.
func checkStringArrayField(violations *[]Violation, obj map[string]any, field, parentPath string) {
	raw, present := obj[field]
	if !present {
		return
	}
	arr, ok := raw.([]any)
	if !ok {
		*violations = append(*violations, Violation{Path: parentPath + "/" + field, Message: "must be an array"})
		return
	}
	for i, v := range arr {
		if _, ok := v.(string); !ok {
			*violations = append(*violations, Violation{
				Path:    fmt.Sprintf("%s/%s/%d", parentPath, field, i),
				Message: "must be a string",
			})
		}
	}
}

// checkRefs verifies every entry of node[field] (a scalar array of id
// strings) resolves to an id in known. A present-but-non-string entry is
// itself reported (an independent Codex peer review found non-string
// entries were previously silently skipped via a discarded type-assertion
// ok value), not just an unresolved reference.
func checkRefs(violations *[]Violation, node map[string]any, field, nodePath string, known map[string]bool, kind string) {
	raw, present := node[field]
	if !present {
		return
	}
	refs, ok := raw.([]any)
	if !ok {
		*violations = append(*violations, Violation{Path: nodePath + "/" + field, Message: "must be an array"})
		return
	}
	for j, r := range refs {
		path := fmt.Sprintf("%s/%s/%d", nodePath, field, j)
		ref, refIsString := r.(string)
		if !refIsString {
			*violations = append(*violations, Violation{Path: path, Message: "must be a string"})
			continue
		}
		if ref == "" {
			*violations = append(*violations, Violation{Path: path, Message: "must not be empty"})
			continue
		}
		if !known[ref] {
			*violations = append(*violations, Violation{Path: path, Message: fmt.Sprintf("references unknown %s id %q", kind, ref)})
		}
	}
}
