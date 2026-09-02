// Package benchmark defines the T1 benchmark evidence record format and its
// validator. See docs/roadmap.md section 8 ("T1: measurement contracts and
// representative fixtures") for the requirements this format serves, and
// README.md in this directory for the harness's own scope and status.
package benchmark

// CurrentSchemaVersion is the only schema version this package accepts.
// Pre-Gate-1 formats carry no compatibility promise (roadmap section 2.6):
// a breaking change bumps this string rather than adding optional fields
// silently. v2 adds OS.Build and the required PreparationCommand field: an
// independent Codex peer review of the T1 wave-1 batch found v1's State
// (cold/warm/cache-hit) was an unenforced caller-supplied label with no
// per-sample preparation hook, and that OS.Version alone did not satisfy
// T1's "OS build" requirement. Both new fields are required, so this is a
// breaking change per the policy above, not a silent addition.
const CurrentSchemaVersion = "taskflow-t1-benchmark/v2"

// State distinguishes the cache path a sample set was collected under, per
// roadmap section 8's exit gate: "distinguish cold, warm, and cache-hit
// paths." It names the PRIMARY cache dimension a given benchmark run is
// measuring. A run may involve other caches whose state also needs pinning
// down (for example: TF-001.03 found that Go's own build cache, GOCACHE,
// materially changed timings independently of the driver's own binary
// cache) — those go in Record.CacheDimensions instead of overloading this
// enum.
type State string

const (
	StateCold     State = "cold"
	StateWarm     State = "warm"
	StateCacheHit State = "cache-hit"
)

// Hardware describes the machine a benchmark ran on.
type Hardware struct {
	CPU    string  `json:"cpu"`
	Cores  int     `json:"cores"`
	RAMGiB float64 `json:"ram_gib"`
}

// OS describes the operating system a benchmark ran on. Version and Build
// are deliberately separate fields: on macOS, sw_vers -productVersion
// (Version, e.g. "26.5.2") and sw_vers -buildVersion (Build, e.g.
// "25F79") can differ between two machines running what a human would call
// "the same" macOS release, and T1's evidence-to-capture list asks for OS
// build specifically, not just product version.
type OS struct {
	Name    string `json:"name"`
	Version string `json:"version"`
	Build   string `json:"build"`
	Arch    string `json:"arch"`
}

// Toolchain describes one toolchain a benchmark's fixture depends on (a W3
// fixture may need both Go and Xcode versions recorded, for example).
type Toolchain struct {
	Name    string `json:"name"`
	Version string `json:"version"`
}

// Record is one validated benchmark result. Every field here is required
// unless its comment says otherwise; Validate rejects a Record missing any
// required field, with samples/malformed data, or an internally
// inconsistent state.
type Record struct {
	SchemaVersion string `json:"schema_version"`

	// ExperimentID is the roadmap identifier this result belongs to: "T0",
	// "T1", or one of "E01".."E08".
	ExperimentID string `json:"experiment_id"`

	// FixtureID identifies the frozen fixture the sampled command exercises.
	// It should match the fixture's own declared fixture_id, for example
	// "w1-fast-project-check" (fixtures/w1/manifest.yaml) or
	// "w2-cross-target-artifact-pipeline" (fixtures/w2/graph.json) - see
	// TF-002.01/.02/.03. This package does not itself verify FixtureID
	// against any fixture's real identity (that would require reading
	// arbitrary fixture files from an arbitrary path); callers are
	// responsible for using the fixture's actual declared id.
	FixtureID string `json:"fixture_id"`

	// SourceRevision is the git commit the benchmark ran against.
	SourceRevision string `json:"source_revision"`

	// Timestamp is RFC 3339, UTC, when the sample run started.
	Timestamp string `json:"timestamp"`

	Hardware  Hardware    `json:"hardware"`
	OS        OS          `json:"os"`
	Toolchain []Toolchain `json:"toolchain"`

	State State `json:"state"`

	// PreparationCommand is the shell command run, untimed, before EVERY
	// sample (not just once before the batch) to establish State for that
	// sample - for example a command that clears a driver-binary cache
	// directory before each cold sample, or "true" to explicitly declare
	// that no preparation is needed. This is required for every State, not
	// just cold/warm, because a caller must document what "cache-hit" prep
	// they performed too. Validate only checks this is non-empty; it cannot
	// verify the command actually produces the declared State (that would
	// require running the sampled system itself) - it exists so every
	// record makes its preparation procedure auditable rather than
	// implicit, per T1's "unambiguous preparation rules" requirement.
	PreparationCommand string `json:"preparation_command"`

	// CacheDimensions declares any secondary cache states the caller pinned
	// down before sampling, keyed by cache name (for example
	// {"gocache": "warm"}). Optional: a fixture with only one relevant cache
	// dimension can leave this empty and rely on State alone.
	CacheDimensions map[string]string `json:"cache_dimensions,omitempty"`

	// Samples holds every raw wall-clock sample in seconds, in the order
	// they were collected.
	Samples []float64 `json:"samples"`

	// SampleCount must equal len(Samples). It is kept as an explicit field
	// (rather than only relying on the slice length) so a validator can
	// catch a record whose samples were truncated or edited after the count
	// was recorded.
	SampleCount int `json:"sample_count"`

	// Median and P95 must equal the values Validate recomputes from Samples
	// using ComputeStatistics. They are stored in the record for
	// human/tooling convenience, not trusted as authoritative input.
	Median float64 `json:"median"`
	P95    float64 `json:"p95"`

	// ReservationCount is the number of provider/worker reservations the
	// sampled run performed. Required when State is StateCacheHit (the W1
	// budget in roadmap section 8 is specifically "zero worker
	// reservations" on a cache hit); optional for cold/warm states.
	ReservationCount *int `json:"reservation_count,omitempty"`

	// LeaseCount is the number of resource leases (e.g. simulator/device
	// sessions, W3-style namespace leases per fixtures/w3/spec.md) the
	// sampled run held. Optional and unconstrained beyond non-negative:
	// unlike ReservationCount it is not tied to a specific State, since
	// lease-oriented workloads (W3, E05, E06, E07) are relevant across all
	// three cache states, and no lease budget has been declared yet
	// (roadmap section 8's initial budgets are all cache/reservation
	// budgets, not lease-count ones).
	LeaseCount *int `json:"lease_count,omitempty"`

	// RawResultLocation is a path, relative to this record's own location,
	// to the raw sample/log data backing it (mirroring the
	// docs/evidence/t0/raw*/ convention TF-001.01/.03/.04 used ad hoc).
	RawResultLocation string `json:"raw_result_location"`
}
