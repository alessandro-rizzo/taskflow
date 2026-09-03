package maliciousplanner

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"os"
	"strings"
	"time"
)

// perAttemptTimeout bounds every individual Attempt.Run. suiteTimeout bounds
// the entire RunSuite call regardless of how many attempts the catalogue
// grows to contain. Both exist so a bug in any single self-test (or in the
// catalogue as a whole) cannot hang the caller or run unbounded.
const (
	perAttemptTimeout = 2 * time.Second
	suiteTimeout      = 30 * time.Second
)

// RunSuite executes every Catalogue() entry as a bounded, synthetic
// self-test. It creates one throwaway temp directory and one fresh
// synthetic secret marker, passes them to every attempt via SelfTestEnv, and
// removes the temp directory before returning. It never touches any real
// file outside that directory, any real network host, or any real
// credential - see attack.go's package doc for the full framing.
func RunSuite(ctx context.Context, sourceRevision string) (SuiteResult, error) {
	suiteCtx, cancel := context.WithTimeout(ctx, suiteTimeout)
	defer cancel()

	dir, err := os.MkdirTemp("", "malicious-planner-selftest-*")
	if err != nil {
		return SuiteResult{}, fmt.Errorf("creating self-test temp directory: %w", err)
	}
	defer os.RemoveAll(dir)

	secret, err := randomSecretMarker()
	if err != nil {
		return SuiteResult{}, fmt.Errorf("generating synthetic secret marker: %w", err)
	}
	env := &SelfTestEnv{Dir: dir, SecretMarker: secret}

	result := SuiteResult{
		CatalogueVersion: CatalogueVersion,
		ResultVersion:    ResultEnvelopeVersion,
		SourceRevision:   sourceRevision,
		Timestamp:        time.Now().UTC().Format(time.RFC3339),
		AllBounded:       true,
	}

	for _, a := range Catalogue() {
		rec := runOneAttemptBounded(suiteCtx, a, env, secret)
		if rec.TimedOut {
			result.AllBounded = false
		}
		if strings.Contains(rec.Observed, secret) || strings.Contains(rec.Error, secret) {
			result.AnySecretLeak = true
		}
		result.Attempts = append(result.Attempts, rec)
	}

	return result, nil
}

// attemptOutcome carries a.Run's result across the goroutine boundary in
// runOneAttemptBounded.
type attemptOutcome struct {
	res AttemptResult
	err error
}

// runOneAttemptBounded runs a single attempt and enforces perAttemptTimeout
// for real, not merely by checking elapsed time after a synchronous call
// returns. a.Run executes in its own goroutine; runOneAttemptBounded selects
// between that goroutine finishing and attemptCtx's deadline, so an attempt
// that ignores ctx entirely is reported as timed out instead of blocking the
// caller. If the goroutine is still running when the deadline fires, this
// function does not wait for it - a truly hung Run can still leak that one
// goroutine, but RunSuite itself always returns on schedule and never trusts
// a result it did not actually observe within the bound.
//
// a.Run is also run under recover(): a panic inside any attempt is caught,
// redacted like any other error text, and recorded as this attempt's
// failure rather than crashing the whole suite or reaching stderr unredacted
// (output abuse is one of the six categories this fixture exists to test).
func runOneAttemptBounded(suiteCtx context.Context, a Attempt, env *SelfTestEnv, secret string) AttemptRecord {
	attemptCtx, attemptCancel := context.WithTimeout(suiteCtx, perAttemptTimeout)
	defer attemptCancel()

	rec := AttemptRecord{
		ID:                  a.ID,
		Category:            a.Category,
		ExpectedOutcome:     a.ExpectedOutcome,
		ResourceLimit:       a.ResourceLimit,
		DiagnosticAssertion: a.DiagnosticAssertion,
	}

	done := make(chan attemptOutcome, 1)
	start := time.Now()
	go func() {
		res, err := runAttemptRecoveringPanics(attemptCtx, a, env)
		done <- attemptOutcome{res: res, err: err}
	}()

	select {
	case o := <-done:
		rec.DurationSeconds = time.Since(start).Seconds()
		rec.Observed = Redact(o.res.Diagnostic, secret)
		if o.err != nil {
			rec.Error = Redact(o.err.Error(), secret)
		}
	case <-attemptCtx.Done():
		rec.DurationSeconds = time.Since(start).Seconds()
		rec.TimedOut = true
		rec.Error = fmt.Sprintf("attempt did not return before its %v bound", perAttemptTimeout)
		// Deliberately not waiting on done: a goroutine that ignores ctx may
		// still be running, but RunSuite must not block on it either.
	}
	return rec
}

// runAttemptRecoveringPanics calls a.Run and converts any panic into an
// error instead of letting it propagate (which would crash the whole suite,
// or - for the output-abuse attempt specifically - reach stderr without
// going through Redact first).
func runAttemptRecoveringPanics(ctx context.Context, a Attempt, env *SelfTestEnv) (res AttemptResult, err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("attempt panicked: %v", r)
		}
	}()
	return a.Run(ctx, env)
}

// randomSecretMarker returns a fresh, fixed-format, obviously-synthetic
// credential-shaped string - never resembling any real API key, token, or
// password format - generated with crypto/rand so it differs on every run.
func randomSecretMarker() (string, error) {
	b := make([]byte, 8)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return "SYNTHETIC-TEST-SECRET-" + hex.EncodeToString(b) + "-DO-NOT-USE", nil
}
