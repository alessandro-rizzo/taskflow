package benchmark

import (
	"encoding/json"
	"math"
	"strings"
	"testing"
	"time"
)

func validReservationCount(n int) *int { return &n }

// validRecord returns a Record that Validate accepts, for tests to mutate.
func validRecord(t *testing.T) Record {
	t.Helper()
	samples := []float64{0.508, 0.512, 0.520, 0.531, 0.548, 0.552, 0.560, 0.571, 0.585}
	median, p95, err := ComputeStatistics(samples)
	if err != nil {
		t.Fatalf("ComputeStatistics: %v", err)
	}
	return Record{
		SchemaVersion:     CurrentSchemaVersion,
		ExperimentID:      "T1",
		FixtureID:         "w1-fast-check@v1",
		SourceRevision:    "9ddea886c7b4e368b5bcd8e48c36a9e2e916cb18",
		Timestamp:         time.Date(2026, 9, 2, 19, 0, 0, 0, time.UTC).Format(time.RFC3339),
		Hardware:          Hardware{CPU: "Apple M5 Max", Cores: 18, RAMGiB: 64},
		OS:                OS{Name: "darwin", Version: "26.5.2", Arch: "arm64"},
		Toolchain:         []Toolchain{{Name: "go", Version: "go1.25.12"}},
		State:             StateCold,
		Samples:           samples,
		SampleCount:       len(samples),
		Median:            median,
		P95:               p95,
		RawResultLocation: "samples.txt",
	}
}

func TestValidRecordPasses(t *testing.T) {
	if err := Validate(validRecord(t)); err != nil {
		t.Fatalf("expected a valid record to pass, got: %v", err)
	}
}

func TestValidRecordRoundTripsThroughJSON(t *testing.T) {
	r := validRecord(t)
	data, err := json.Marshal(r)
	if err != nil {
		t.Fatalf("Marshal: %v", err)
	}
	var got Record
	if err := json.Unmarshal(data, &got); err != nil {
		t.Fatalf("Unmarshal: %v", err)
	}
	if err := Validate(got); err != nil {
		t.Fatalf("round-tripped record should still validate, got: %v", err)
	}
	if got.SchemaVersion != r.SchemaVersion || got.FixtureID != r.FixtureID {
		t.Fatalf("round trip lost data: got %+v, want %+v", got, r)
	}
}

func TestCacheHitRequiresReservationCount(t *testing.T) {
	r := validRecord(t)
	r.State = StateCacheHit
	// ReservationCount left nil.
	err := Validate(r)
	if err == nil {
		t.Fatal("expected an error for cache-hit without reservation_count")
	}
	if !strings.Contains(err.Error(), "reservation_count") {
		t.Fatalf("expected error to mention reservation_count, got: %v", err)
	}

	r.ReservationCount = validReservationCount(0)
	if err := Validate(r); err != nil {
		t.Fatalf("cache-hit with reservation_count set should pass, got: %v", err)
	}
}

func TestNegativeReservationCountRejected(t *testing.T) {
	r := validRecord(t)
	r.State = StateCacheHit
	r.ReservationCount = validReservationCount(-1)
	if err := Validate(r); err == nil {
		t.Fatal("expected an error for a negative reservation_count")
	}
}

func TestMissingRequiredMetadataRejected(t *testing.T) {
	cases := []struct {
		name    string
		mutate  func(*Record)
		wantSub string
	}{
		{"schema_version", func(r *Record) { r.SchemaVersion = "wrong" }, "schema_version"},
		{"experiment_id", func(r *Record) { r.ExperimentID = "" }, "experiment_id"},
		{"fixture_id", func(r *Record) { r.FixtureID = "" }, "fixture_id"},
		{"source_revision", func(r *Record) { r.SourceRevision = "" }, "source_revision"},
		{"timestamp missing", func(r *Record) { r.Timestamp = "" }, "timestamp"},
		{"timestamp malformed", func(r *Record) { r.Timestamp = "not-a-date" }, "timestamp"},
		{"hardware.cpu", func(r *Record) { r.Hardware.CPU = "" }, "hardware.cpu"},
		{"hardware.cores", func(r *Record) { r.Hardware.Cores = 0 }, "hardware.cores"},
		{"hardware.ram_gib", func(r *Record) { r.Hardware.RAMGiB = 0 }, "hardware.ram_gib"},
		{"os.name", func(r *Record) { r.OS.Name = "" }, "os.name"},
		{"os.version", func(r *Record) { r.OS.Version = "" }, "os.version"},
		{"os.arch", func(r *Record) { r.OS.Arch = "" }, "os.arch"},
		{"toolchain empty", func(r *Record) { r.Toolchain = nil }, "toolchain"},
		{"toolchain entry missing version", func(r *Record) { r.Toolchain = []Toolchain{{Name: "go"}} }, "toolchain[0].version"},
		{"raw_result_location", func(r *Record) { r.RawResultLocation = "" }, "raw_result_location"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			r := validRecord(t)
			tc.mutate(&r)
			err := Validate(r)
			if err == nil {
				t.Fatalf("expected an error for mutation %q", tc.name)
			}
			if !strings.Contains(err.Error(), tc.wantSub) {
				t.Fatalf("expected error to mention %q, got: %v", tc.wantSub, err)
			}
		})
	}
}

