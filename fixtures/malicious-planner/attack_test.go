package maliciousplanner

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestCatalogueCoversAllSixCategories(t *testing.T) {
	want := map[Category]bool{
		CategoryFilesystem:  false,
		CategoryEnvironment: false,
		CategoryNetwork:     false,
		CategoryProcess:     false,
		CategoryResource:    false,
		CategoryOutput:      false,
	}
	for _, a := range Catalogue() {
		if _, ok := want[a.Category]; !ok {
			t.Fatalf("attempt %q has unrecognized category %q", a.ID, a.Category)
		}
		want[a.Category] = true
	}
	for category, seen := range want {
		if !seen {
			t.Errorf("no catalogue entry covers required category %q (AC #1)", category)
		}
	}
}

func TestCatalogueEntriesAreWellFormed(t *testing.T) {
	seenIDs := map[string]bool{}
	for _, a := range Catalogue() {
		if a.ID == "" {
			t.Fatalf("attempt with category %q has an empty ID", a.Category)
		}
		if seenIDs[a.ID] {
			t.Fatalf("duplicate attempt ID %q", a.ID)
		}
		seenIDs[a.ID] = true

		switch a.ExpectedOutcome {
		case OutcomeBlocked, OutcomeBounded, OutcomeTrustedLocalLimitation:
		default:
			t.Errorf("attempt %q has an unrecognized expected_outcome %q", a.ID, a.ExpectedOutcome)
		}
		if a.DiagnosticAssertion == "" {
			t.Errorf("attempt %q has an empty diagnostic_assertion (AC #2)", a.ID)
		}
		if a.Description == "" {
			t.Errorf("attempt %q has an empty description", a.ID)
		}
		if a.Run == nil {
			t.Errorf("attempt %q has a nil Run func", a.ID)
		}
	}
}

func TestEveryAttemptCompletesWithinItsBound(t *testing.T) {
	env := &SelfTestEnv{Dir: t.TempDir(), SecretMarker: "SYNTHETIC-TEST-SECRET-testonly-DO-NOT-USE"}
	for _, a := range Catalogue() {
		a := a
		t.Run(a.ID, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), perAttemptTimeout)
			defer cancel()

			start := time.Now()
			res, err := a.Run(ctx, env)
			elapsed := time.Since(start)

			if elapsed > perAttemptTimeout {
				t.Fatalf("attempt %q took %v, exceeding its own %v bound", a.ID, elapsed, perAttemptTimeout)
			}
			if err != nil {
				t.Fatalf("attempt %q self-test failed: %v", a.ID, err)
			}
			if res.Diagnostic == "" {
				t.Fatalf("attempt %q returned no diagnostic", a.ID)
			}
		})
	}
}

func TestOutputAttemptActuallyEmbedsSecretBeforeRedaction(t *testing.T) {
	// Guards against the redaction test below passing vacuously because the
	// attempt stopped embedding the secret in the first place.
	env := &SelfTestEnv{Dir: t.TempDir(), SecretMarker: "SYNTHETIC-TEST-SECRET-testonly-DO-NOT-USE"}
	res, err := attemptOutputSecretLeak(context.Background(), env)
	if err != nil {
		t.Fatalf("attemptOutputSecretLeak: %v", err)
	}
	if !strings.Contains(res.Diagnostic, env.SecretMarker) {
		t.Fatalf("expected the raw (pre-redaction) diagnostic to contain the secret marker, got: %q", res.Diagnostic)
	}
}

func TestRedactStripsSecretEverywhere(t *testing.T) {
	secret := "SYNTHETIC-TEST-SECRET-abc123-DO-NOT-USE"
	text := "leading " + secret + " middle " + secret + " trailing"
	got := Redact(text, secret)
	if strings.Contains(got, secret) {
		t.Fatalf("Redact left the secret in place: %q", got)
	}
	if strings.Count(got, redactedPlaceholder) != 2 {
		t.Fatalf("expected 2 redaction placeholders, got: %q", got)
	}
}

func TestRunSuiteNeverPersistsSecret(t *testing.T) {
	// This is the assertion that actually enforces AC #3 end-to-end: run the
	// real suite (which includes the deliberate output-secret-leak attempt)
	// and confirm the secret marker it generated for this run does not
	// appear anywhere in the persisted result, and that AnySecretLeak - the
	// suite's own self-check - agrees.
	result, err := RunSuite(context.Background(), "test-revision")
	if err != nil {
		t.Fatalf("RunSuite: %v", err)
	}
	if result.AnySecretLeak {
		t.Fatal("RunSuite reported any_secret_leak=true - redaction failed")
	}
	if !result.AllBounded {
		t.Fatal("RunSuite reported all_bounded=false - some attempt exceeded its per-attempt timeout")
	}

	foundOutputAttempt := false
	for _, a := range result.Attempts {
		if a.ID == "output-secret-leak" {
			foundOutputAttempt = true
			if !strings.Contains(a.Observed, redactedPlaceholder) {
				t.Fatalf("expected the output-secret-leak attempt's persisted diagnostic to contain the redaction placeholder, got: %q", a.Observed)
			}
		}
		for _, field := range []string{a.Observed, a.Error} {
			if strings.Contains(field, "SYNTHETIC-TEST-SECRET-") && !strings.Contains(field, redactedPlaceholder) {
				t.Fatalf("attempt %q has an unredacted secret-shaped string: %q", a.ID, field)
			}
		}
	}
	if !foundOutputAttempt {
		t.Fatal("expected to find the output-secret-leak attempt in the suite result")
	}

	// Scan the FULL serialized envelope, not just the two fields checked
	// above - catches a leak through any field (including ones this test
	// doesn't know to check individually, e.g. a future field added to
	// AttemptRecord or SuiteResult). "SYNTHETIC-TEST-SECRET-" never appears
	// inside redactedPlaceholder ("[REDACTED-SYNTHETIC-SECRET]" has no
	// "TEST-" segment), so this cannot false-positive on a correctly
	// redacted record.
	data, err := json.Marshal(result)
	if err != nil {
		t.Fatalf("marshaling result: %v", err)
	}
	if strings.Contains(string(data), "SYNTHETIC-TEST-SECRET-") {
		t.Fatalf("serialized suite result contains an unredacted secret-shaped string:\n%s", data)
	}
}

