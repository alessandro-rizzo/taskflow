package conformance

import (
	"encoding/json"
	"fmt"
	"sort"
)

// Diff is one structural difference between a candidate and a golden, found
// by Compare. Golden/Candidate hold the differing value at Path (nil if
// absent on that side), so a caller can render or persist a reproducible
// diff (AC #4: "preserve reproducible diff evidence").
type Diff struct {
	Path      string `json:"path"`
	Golden    any    `json:"golden"`
	Candidate any    `json:"candidate"`
}

// Compare decodes two already-canonicalized JSON documents (from
// Canonicalize, via decodeAny so exact number literals are preserved) and
// returns every structural difference between them, each with a semantic
// path. An empty result means the two documents are structurally
// identical.
func Compare(candidateCanonical, goldenCanonical []byte) ([]Diff, error) {
	candidate, err := decodeAny(candidateCanonical)
	if err != nil {
		return nil, fmt.Errorf("decoding candidate: %w", err)
	}
	golden, err := decodeAny(goldenCanonical)
	if err != nil {
		return nil, fmt.Errorf("decoding golden: %w", err)
	}
	var diffs []Diff
	diffValues("", golden, candidate, &diffs)
	return diffs, nil
}

func diffValues(path string, golden, candidate any, diffs *[]Diff) {
	gm, gIsMap := golden.(map[string]any)
	cm, cIsMap := candidate.(map[string]any)
	if gIsMap && cIsMap {
		keys := map[string]bool{}
		for k := range gm {
			keys[k] = true
		}
		for k := range cm {
			keys[k] = true
		}
		sortedKeys := make([]string, 0, len(keys))
		for k := range keys {
			sortedKeys = append(sortedKeys, k)
		}
		sort.Strings(sortedKeys)
		for _, k := range sortedKeys {
			diffValues(path+"/"+k, gm[k], cm[k], diffs)
		}
		return
	}

	ga, gIsArr := golden.([]any)
	ca, cIsArr := candidate.([]any)
	if gIsArr && cIsArr {
		maxLen := len(ga)
		if len(ca) > maxLen {
			maxLen = len(ca)
		}
		for i := 0; i < maxLen; i++ {
			var gv, cv any
			if i < len(ga) {
				gv = ga[i]
			}
			if i < len(ca) {
				cv = ca[i]
			}
			diffValues(fmt.Sprintf("%s/%d", path, i), gv, cv, diffs)
		}
		return
	}

	if !valuesEqual(golden, candidate) {
		*diffs = append(*diffs, Diff{Path: pathOrRoot(path), Golden: golden, Candidate: candidate})
	}
}

func pathOrRoot(path string) string {
	if path == "" {
		return "/"
	}
	return path
}

func valuesEqual(a, b any) bool {
	aj, _ := json.Marshal(a)
	bj, _ := json.Marshal(b)
	return string(aj) == string(bj)
}
