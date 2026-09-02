package benchmark

import (
	"errors"
	"fmt"
	"math"
	"sort"
	"time"
)

// eps is the tolerance used when comparing a Record's declared Median/P95
// against a fresh recomputation from its Samples. Values are computed with
// the same algorithm on both sides (ComputeStatistics), so a real mismatch
// differs by far more than floating-point rounding ever would.
const eps = 1e-9

// ComputeStatistics returns the median and p95 of samples using the method
// documented in docs/evidence/t0/w1-startup.md: samples sorted ascending;
// median is the statistics-library median (the middle value for odd n, the
// average of the two middle values for even n); p95 is the nearest-rank
// value at index round(0.95*(n-1)) of the sorted slice.
//
// ComputeStatistics returns an error for an empty input; it does not modify
// samples.
func ComputeStatistics(samples []float64) (median, p95 float64, err error) {
	if len(samples) == 0 {
		return 0, 0, errors.New("cannot compute statistics over zero samples")
	}
	sorted := append([]float64(nil), samples...)
	sort.Float64s(sorted)

	n := len(sorted)
	if n%2 == 1 {
		median = sorted[n/2]
	} else {
		median = (sorted[n/2-1] + sorted[n/2]) / 2
	}

	p95Index := int(math.Round(0.95 * float64(n-1)))
	p95 = sorted[p95Index]

	return median, p95, nil
}

// Validate checks a Record against every T1 benchmark-evidence requirement
// (roadmap section 8): required metadata, sample integrity, cache-state
// unambiguity, and derived-statistic consistency. It returns a single error
// joining every violation found (via errors.Join), so callers and tests can
// see every problem at once rather than one at a time.
func Validate(r Record) error {
	var errs []error

	if r.SchemaVersion != CurrentSchemaVersion {
		errs = append(errs, fmt.Errorf("schema_version: want %q, got %q", CurrentSchemaVersion, r.SchemaVersion))
	}
	if r.ExperimentID == "" {
		errs = append(errs, errors.New("experiment_id: required"))
	}
	if r.FixtureID == "" {
		errs = append(errs, errors.New("fixture_id: required"))
	}
	if r.SourceRevision == "" {
		errs = append(errs, errors.New("source_revision: required"))
	}
	if r.Timestamp == "" {
		errs = append(errs, errors.New("timestamp: required"))
	} else if _, parseErr := time.Parse(time.RFC3339, r.Timestamp); parseErr != nil {
		errs = append(errs, fmt.Errorf("timestamp: not RFC3339: %w", parseErr))
	}

	if r.Hardware.CPU == "" {
		errs = append(errs, errors.New("hardware.cpu: required"))
	}
	if r.Hardware.Cores <= 0 {
		errs = append(errs, errors.New("hardware.cores: must be positive"))
	}
	if r.Hardware.RAMGiB <= 0 {
		errs = append(errs, errors.New("hardware.ram_gib: must be positive"))
	}

	if r.OS.Name == "" {
		errs = append(errs, errors.New("os.name: required"))
	}
	if r.OS.Version == "" {
		errs = append(errs, errors.New("os.version: required"))
	}
	if r.OS.Arch == "" {
		errs = append(errs, errors.New("os.arch: required"))
	}

	if len(r.Toolchain) == 0 {
		errs = append(errs, errors.New("toolchain: at least one entry required"))
	}
	for i, tc := range r.Toolchain {
		if tc.Name == "" {
			errs = append(errs, fmt.Errorf("toolchain[%d].name: required", i))
		}
		if tc.Version == "" {
			errs = append(errs, fmt.Errorf("toolchain[%d].version: required", i))
		}
	}

	switch r.State {
	case StateCold, StateWarm, StateCacheHit:
	default:
		errs = append(errs, fmt.Errorf("state: must be one of %q, %q, %q, got %q", StateCold, StateWarm, StateCacheHit, r.State))
	}

	if len(r.Samples) == 0 {
		errs = append(errs, errors.New("samples: must not be empty"))
	} else {
		for i, s := range r.Samples {
			if math.IsNaN(s) || math.IsInf(s, 0) {
				errs = append(errs, fmt.Errorf("samples[%d]: not a finite number", i))
			} else if s < 0 {
				errs = append(errs, fmt.Errorf("samples[%d]: negative duration %v", i, s))
			}
		}
	}

	if r.SampleCount != len(r.Samples) {
		errs = append(errs, fmt.Errorf("sample_count: declared %d, but samples has %d entries", r.SampleCount, len(r.Samples)))
	}

	if len(r.Samples) > 0 {
		wantMedian, wantP95, statErr := ComputeStatistics(r.Samples)
		if statErr != nil {
			errs = append(errs, statErr)
		} else {
			if math.Abs(wantMedian-r.Median) > eps {
				errs = append(errs, fmt.Errorf("median: declared %v, recomputed %v from samples", r.Median, wantMedian))
			}
			if math.Abs(wantP95-r.P95) > eps {
				errs = append(errs, fmt.Errorf("p95: declared %v, recomputed %v from samples", r.P95, wantP95))
			}
		}
	}

	if r.State == StateCacheHit && r.ReservationCount == nil {
		errs = append(errs, errors.New("reservation_count: required when state is \"cache-hit\""))
	}
	if r.ReservationCount != nil && *r.ReservationCount < 0 {
		errs = append(errs, errors.New("reservation_count: must not be negative"))
	}

	if r.RawResultLocation == "" {
		errs = append(errs, errors.New("raw_result_location: required"))
	}

	return errors.Join(errs...)
}
