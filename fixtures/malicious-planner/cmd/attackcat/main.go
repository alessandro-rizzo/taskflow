// Command attackcat runs the full malicious-planner self-test catalogue
// (see the maliciousplanner package in this module) with one command,
// satisfying AC #4 ("one command runs the complete abuse suite in a bounded
// environment"). It exits nonzero if any self-test errors, times out, or
// leaks the run's synthetic secret marker into persisted evidence.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"strings"

	maliciousplanner "github.com/alessandro-rizzo/taskflow/fixtures/malicious-planner"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "attackcat:", err)
		os.Exit(2)
	}
}

func run(args []string) error {
	fs := flag.NewFlagSet("attackcat", flag.ContinueOnError)
	out := fs.String("out", "", "output path for the result envelope JSON (required)")
	sourceRevision := fs.String("source-revision", "", "git commit; defaults to `git rev-parse HEAD` in the current directory")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *out == "" {
		return fmt.Errorf("missing required flag: --out")
	}

	if *sourceRevision == "" {
		rev, err := commandOutput("git", "rev-parse", "HEAD")
		if err != nil {
			return fmt.Errorf("--source-revision not given and `git rev-parse HEAD` failed: %w", err)
		}
		*sourceRevision = rev
	}

	fmt.Fprintln(os.Stderr, "attackcat: running the malicious-planner self-test catalogue (synthetic, bounded, no real target)")

	result, err := maliciousplanner.RunSuite(context.Background(), *sourceRevision)
	if err != nil {
		return fmt.Errorf("running suite: %w", err)
	}

	data, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		return fmt.Errorf("marshaling result: %w", err)
	}
	if err := os.WriteFile(*out, append(data, '\n'), 0o644); err != nil {
		return fmt.Errorf("writing %s: %w", *out, err)
	}

	var failed []string
	for _, a := range result.Attempts {
		if a.Error != "" {
			failed = append(failed, fmt.Sprintf("%s: %s", a.ID, a.Error))
		}
		if a.TimedOut {
			failed = append(failed, fmt.Sprintf("%s: exceeded its per-attempt bound", a.ID))
		}
	}

	fmt.Fprintf(os.Stderr, "attackcat: wrote %s (%d attempt(s), all_bounded=%v, any_secret_leak=%v)\n",
		*out, len(result.Attempts), result.AllBounded, result.AnySecretLeak)

	if result.AnySecretLeak {
		return fmt.Errorf("the synthetic secret marker leaked into persisted evidence despite redaction - this is a bug in the fixture itself")
	}
	if len(failed) > 0 {
		return fmt.Errorf("%d attempt(s) did not complete cleanly:\n%s", len(failed), strings.Join(failed, "\n"))
	}
	return nil
}

func commandOutput(name string, args ...string) (string, error) {
	out, err := exec.Command(name, args...).Output()
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(out)), nil
}
