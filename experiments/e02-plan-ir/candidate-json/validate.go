package candidatejson

import (
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
)

var identifier = regexp.MustCompile(`^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$`)

func MarshalPlan(plan Plan) ([]byte, error) { return json.Marshal(plan) }

func Validate(raw []byte) error {
	value, err := Decode(raw)
	if err != nil {
		return err
	}
	root, ok := value.(map[string]any)
	if !ok {
		return fmt.Errorf("$ must be an object")
	}
	if err := exact(root, "$", []string{"document_kind", "format_version", "fixture_id", "fixture_version", "status", "nodes", "artifacts"}, []string{"document_kind", "format_version", "fixture_id", "fixture_version", "status", "nodes", "artifacts", "services", "secrets", "effects"}); err != nil {
		return err
	}
	if root["document_kind"] != "plan" {
		return fmt.Errorf("$.document_kind must be plan")
	}
	if root["format_version"] != PlanFormatVersion {
		return fmt.Errorf("$.format_version incompatible")
	}
	for _, key := range []string{"fixture_id", "fixture_version", "status"} {
		if text, ok := root[key].(string); !ok || text == "" {
			return fmt.Errorf("$.%s must be a non-empty string", key)
		}
	}
	artifacts, err := objectArray(root, "artifacts", true)
	if err != nil {
		return err
	}
	nodes, err := objectArray(root, "nodes", true)
	if err != nil {
		return err
	}
	artifactIDs, err := validateDeclarations(artifacts, "$.artifacts", "artifact")
	if err != nil {
		return err
	}
	nodeIDs, err := validateDeclarations(nodes, "$.nodes", "node")
	if err != nil {
		return err
	}
	for _, spec := range []struct{ key, kind string }{{"services", "service"}, {"secrets", "secret"}, {"effects", "effect"}} {
		items, err := objectArray(root, spec.key, false)
		if err != nil {
			return err
		}
		if _, err := validateDeclarations(items, "$."+spec.key, spec.kind); err != nil {
			return err
		}
	}
	for _, node := range nodes {
		id := node["id"].(string)
		path := "$.nodes[id=" + id + "]"
		if err := exact(node, path, []string{"id", "needs", "consumes", "produces", "planning_condition", "outcome_condition", "resources", "execution_profile", "cache_policy"}, []string{"id", "needs", "consumes", "produces", "planning_condition", "outcome_condition", "resources", "execution_profile", "cache_policy"}); err != nil {
			return err
		}
		for _, ref := range []struct {
			key   string
			known map[string]bool
		}{{"needs", nodeIDs}, {"consumes", artifactIDs}, {"produces", artifactIDs}} {
			values, err := stringsArray(node, ref.key, path+"."+ref.key, true)
			if err != nil {
				return err
			}
			for _, value := range values {
				if !ref.known[value] {
					return fmt.Errorf("%s.%s references unknown %q", path, ref.key, value)
				}
			}
		}
		if err := validateCondition(node["planning_condition"], path+".planning_condition", true); err != nil {
			return err
		}
		if err := validateCondition(node["outcome_condition"], path+".outcome_condition", false); err != nil {
			return err
		}
		if err := validateResources(node["resources"], path+".resources"); err != nil {
			return err
		}
		if err := validateProfile(node["execution_profile"], path+".execution_profile"); err != nil {
			return err
		}
		if err := validateCache(node["cache_policy"], path+".cache_policy"); err != nil {
			return err
		}
	}
	return nil
}

func exact(object map[string]any, path string, required, allowed []string) error {
	allowedSet := map[string]bool{}
	for _, key := range allowed {
		allowedSet[key] = true
	}
	for key := range object {
		if !allowedSet[key] {
			return fmt.Errorf("%s.%s unknown field", path, key)
		}
	}
	for _, key := range required {
		if _, ok := object[key]; !ok {
			return fmt.Errorf("%s.%s required", path, key)
		}
	}
	return nil
}

func objectArray(parent map[string]any, key string, required bool) ([]map[string]any, error) {
	value, exists := parent[key]
	if !exists {
		if required {
			return nil, fmt.Errorf("$.%s required", key)
		}
		return nil, nil
	}
	array, ok := value.([]any)
	if !ok {
		return nil, fmt.Errorf("$.%s must be an array", key)
	}
	out := make([]map[string]any, len(array))
	for i, item := range array {
		object, ok := item.(map[string]any)
		if !ok {
			return nil, fmt.Errorf("$.%s[%d] must be an object", key, i)
		}
		out[i] = object
	}
	return out, nil
}

