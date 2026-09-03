// Command t1conform validates a candidate plan document, canonicalizes it
// and a golden, compares their structural digests, and on any mismatch
// writes reproducible diff evidence to --diff-out (see the conformance
// package in this module, and README.md).
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"

	conformance "github.com/alessandro-rizzo/taskflow/fixtures/t1-plan-conformance"
)

func main() {
	os.Exit(run(os.Args[1:]))
}

func run(args []string) int {
	fs := flag.NewFlagSet("t1conform", flag.ContinueOnError)
	candidatePath := fs.String("candidate", "", "candidate plan JSON file (required)")
	goldenPath := fs.String("golden", "", "golden plan JSON file (required)")
	diffOut := fs.String("diff-out", "", "directory to write diff.json plus copies of both inputs on failure")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if *candidatePath == "" || *goldenPath == "" {
		fmt.Fprintln(os.Stderr, "t1conform: both --candidate and --golden are required")
		return 2
	}

	candidateRaw, err := os.ReadFile(*candidatePath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "t1conform: reading --candidate: %v\n", err)
		return 2
	}
	goldenRaw, err := os.ReadFile(*goldenPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "t1conform: reading --golden: %v\n", err)
		return 2
	}

	violations, err := conformance.Validate(candidateRaw)
	if err != nil {
		fmt.Fprintf(os.Stderr, "t1conform: validating candidate: %v\n", err)
		return 2
	}

	candidateCanonical, err := conformance.Canonicalize(candidateRaw)
	if err != nil {
		fmt.Fprintf(os.Stderr, "t1conform: canonicalizing candidate: %v\n", err)
		return 2
	}
	goldenCanonical, err := conformance.Canonicalize(goldenRaw)
	if err != nil {
		fmt.Fprintf(os.Stderr, "t1conform: canonicalizing golden: %v\n", err)
		return 2
	}

	candidateDigest := conformance.Digest(candidateCanonical)
	goldenDigest := conformance.Digest(goldenCanonical)

	var diffs []conformance.Diff
	if candidateDigest != goldenDigest {
		diffs, err = conformance.Compare(candidateCanonical, goldenCanonical)
		if err != nil {
			fmt.Fprintf(os.Stderr, "t1conform: comparing: %v\n", err)
			return 2
		}
	}

	if len(violations) == 0 && len(diffs) == 0 {
		fmt.Fprintf(os.Stderr, "t1conform: PASS (digest %s)\n", candidateDigest)
		return 0
	}

	fmt.Fprintf(os.Stderr, "t1conform: FAIL - %d validation violation(s), %d diff(s)\n", len(violations), len(diffs))
	for _, v := range violations {
		fmt.Fprintf(os.Stderr, "  violation %s: %s\n", v.Path, v.Message)
	}
	for _, d := range diffs {
		fmt.Fprintf(os.Stderr, "  diff %s: golden=%v candidate=%v\n", d.Path, d.Golden, d.Candidate)
	}

	if *diffOut != "" {
		if err := writeDiffEvidence(*diffOut, *candidatePath, *goldenPath, candidateRaw, goldenRaw, violations, diffs, candidateDigest, goldenDigest); err != nil {
			fmt.Fprintf(os.Stderr, "t1conform: writing --diff-out evidence: %v\n", err)
			return 2
		}
		fmt.Fprintf(os.Stderr, "t1conform: evidence written to %s\n", *diffOut)
	}

	return 1
}

// evidence is what --diff-out writes as diff.json. It carries enough to be
// reproducible offline without rerunning anything live: which fixture and
// declared versions were involved on each side, the exact input paths, and
// the command to reproduce the comparison (AC #4: "preserve reproducible
// diff evidence" - an independent Codex peer review found the original
// version had only digests/violations/diffs, missing fixture identity,
// input paths, and a reproduction command).
type evidence struct {
	CandidatePath           string                  `json:"candidate_path"`
	GoldenPath              string                  `json:"golden_path"`
	CandidateFixtureID      string                  `json:"candidate_fixture_id"`
	CandidateFixtureVersion string                  `json:"candidate_fixture_version"`
	GoldenFixtureID         string                  `json:"golden_fixture_id"`
	GoldenFixtureVersion    string                  `json:"golden_fixture_version"`
	CandidateDigest         string                  `json:"candidate_digest"`
	GoldenDigest            string                  `json:"golden_digest"`
	ReproductionCommand     string                  `json:"reproduction_command"`
	Violations              []conformance.Violation `json:"violations,omitempty"`
	Diffs                   []conformance.Diff      `json:"diffs,omitempty"`
}

func writeDiffEvidence(dir, candidatePath, goldenPath string, candidateRaw, goldenRaw []byte, violations []conformance.Violation, diffs []conformance.Diff, candidateDigest, goldenDigest string) error {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(dir, "candidate.json"), candidateRaw, 0o644); err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(dir, "golden.json"), goldenRaw, 0o644); err != nil {
		return err
	}

	candidateEnv := conformance.ReadEnvelope(candidateRaw)
	goldenEnv := conformance.ReadEnvelope(goldenRaw)

	ev := evidence{
		CandidatePath:           candidatePath,
		GoldenPath:              goldenPath,
		CandidateFixtureID:      candidateEnv.FixtureID,
		CandidateFixtureVersion: candidateEnv.FixtureVersion,
		GoldenFixtureID:         goldenEnv.FixtureID,
		GoldenFixtureVersion:    goldenEnv.FixtureVersion,
		CandidateDigest:         candidateDigest,
		GoldenDigest:            goldenDigest,
		ReproductionCommand:     fmt.Sprintf("t1conform --candidate %s --golden %s", candidatePath, goldenPath),
		Violations:              violations,
		Diffs:                   diffs,
	}
	evJSON, err := json.MarshalIndent(ev, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, "diff.json"), append(evJSON, '\n'), 0o644)
}
