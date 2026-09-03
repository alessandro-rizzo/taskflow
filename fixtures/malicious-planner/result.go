package maliciousplanner

import "strings"

// ResultEnvelopeVersion is this package's result-format experimental version,
// versioned separately from CatalogueVersion since results can evolve
// independently of the attack catalogue that produced them (roadmap section
// 3 rule 3a).
const ResultEnvelopeVersion = "t1-malicious-planner-result-v1-experimental"

// redactedPlaceholder replaces every occurrence of a run's secret marker.
const redactedPlaceholder = "[REDACTED-SYNTHETIC-SECRET]"

// Redact replaces every occurrence of secret in text with a fixed
// placeholder. It is applied to every attempt's diagnostic and error text
// before persistence, regardless of category - the output-abuse attempt is
// the only one that deliberately embeds the secret, so this is the one path
// that actually exercises redaction against a real occurrence rather than a
// hypothetical one (see attack_test.go's TestRunSuiteNeverPersistsSecret).
func Redact(text, secret string) string {
	if secret == "" || text == "" {
		return text
	}
	return strings.ReplaceAll(text, secret, redactedPlaceholder)
}

// AttemptRecord is one catalogue entry's result, ready for persistence.
// Observed and Error have already been redacted by RunSuite.
type AttemptRecord struct {
	ID                  string   `json:"id"`
	Category            Category `json:"category"`
	ExpectedOutcome     Outcome  `json:"expected_outcome"`
	ResourceLimit       string   `json:"resource_limit,omitempty"`
	DiagnosticAssertion string   `json:"diagnostic_assertion"`

	// Observed is the (redacted) diagnostic this attempt's self-test
	// produced.
	Observed string `json:"observed_diagnostic,omitempty"`

	// Error is the (redacted) error text if the self-test itself failed to
	// run cleanly (a bug in the fixture, not a security finding).
	Error string `json:"error,omitempty"`

	DurationSeconds float64 `json:"duration_seconds"`

	// TimedOut is true if this attempt did not return before its own
	// per-attempt deadline.
	TimedOut bool `json:"timed_out"`
}

// SuiteResult is the full, versioned result envelope for one run of the
// entire catalogue.
type SuiteResult struct {
	CatalogueVersion string `json:"catalogue_version"`
	ResultVersion    string `json:"result_version"`
	SourceRevision   string `json:"source_revision"`
	Timestamp        string `json:"timestamp"`

	Attempts []AttemptRecord `json:"attempts"`

	// AllBounded is true only if every attempt returned before its own
	// per-attempt deadline.
	AllBounded bool `json:"all_bounded"`

	// AnySecretLeak is a self-check: true only if, despite Redact being
	// applied, some persisted Observed/Error field still literally contains
	// the raw secret marker. It must always be false for a correct run; see
	// attack_test.go's TestRunSuiteNeverPersistsSecret for the assertion
	// that actually enforces this.
	AnySecretLeak bool `json:"any_secret_leak"`
}
