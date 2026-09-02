// Command t1bench times N repetitions of a shell command and emits a
// validated T1 benchmark record (see the benchmark package in this module,
// and docs/roadmap.md section 8). It generalizes the throwaway benchmark
// script TF-001.03 wrote ad hoc (docs/evidence/t0/raw-w1-startup/
// benchmark.sh) into a reusable, self-validating tool.
//
// t1bench does not know what "cold" or "warm" means for an arbitrary
// command: preparing the state to sample (clearing or warming whichever
// caches are relevant) is the caller's job, done before invoking t1bench.
// What t1bench guarantees is that the resulting record states precisely
// what was declared (--state, --cache-dim) rather than leaving it implicit,
// and that every required field is present and internally consistent before
// anything is written to disk.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	benchmark "github.com/alessandro-rizzo/taskflow/fixtures/t1-benchmark-harness"
)

type keyValueFlag map[string]string

func (m keyValueFlag) String() string {
	var parts []string
	for k, v := range m {
		parts = append(parts, k+"="+v)
	}
	return strings.Join(parts, ",")
}

func (m keyValueFlag) Set(s string) error {
	k, v, ok := strings.Cut(s, "=")
	if !ok {
		return fmt.Errorf("expected key=value, got %q", s)
	}
	m[k] = v
	return nil
}

type toolchainFlag []benchmark.Toolchain

func (t *toolchainFlag) String() string {
	var parts []string
	for _, tc := range *t {
		parts = append(parts, tc.Name+"@"+tc.Version)
	}
	return strings.Join(parts, ",")
}

func (t *toolchainFlag) Set(s string) error {
	name, version, ok := strings.Cut(s, "@")
	if !ok {
		return fmt.Errorf("expected name@version, got %q", s)
	}
	*t = append(*t, benchmark.Toolchain{Name: name, Version: version})
	return nil
}

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "t1bench:", err)
		os.Exit(2)
	}
}

func run(args []string) error {
	fs := flag.NewFlagSet("t1bench", flag.ContinueOnError)

	command := fs.String("cmd", "", "shell command to time (required)")
	n := fs.Int("n", 0, "number of samples to collect (required)")
	state := fs.String("state", "", "cold, warm, or cache-hit (required)")
	experimentID := fs.String("experiment", "", "roadmap experiment id, e.g. T1 or E04 (required)")
	fixtureID := fs.String("fixture", "", "frozen fixture id, e.g. w1-fast-check@v1 (required)")
	outDir := fs.String("out", "", "output directory for record.json and samples.txt (required)")
	sourceRevision := fs.String("source-revision", "", "git commit; defaults to `git rev-parse HEAD` in the current directory")
	reservationCount := fs.Int("reservation-count", -1, "provider/worker reservation count; required when --state=cache-hit")

	cpu := fs.String("cpu", "", "hardware.cpu override; auto-detected if omitted")
	cores := fs.Int("cores", 0, "hardware.cores override; defaults to runtime.NumCPU()")
	ramGiB := fs.Float64("ram-gib", 0, "hardware.ram_gib override; auto-detected if omitted")
	osName := fs.String("os-name", "", "os.name override; defaults to GOOS")
	osVersion := fs.String("os-version", "", "os.version override; auto-detected if omitted")
	osArch := fs.String("os-arch", "", "os.arch override; defaults to GOARCH")

	cacheDims := keyValueFlag{}
	fs.Var(cacheDims, "cache-dim", "secondary cache dimension as key=value; repeatable")
	var toolchains toolchainFlag
	fs.Var(&toolchains, "toolchain", "toolchain as name@version; repeatable, adds to the auto-detected Go toolchain")

	if err := fs.Parse(args); err != nil {
		return err
	}

	var missing []string
	if *command == "" {
		missing = append(missing, "--cmd")
	}
	if *n <= 0 {
		missing = append(missing, "--n (must be > 0)")
	}
	if *state == "" {
		missing = append(missing, "--state")
	}
	if *experimentID == "" {
		missing = append(missing, "--experiment")
	}
	if *fixtureID == "" {
		missing = append(missing, "--fixture")
	}
	if *outDir == "" {
		missing = append(missing, "--out")
	}
	if len(missing) > 0 {
		return fmt.Errorf("missing required flags: %s", strings.Join(missing, ", "))
	}

	if *sourceRevision == "" {
		rev, err := commandOutput("git", "rev-parse", "HEAD")
		if err != nil {
			return fmt.Errorf("--source-revision not given and `git rev-parse HEAD` failed: %w", err)
		}
		*sourceRevision = rev
	}

	if *cores <= 0 {
		*cores = runtime.NumCPU()
	}
	if *osName == "" {
		*osName = runtime.GOOS
	}
	if *osArch == "" {
		*osArch = runtime.GOARCH
	}
	if *cpu == "" {
		*cpu = detectCPU()
	}
	if *ramGiB <= 0 {
		*ramGiB = detectRAMGiB()
	}
	if *osVersion == "" {
		*osVersion = detectOSVersion()
	}

	allToolchains := append([]benchmark.Toolchain{}, toolchains...)
	if goVersion, err := commandOutput("go", "version"); err == nil {
		allToolchains = append([]benchmark.Toolchain{{Name: "go", Version: parseGoVersion(goVersion)}}, allToolchains...)
	}

	fmt.Fprintf(os.Stderr, "t1bench: collecting %d sample(s) of %q (state=%s)\n", *n, *command, *state)
	samples := make([]float64, 0, *n)
	for i := 0; i < *n; i++ {
		start := time.Now()
		cmd := exec.Command("sh", "-c", *command)
		cmd.Stdout = nil
		cmd.Stderr = os.Stderr
		if err := cmd.Run(); err != nil {
			return fmt.Errorf("sample %d: command failed: %w", i+1, err)
		}
		samples = append(samples, time.Since(start).Seconds())
	}

	median, p95, err := benchmark.ComputeStatistics(samples)
	if err != nil {
		return fmt.Errorf("computing statistics: %w", err)
	}

	var reservationPtr *int
	if *reservationCount >= 0 {
		reservationPtr = reservationCount
	}

	record := benchmark.Record{
		SchemaVersion:     benchmark.CurrentSchemaVersion,
		ExperimentID:      *experimentID,
		FixtureID:         *fixtureID,
		SourceRevision:    *sourceRevision,
		Timestamp:         time.Now().UTC().Format(time.RFC3339),
		Hardware:          benchmark.Hardware{CPU: *cpu, Cores: *cores, RAMGiB: *ramGiB},
		OS:                benchmark.OS{Name: *osName, Version: *osVersion, Arch: *osArch},
		Toolchain:         allToolchains,
		State:             benchmark.State(*state),
		CacheDimensions:   map[string]string(cacheDims),
		Samples:           samples,
		SampleCount:       len(samples),
		Median:            median,
		P95:               p95,
		ReservationCount:  reservationPtr,
		RawResultLocation: "samples.txt",
	}

	if err := benchmark.Validate(record); err != nil {
		return fmt.Errorf("collected record failed validation, nothing written:\n%w", err)
	}

	if err := os.MkdirAll(*outDir, 0o755); err != nil {
		return fmt.Errorf("creating --out directory: %w", err)
	}

	var samplesText strings.Builder
	for _, s := range samples {
		fmt.Fprintf(&samplesText, "%v\n", s)
	}
	if err := os.WriteFile(filepath.Join(*outDir, "samples.txt"), []byte(samplesText.String()), 0o644); err != nil {
		return fmt.Errorf("writing samples.txt: %w", err)
	}

	recordJSON, err := json.MarshalIndent(record, "", "  ")
	if err != nil {
		return fmt.Errorf("marshaling record: %w", err)
	}
	if err := os.WriteFile(filepath.Join(*outDir, "record.json"), append(recordJSON, '\n'), 0o644); err != nil {
		return fmt.Errorf("writing record.json: %w", err)
	}

	fmt.Fprintf(os.Stderr, "t1bench: wrote %s (median=%.3fs p95=%.3fs)\n", filepath.Join(*outDir, "record.json"), median, p95)
	return nil
}

