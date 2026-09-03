// Package maliciousplanner defines a self-test catalogue standing in for the
// attack fixture docs/roadmap.md's E03 experiment (project-planner trust
// boundary) must eventually run against a real candidate planner sandbox.
//
// CRITICAL FRAMING: no planner and no sandbox exists anywhere in this
// repository yet - E03 has not run. Every Attempt below therefore targets
// only synthetic resources this fixture creates and owns itself (its own
// throwaway temp directory, its own loopback listener it opens and closes,
// its own spawned-and-reaped child process, its own bounded allocations, its
// own fake secret marker). Running this catalogue proves the catalogue
// itself is well-formed, deterministic, non-hanging, and non-leaking; it is
// NOT a security boundary and asserts nothing about the safety of any real
// system. See README.md.
package maliciousplanner

import "context"

// CatalogueVersion is this package's experimental format version (roadmap
// section 3 rule 3a: frozen, reusable, explicitly versioned, pre-Gate-1).
const CatalogueVersion = "t1-malicious-planner-v1-experimental"

// Category is one of the six abuse areas AC #1 requires coverage for, each
// mapped 1:1 to an item in docs/roadmap.md's E03 "Attack fixture attempts"
// list.
type Category string

const (
	CategoryFilesystem  Category = "filesystem"
	CategoryEnvironment Category = "environment"
	CategoryNetwork     Category = "network"
	CategoryProcess     Category = "process"
	CategoryResource    Category = "resource"
	CategoryOutput      Category = "output"
)

// Outcome is the vocabulary docs/roadmap.md's E03 "Continue criteria" uses:
// "every malicious fixture is blocked, bounded, or explicitly classified as
// a trusted-local limitation" - not a bare allow/deny. It records what a
// REAL planner-sandbox implementation is expected to achieve; this fixture's
// own self-test does not (and cannot, since nothing real exists yet) verify
// that expectation itself.
type Outcome string

const (
	OutcomeBlocked                Outcome = "blocked"
	OutcomeBounded                Outcome = "bounded"
	OutcomeTrustedLocalLimitation Outcome = "trusted_local_limitation"
)

// SelfTestEnv is the synthetic, throwaway environment every Attempt.Run
// operates against. Nothing in this struct ever points at a real file
// outside Dir, a real network host, or a real credential.
type SelfTestEnv struct {
	// Dir is a temp directory this run created and will remove when done.
	// Every filesystem attempt confines itself to paths under Dir.
	Dir string

	// SecretMarker is a fixed-format, obviously-fake credential generated
	// fresh per run (see runner.go). Only the output-abuse attempt
	// deliberately embeds it in a diagnostic, to exercise the redaction path
	// (see result.go's Redact) against a real occurrence rather than a
	// hypothetical one.
	SecretMarker string
}

// AttemptResult is what a single Attempt.Run reports about its own,
// synthetic execution.
type AttemptResult struct {
	// Diagnostic is human-readable text describing what the self-test did
	// and observed. It is redacted for the SecretMarker before persistence
	// (see runner.go), regardless of category.
	Diagnostic string
}

// Attempt is one catalogue entry: a stable identity, what a REAL planner
// sandbox implementation must eventually guarantee against it
// (ExpectedOutcome, ResourceLimit, DiagnosticAssertion), and a safe
// synthetic self-test standing in for it today (Run).
type Attempt struct {
	// ID is a stable identifier for this attempt, referenced by future
	// evidence and by any experiment or regression that depends on it not
	// changing across catalogue versions.
	ID string

	Category Category

	// Description explains the attack this attempt represents, from the
	// perspective of a real malicious or buggy project-planner process.
	Description string

	// ExpectedOutcome is what a real planner sandbox implementation (E03)
	// must eventually achieve for this attempt, per roadmap section 9's
	// continue criteria.
	ExpectedOutcome Outcome

	// ResourceLimit is a human-readable statement of the bound this
	// self-test enforces on itself (not a claim about a real sandbox's
	// limits, which E03 will define).
	ResourceLimit string

	// DiagnosticAssertion states what a future real planner-sandbox test
	// run must check to consider this attempt handled correctly.
	DiagnosticAssertion string

	// Run executes this attempt's safe, synthetic self-test. It must
	// respect ctx's deadline and touch only resources reachable through
	// env.
	Run func(ctx context.Context, env *SelfTestEnv) (AttemptResult, error)
}

