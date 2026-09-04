package candidatejson

import (
	"bytes"
	"encoding/json"
	"fmt"
	"sort"
)

type Difference struct {
	Path           string `json:"path"`
	Classification string `json:"classification"`
	Before         any    `json:"before"`
	After          any    `json:"after"`
}

type ResumeReport struct {
	FormatVersion string       `json:"format_version"`
	Compatible    bool         `json:"compatible"`
	Differences   []Difference `json:"differences"`
}

func ResumeDiff(beforeRaw, afterRaw []byte) (ResumeReport, error) {
	if err := Validate(beforeRaw); err != nil {
		return ResumeReport{}, fmt.Errorf("before: %w", err)
	}
	if err := Validate(afterRaw); err != nil {
		return ResumeReport{}, fmt.Errorf("after: %w", err)
	}
	before, err := Decode(beforeRaw)
	if err != nil {
		return ResumeReport{}, fmt.Errorf("before: %w", err)
	}
	after, err := Decode(afterRaw)
	if err != nil {
		return ResumeReport{}, fmt.Errorf("after: %w", err)
	}
	before, err = normalize(before, "$")
	if err != nil {
		return ResumeReport{}, err
	}
	after, err = normalize(after, "$")
	if err != nil {
		return ResumeReport{}, err
	}
	differences := []Difference{}
	diffValue("$", before, after, &differences)
	sort.Slice(differences, func(i, j int) bool { return differences[i].Path < differences[j].Path })
	return ResumeReport{FormatVersion: "e02-resume-diff-v1", Compatible: len(differences) == 0, Differences: differences}, nil
}

func diffValue(path string, before, after any, differences *[]Difference) {
	if equalValue(before, after) {
		return
	}
	beforeMap, bm := before.(map[string]any)
	afterMap, am := after.(map[string]any)
	if bm && am {
		keys := map[string]bool{}
		for key := range beforeMap {
			keys[key] = true
		}
		for key := range afterMap {
			keys[key] = true
		}
		for _, key := range SortedKeys(keys) {
			diffValue(path+"."+key, beforeMap[key], afterMap[key], differences)
		}
		return
	}
	beforeArray, ba := before.([]any)
	afterArray, aa := after.([]any)
	if ba && aa {
		if rule, ok := setLike[path]; ok && rule.objectID != "" {
			beforeByID := byID(beforeArray)
			afterByID := byID(afterArray)
			keys := map[string]bool{}
			for key := range beforeByID {
				keys[key] = true
			}
			for key := range afterByID {
				keys[key] = true
			}
			for _, key := range SortedKeys(keys) {
				diffValue(path+"[id="+key+"]", beforeByID[key], afterByID[key], differences)
			}
			return
		}
		*differences = append(*differences, Difference{Path: path, Classification: "structural-incompatible", Before: before, After: after})
		return
	}
	*differences = append(*differences, Difference{Path: path, Classification: "structural-incompatible", Before: before, After: after})
}

func byID(values []any) map[string]any {
	result := map[string]any{}
	for _, value := range values {
		if object, ok := value.(map[string]any); ok {
			if id, ok := object["id"].(string); ok {
				result[id] = object
			}
		}
	}
	return result
}
func equalValue(left, right any) bool {
	a, _ := json.Marshal(left)
	b, _ := json.Marshal(right)
	return bytes.Equal(a, b)
}