func commandOutput(name string, args ...string) (string, error) {
	out, err := exec.Command(name, args...).Output()
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(out)), nil
}

func parseGoVersion(goVersionOutput string) string {
	// "go version go1.25.12 darwin/arm64" -> "go1.25.12"
	fields := strings.Fields(goVersionOutput)
	for _, f := range fields {
		if strings.HasPrefix(f, "go1.") || strings.HasPrefix(f, "go2.") {
			return f
		}
	}
	return goVersionOutput
}

func detectCPU() string {
	switch runtime.GOOS {
	case "darwin":
		if v, err := commandOutput("sysctl", "-n", "machdep.cpu.brand_string"); err == nil {
			return v
		}
	case "linux":
		if data, err := os.ReadFile("/proc/cpuinfo"); err == nil {
			for _, line := range strings.Split(string(data), "\n") {
				if strings.HasPrefix(line, "model name") {
					if _, v, ok := strings.Cut(line, ":"); ok {
						return strings.TrimSpace(v)
					}
				}
			}
		}
	}
	return "unknown"
}

func detectRAMGiB() float64 {
	switch runtime.GOOS {
	case "darwin":
		if v, err := commandOutput("sysctl", "-n", "hw.memsize"); err == nil {
			if bytes, err := strconv.ParseFloat(v, 64); err == nil {
				return bytes / (1024 * 1024 * 1024)
			}
		}
	case "linux":
		if data, err := os.ReadFile("/proc/meminfo"); err == nil {
			for _, line := range strings.Split(string(data), "\n") {
				if strings.HasPrefix(line, "MemTotal:") {
					fields := strings.Fields(line)
					if len(fields) >= 2 {
						if kb, err := strconv.ParseFloat(fields[1], 64); err == nil {
							return kb / (1024 * 1024)
						}
					}
				}
			}
		}
	}
	return 0
}

func detectOSVersion() string {
	switch runtime.GOOS {
	case "darwin":
		if v, err := commandOutput("sw_vers", "-productVersion"); err == nil {
			return v
		}
	case "linux":
		if v, err := commandOutput("uname", "-r"); err == nil {
			return v
		}
	}
	return "unknown"
}