func validateDeclarations(items []map[string]any, path, kind string) (map[string]bool, error) {
	ids := map[string]bool{}
	for index, item := range items {
		id, ok := item["id"].(string)
		if !ok || !identifier.MatchString(id) {
			return nil, fmt.Errorf("%s[%d].id invalid", path, index)
		}
		if ids[id] {
			return nil, fmt.Errorf("%s duplicate id %q", path, id)
		}
		ids[id] = true
		entryPath := path + "[id=" + id + "]"
		switch kind {
		case "artifact":
			if err := exact(item, entryPath, []string{"id", "type", "optional"}, []string{"id", "type", "optional"}); err != nil {
				return nil, err
			}
			if text, ok := item["type"].(string); !ok || text == "" {
				return nil, fmt.Errorf("%s.type must be a non-empty string", entryPath)
			}
			if _, ok := item["optional"].(bool); !ok {
				return nil, fmt.Errorf("%s.optional must be boolean", entryPath)
			}
		case "node":
		case "service":
			if err := exact(item, entryPath, []string{"id", "name", "route"}, []string{"id", "name", "route"}); err != nil {
				return nil, err
			}
			if err := stringFields(item, entryPath, "name", "route"); err != nil {
				return nil, err
			}
		case "secret":
			if err := exact(item, entryPath, []string{"id", "capability", "resolved_by"}, []string{"id", "capability", "resolved_by"}); err != nil {
				return nil, err
			}
			if item["resolved_by"] != "daemon" {
				return nil, fmt.Errorf("%s.resolved_by must be daemon", entryPath)
			}
			if err := stringFields(item, entryPath, "capability", "resolved_by"); err != nil {
				return nil, err
			}
		case "effect":
			if err := exact(item, entryPath, []string{"id", "kind", "target", "idempotency_key", "authorized_actor"}, []string{"id", "kind", "target", "idempotency_key", "authorized_actor"}); err != nil {
				return nil, err
			}
			if err := stringFields(item, entryPath, "kind", "target", "idempotency_key", "authorized_actor"); err != nil {
				return nil, err
			}
		}
	}
	return ids, nil
}

func stringFields(item map[string]any, path string, keys ...string) error {
	for _, key := range keys {
		if text, ok := item[key].(string); !ok || text == "" {
			return fmt.Errorf("%s.%s must be a non-empty string", path, key)
		}
	}
	return nil
}

func stringsArray(parent map[string]any, key, path string, required bool) ([]string, error) {
	value, exists := parent[key]
	if !exists {
		if required {
			return nil, fmt.Errorf("%s required", path)
		}
		return nil, nil
	}
	array, ok := value.([]any)
	if !ok {
		return nil, fmt.Errorf("%s must be an array", path)
	}
	out := make([]string, len(array))
	seen := map[string]bool{}
	for i, item := range array {
		text, ok := item.(string)
		if !ok {
			return nil, fmt.Errorf("%s[%d] must be a string", path, i)
		}
		if seen[text] {
			return nil, fmt.Errorf("%s duplicate %q", path, text)
		}
		seen[text] = true
		out[i] = text
	}
	return out, nil
}

func object(value any, path string) (map[string]any, error) {
	result, ok := value.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("%s must be an object", path)
	}
	return result, nil
}

func validateCondition(value any, path string, planning bool) error {
	condition, err := object(value, path)
	if err != nil {
		return err
	}
	kind, ok := condition["type"].(string)
	if !ok {
		return fmt.Errorf("%s.type required", path)
	}
	if planning && kind == "changed-paths" {
		if err := exact(condition, path, []string{"type", "patterns"}, []string{"type", "patterns", "exclude_patterns"}); err != nil {
			return err
		}
		_, err = stringsArray(condition, "patterns", path+".patterns", true)
		if err != nil {
			return err
		}
		_, err = stringsArray(condition, "exclude_patterns", path+".exclude_patterns", false)
		return err
	}
	allowed := map[string]bool{"always": true}
	if !planning {
		allowed["all-upstream-pass"] = true
		allowed["conditional"] = true
	}
	if !allowed[kind] {
		return fmt.Errorf("%s.type invalid", path)
	}
	return exact(condition, path, []string{"type"}, []string{"type"})
}

func validateResources(value any, path string) error {
	item, err := object(value, path)
	if err != nil {
		return err
	}
	if err = exact(item, path, []string{"cpu_millicores", "memory_mib"}, []string{"cpu_millicores", "memory_mib"}); err != nil {
		return err
	}
	for _, key := range []string{"cpu_millicores", "memory_mib"} {
		number, ok := item[key].(int64)
		if !ok || number < 0 {
			return fmt.Errorf("%s.%s must be a nonnegative integer", path, key)
		}
	}
	return nil
}
func validateProfile(value any, path string) error {
	item, err := object(value, path)
	if err != nil {
		return err
	}
	if err = exact(item, path, []string{"os", "toolchain"}, []string{"os", "toolchain", "profile_digest", "profile_id", "target_role"}); err != nil {
		return err
	}
	for _, key := range []string{"os", "toolchain", "profile_digest", "profile_id", "target_role"} {
		if _, exists := item[key]; !exists {
			continue
		}
		if text, ok := item[key].(string); !ok || text == "" {
			return fmt.Errorf("%s.%s must be non-empty", path, key)
		}
	}
	return nil
}
func validateCache(value any, path string) error {
	item, err := object(value, path)
	if err != nil {
		return err
	}
	mode, ok := item["mode"].(string)
	if !ok {
		return fmt.Errorf("%s.mode required", path)
	}
	if mode == "none" {
		return exact(item, path, []string{"mode"}, []string{"mode"})
	}
	if mode != "content-addressed" {
		return fmt.Errorf("%s.mode invalid", path)
	}
	if err = exact(item, path, []string{"mode", "key_inputs"}, []string{"mode", "key_inputs"}); err != nil {
		return err
	}
	_, err = stringsArray(item, "key_inputs", path+".key_inputs", true)
	return err
}

func SortedKeys(values map[string]bool) []string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}