func TestInvalidStateRejected(t *testing.T) {
	r := validRecord(t)
	r.State = "lukewarm"
	err := Validate(r)
	if err == nil {
		t.Fatal("expected an error for an unrecognized state")
	}
	if !strings.Contains(err.Error(), "state") {
		t.Fatalf("expected error to mention state, got: %v", err)
	}
}

func TestEmptySamplesRejected(t *testing.T) {
	r := validRecord(t)
	r.Samples = nil
	r.SampleCount = 0
	// Median/P95 are meaningless with no samples; leave them at whatever
	// validRecord computed, Validate must still reject on the empty slice
	// before it would try to recompute statistics.
	err := Validate(r)
	if err == nil {
		t.Fatal("expected an error for empty samples")
	}
	if !strings.Contains(err.Error(), "samples") {
		t.Fatalf("expected error to mention samples, got: %v", err)
	}
}

func TestNonFiniteSampleRejected(t *testing.T) {
	r := validRecord(t)
	r.Samples = append(append([]float64{}, r.Samples...), math.NaN())
	r.SampleCount = len(r.Samples)
	err := Validate(r)
	if err == nil {
		t.Fatal("expected an error for a NaN sample")
	}
	if !strings.Contains(err.Error(), "samples[") {
		t.Fatalf("expected error to mention the offending sample index, got: %v", err)
	}
}

func TestNegativeSampleRejected(t *testing.T) {
	r := validRecord(t)
	r.Samples = append(append([]float64{}, r.Samples...), -0.5)
	r.SampleCount = len(r.Samples)
	err := Validate(r)
	if err == nil {
		t.Fatal("expected an error for a negative sample")
	}
}

func TestSampleCountMismatchRejected(t *testing.T) {
	r := validRecord(t)
	r.SampleCount = len(r.Samples) + 1
	err := Validate(r)
	if err == nil {
		t.Fatal("expected an error for a sample_count/samples length mismatch")
	}
	if !strings.Contains(err.Error(), "sample_count") {
		t.Fatalf("expected error to mention sample_count, got: %v", err)
	}
}

func TestMislabeledMedianRejected(t *testing.T) {
	r := validRecord(t)
	r.Median += 1.0
	err := Validate(r)
	if err == nil {
		t.Fatal("expected an error for a median that does not match the samples")
	}
	if !strings.Contains(err.Error(), "median") {
		t.Fatalf("expected error to mention median, got: %v", err)
	}
}

func TestMislabeledP95Rejected(t *testing.T) {
	r := validRecord(t)
	r.P95 += 1.0
	err := Validate(r)
	if err == nil {
		t.Fatal("expected an error for a p95 that does not match the samples")
	}
	if !strings.Contains(err.Error(), "p95") {
		t.Fatalf("expected error to mention p95, got: %v", err)
	}
}

func TestComputeStatisticsMatchesDocumentedMethod(t *testing.T) {
	// The actual raw cold-run samples from docs/evidence/t0/raw-w1-startup/
	// cold-samples.txt (TF-001.03), used as a known-answer check of the
	// documented median/p95 method against its own recorded result
	// (median 0.548s, p95 0.576s in docs/evidence/t0/w1-startup.md).
	samples := []float64{0.576, 0.550, 0.537, 0.528, 0.540, 0.585, 0.539, 0.508, 0.569, 0.542, 0.552, 0.560, 0.555, 0.548, 0.516}
	median, p95, err := ComputeStatistics(samples)
	if err != nil {
		t.Fatalf("ComputeStatistics: %v", err)
	}
	if median != 0.548 {
		t.Fatalf("median = %v, want 0.548 (middle of 15 sorted samples)", median)
	}
	// index round(0.95*(15-1)) = round(13.3) = 13, 0-indexed 14th value.
	if p95 != 0.576 {
		t.Fatalf("p95 = %v, want 0.576 (nearest-rank index 13)", p95)
	}
}

func TestComputeStatisticsRejectsEmptyInput(t *testing.T) {
	if _, _, err := ComputeStatistics(nil); err == nil {
		t.Fatal("expected an error for zero samples")
	}
}