// TestAttemptThatIgnoresContextIsReportedAsTimedOut proves runOneAttemptBounded
// actually enforces perAttemptTimeout: an attempt whose Run never checks ctx
// and never returns must still cause RunSuite-level accounting to report it
// as timed out, without the caller (this test) blocking past the bound.
func TestAttemptThatIgnoresContextIsReportedAsTimedOut(t *testing.T) {
	hungAttempt := Attempt{
		ID:                  "test-hangs-forever",
		Category:            CategoryProcess,
		ExpectedOutcome:     OutcomeBounded,
		DiagnosticAssertion: "test fixture only",
		Run: func(ctx context.Context, env *SelfTestEnv) (AttemptResult, error) {
			select {} // deliberately never returns and ignores ctx
		},
	}

	env := &SelfTestEnv{Dir: t.TempDir(), SecretMarker: "SYNTHETIC-TEST-SECRET-testonly-DO-NOT-USE"}
	start := time.Now()
	rec := runOneAttemptBounded(context.Background(), hungAttempt, env, env.SecretMarker)
	elapsed := time.Since(start)

	if elapsed > perAttemptTimeout+500*time.Millisecond {
		t.Fatalf("runOneAttemptBounded blocked for %v on a hung attempt, well past its %v bound - timeout is not actually enforced", elapsed, perAttemptTimeout)
	}
	if !rec.TimedOut {
		t.Fatalf("expected TimedOut=true for an attempt that never returns, got: %+v", rec)
	}
}

// TestPanickingAttemptIsRecoveredAndRedacted proves a panic inside an
// attempt (including one that panics with the run's own secret marker in
// its message) is caught, converted to a normal error, and redacted like
// any other error text - not left to crash the suite or reach stderr
// unredacted.
func TestPanickingAttemptIsRecoveredAndRedacted(t *testing.T) {
	secret := "SYNTHETIC-TEST-SECRET-panictest-DO-NOT-USE"
	panickingAttempt := Attempt{
		ID:                  "test-panics",
		Category:            CategoryOutput,
		ExpectedOutcome:     OutcomeBlocked,
		DiagnosticAssertion: "test fixture only",
		Run: func(ctx context.Context, env *SelfTestEnv) (AttemptResult, error) {
			panic("simulated failure containing " + env.SecretMarker)
		},
	}

	env := &SelfTestEnv{Dir: t.TempDir(), SecretMarker: secret}
	rec := runOneAttemptBounded(context.Background(), panickingAttempt, env, secret)

	if rec.TimedOut {
		t.Fatal("a recovered panic should not be reported as a timeout")
	}
	if rec.Error == "" {
		t.Fatal("expected a recovered panic to produce a non-empty Error")
	}
	if strings.Contains(rec.Error, secret) {
		t.Fatalf("recovered panic error was not redacted: %q", rec.Error)
	}
	if !strings.Contains(rec.Error, redactedPlaceholder) {
		t.Fatalf("expected the redaction placeholder in the recovered panic error, got: %q", rec.Error)
	}
}

func TestRunSuiteCompletesWellWithinSuiteTimeout(t *testing.T) {
	start := time.Now()
	if _, err := RunSuite(context.Background(), "test-revision"); err != nil {
		t.Fatalf("RunSuite: %v", err)
	}
	elapsed := time.Since(start)
	if elapsed > suiteTimeout {
		t.Fatalf("RunSuite took %v, exceeding the suite-level %v bound", elapsed, suiteTimeout)
	}
	// The whole synthetic suite should be fast (well under a second in
	// practice); a generous fraction of the bound catches a regression
	// toward "technically bounded but uncomfortably slow" without being
	// flaky on a loaded machine.
	if elapsed > suiteTimeout/2 {
		t.Errorf("RunSuite took %v, more than half its %v bound - investigate before this becomes flaky", elapsed, suiteTimeout)
	}
}

func TestRunSuiteCleansUpItsTempDirectory(t *testing.T) {
	glob := filepath.Join(os.TempDir(), "malicious-planner-selftest-*")

	before, err := filepath.Glob(glob)
	if err != nil {
		t.Fatalf("globbing before RunSuite: %v", err)
	}

	if _, err := RunSuite(context.Background(), "test-revision"); err != nil {
		t.Fatalf("RunSuite: %v", err)
	}

	after, err := filepath.Glob(glob)
	if err != nil {
		t.Fatalf("globbing after RunSuite: %v", err)
	}
	if len(after) != len(before) {
		t.Fatalf("RunSuite left its temp directory behind: %d matching dir(s) before, %d after (glob %s)", len(before), len(after), glob)
	}
}
