package candidatejson

import (
	"bytes"
	"encoding/json"
	"testing"
)

func TestPlansValidateAndCanonicalize(t *testing.T) {
	for _, item := range []struct {
		name string
		plan Plan
	}{{"w1", mustW1(t)}, {"w2", W2()}, {"w3", W3()}, {"synthetic", Synthetic()}} {
		t.Run(item.name, func(t *testing.T) {
			raw, err := MarshalPlan(item.plan)
			if err != nil {
				t.Fatal(err)
			}
			if err := Validate(raw); err != nil {
				t.Fatal(err)
			}
			first, err := Canonicalize(raw)
			if err != nil {
				t.Fatal(err)
			}
			second, err := Canonicalize(first)
			if err != nil {
				t.Fatal(err)
			}
			if string(first) != string(second) {
				t.Fatal("canonicalization is not idempotent")
			}
		})
	}
}
func TestCanonicalReordering(t *testing.T) {
	plan := Synthetic()
	plan.Nodes[0].PlanningCondition.Patterns = []string{"z/**", "a/**"}
	plan.Nodes[0].PlanningCondition.ExcludePatterns = []string{"z", "a"}
	plan.Nodes[0].CachePolicy.KeyInputs = []string{"source-tree", "release-binary"}
	raw, _ := MarshalPlan(plan)
	first, err := Canonicalize(raw)
	if err != nil {
		t.Fatal(err)
	}
	for left, right := 0, len(plan.Nodes)-1; left < right; left, right = left+1, right-1 {
		plan.Nodes[left], plan.Nodes[right] = plan.Nodes[right], plan.Nodes[left]
	}
	for left, right := 0, len(plan.Artifacts)-1; left < right; left, right = left+1, right-1 {
		plan.Artifacts[left], plan.Artifacts[right] = plan.Artifacts[right], plan.Artifacts[left]
	}
	raw, _ = MarshalPlan(plan)
	second, err := Canonicalize(raw)
	if err != nil {
		t.Fatal(err)
	}
	if string(first) != string(second) {
		t.Fatal("set-like declaration reordering changed bytes")
	}
}
func TestStrictNumbersDuplicatesAndUnknowns(t *testing.T) {
	for _, raw := range [][]byte{[]byte(`{"document_kind":"plan","document_kind":"plan"}`), []byte(`{"value":-0}`), []byte(`{"value":1.5}`)} {
		if _, err := Canonicalize(raw); err == nil {
			t.Fatalf("accepted %s", raw)
		}
	}
	plan := mustW1(t)
	raw, _ := MarshalPlan(plan)
	var object map[string]any
	json.Unmarshal(raw, &object)
	object["unexpected"] = true
	raw, _ = json.Marshal(object)
	if err := Validate(raw); err == nil {
		t.Fatal("accepted unknown field")
	}
}
func TestResumeSemanticPath(t *testing.T) {
	plan := mustW1(t)
	before, _ := MarshalPlan(plan)
	plan.Nodes[2].PlanningCondition.Patterns = []string{"**/*.go", "**/*.mod"}
	after, _ := MarshalPlan(plan)
	report, err := ResumeDiff(before, after)
	if err != nil {
		t.Fatal(err)
	}
	if len(report.Differences) != 1 || report.Differences[0].Path != "$.nodes[id=lint].planning_condition.patterns" {
		t.Fatalf("unexpected report: %+v", report)
	}
}
func TestResumeRejectsInvalidPlans(t *testing.T) {
	plan := mustW1(t)
	valid, _ := MarshalPlan(plan)
	invalid := bytes.Replace(valid, []byte(`"toolchain":"go1.25.12"`), []byte(`"toolchain":"go1.25.12","profile_id":false`), 1)
	if _, err := ResumeDiff(valid, invalid); err == nil {
		t.Fatal("resume diff accepted an invalid plan")
	}
}
func TestShapeProbe(t *testing.T) {
	for _, platform := range []string{"ios", "android"} {
		plan, err := Shape(platform)
		if err != nil {
			t.Fatal(err)
		}
		raw, _ := MarshalPlan(plan)
		if err := Validate(raw); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := Shape("windows"); err == nil {
		t.Fatal("unsupported platform accepted")
	}
}
func mustW1(t *testing.T) Plan {
	t.Helper()
	plan, err := W1()
	if err != nil {
		t.Fatal(err)
	}
	return plan
}