// Catalogue returns every attack attempt, covering all six categories AC #1
// requires. Order is stable across calls (used by tests and the runner for
// deterministic output).
func Catalogue() []Attempt {
	return []Attempt{
		{
			ID:                  "fs-read-outside-source",
			Category:            CategoryFilesystem,
			Description:         "Project code attempts to read a file outside the immutable selected source view it was declared, via a relative-path escape.",
			ExpectedOutcome:     OutcomeBlocked,
			ResourceLimit:       "confined to a throwaway temp directory this run creates and removes; bounded by a 2s per-attempt timeout",
			DiagnosticAssertion: "A real planner sandbox must reject any read of a path outside the declared source view, regardless of how the path is constructed.",
			Run:                 attemptFSReadOutsideSource,
		},
		{
			ID:                  "env-read-ambient",
			Category:            CategoryEnvironment,
			Description:         "Project code attempts to read the daemon's ambient process environment (which may hold credentials or provider configuration) rather than only its own declared inputs.",
			ExpectedOutcome:     OutcomeBlocked,
			ResourceLimit:       "reads only a synthetic env var this run owns, restoring any pre-existing value of that exact name afterward (never left unset if something else had set it); bounded by a 2s per-attempt timeout",
			DiagnosticAssertion: "A real planner sandbox must not expose the daemon's ambient process environment or credentials to project code.",
			Run:                 attemptEnvReadAmbient,
		},
		{
			ID:                  "net-dial-loopback",
			Category:            CategoryNetwork,
			Description:         "Project code attempts to open an outbound network connection or local socket during planning, which could exfiltrate data or reach unauthorized services.",
			ExpectedOutcome:     OutcomeBlocked,
			ResourceLimit:       "dials only 127.0.0.1 on a port this run opens and keeps open for the entire dial (no close-then-dial race); never a real external host; bounded by a 2s per-attempt timeout",
			DiagnosticAssertion: "A real planner sandbox must deny outbound network connections and local socket access unless explicitly declared and authorized.",
			Run:                 attemptNetworkDialLoopback,
		},
		{
			ID:                  "process-spawn-and-persist",
			Category:            CategoryProcess,
			Description:         "Project code spawns a descendant process that could outlive the planning invocation, escaping cleanup.",
			ExpectedOutcome:     OutcomeBounded,
			ResourceLimit:       "spawns exactly one known-safe trivial child, resolved by an absolute stat-ed path (never PATH lookup) with an explicit minimal environment (never ambient), and reaps it immediately; bounded by a 2s per-attempt timeout",
			DiagnosticAssertion: "A real planner sandbox must ensure no spawned descendant process outlives the planning invocation.",
			Run:                 attemptProcessSpawnAndReap,
		},
		{
			ID:                  "resource-unbounded-growth",
			Category:            CategoryResource,
			Description:         "Project code attempts to exhaust CPU, memory, file descriptors, output, or wall time during planning.",
			ExpectedOutcome:     OutcomeBounded,
			ResourceLimit:       "allocates at most 1 MiB across at most 1000 iterations, then stops; never grows without bound; bounded by a 2s per-attempt timeout",
			DiagnosticAssertion: "A real planner sandbox must enforce CPU, memory, file-descriptor, output, and wall-time limits on project code.",
			Run:                 attemptResourceBoundedLoop,
		},
		{
			ID:                  "output-secret-leak",
			Category:            CategoryOutput,
			Description:         "Project code embeds secret material (or an unsafe path) in an emitted plan field, where a downstream consumer or log could observe it.",
			ExpectedOutcome:     OutcomeBlocked,
			ResourceLimit:       "embeds only this run's own synthetic secret marker, never a real credential; bounded by a 2s per-attempt timeout",
			DiagnosticAssertion: "A real planner sandbox or plan validator must ensure no secret material or unsafe path ever appears in the emitted plan.",
			Run:                 attemptOutputSecretLeak,
		},
	}
}
