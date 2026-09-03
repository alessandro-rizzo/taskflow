package maliciousplanner

import (
	"context"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
)

// attemptFSReadOutsideSource confines itself entirely to env.Dir: it treats
// one subdirectory as the declared "source" and another as
// "repository-external," then reads the external one via a path that
// escapes the source directory. It never touches any path outside env.Dir.
func attemptFSReadOutsideSource(ctx context.Context, env *SelfTestEnv) (AttemptResult, error) {
	sourceDir := filepath.Join(env.Dir, "fs-source")
	outsideDir := filepath.Join(env.Dir, "fs-outside")
	if err := os.MkdirAll(sourceDir, 0o755); err != nil {
		return AttemptResult{}, fmt.Errorf("creating synthetic source dir: %w", err)
	}
	if err := os.MkdirAll(outsideDir, 0o755); err != nil {
		return AttemptResult{}, fmt.Errorf("creating synthetic outside dir: %w", err)
	}
	marker := filepath.Join(outsideDir, "marker.txt")
	if err := os.WriteFile(marker, []byte("outside-marker"), 0o600); err != nil {
		return AttemptResult{}, fmt.Errorf("writing synthetic outside marker: %w", err)
	}

	// Simulated escape: reach outsideDir via a path that starts inside
	// sourceDir and walks out of it, the way a real path-traversal attempt
	// against a declared source root would.
	escaped := filepath.Join(sourceDir, "..", "fs-outside", "marker.txt")
	data, err := os.ReadFile(escaped)
	if err != nil {
		return AttemptResult{Diagnostic: fmt.Sprintf("read of an escaping path failed: %v", err)}, nil
	}
	return AttemptResult{Diagnostic: fmt.Sprintf(
		"read %d byte(s) via a path escaping the synthetic source root - unsurprising, since this fixture's own OS-level read has no sandbox to enforce a boundary yet; a real planner sandbox must deny this",
		len(data),
	)}, nil
}

// syntheticEnvVar is a name this fixture owns exclusively; it is never a
// real ambient environment variable.
const syntheticEnvVar = "TASKFLOW_MALICIOUS_PLANNER_SELFTEST_VAR"

// attemptEnvReadAmbient sets and reads back only its own synthetic
// environment variable - it never inspects any real ambient env var. It
// captures and restores any pre-existing value of that exact name (rather
// than only unsetting it), so running this in-process alongside other code
// (e.g. under `go test` in the same process, or if this package is ever
// imported as a library) cannot leave a stale or missing value behind.
func attemptEnvReadAmbient(ctx context.Context, env *SelfTestEnv) (AttemptResult, error) {
	value := "synthetic-env-value-for-" + env.SecretMarker
	previous, hadPrevious := os.LookupEnv(syntheticEnvVar)
	if err := os.Setenv(syntheticEnvVar, value); err != nil {
		return AttemptResult{}, fmt.Errorf("setting synthetic env var: %w", err)
	}
	defer func() {
		if hadPrevious {
			os.Setenv(syntheticEnvVar, previous)
		} else {
			os.Unsetenv(syntheticEnvVar)
		}
	}()

	got := os.Getenv(syntheticEnvVar)
	if got != value {
		return AttemptResult{}, fmt.Errorf("synthetic env var round-trip mismatch: got %d byte(s), want %d byte(s)", len(got), len(value))
	}
	return AttemptResult{Diagnostic: fmt.Sprintf(
		"read back its own synthetic env var %s, restoring any pre-existing value afterward - no real ambient environment variable was accessed or left altered", syntheticEnvVar,
	)}, nil
}

// attemptNetworkDialLoopback opens a loopback listener on an OS-assigned
// port and dials it WHILE STILL OPEN, then closes both ends. Dialing only
// after closing the listener would create a close-then-dial race: another
// process could bind that exact port in the gap, and a "successful" connect
// would then mean a real, unplanned local service was actually contacted -
// not a self-test artifact. Keeping the listener open for the entire dial
// removes that window entirely: a successful connect here can only ever
// reach this self-test's own listener.
func attemptNetworkDialLoopback(ctx context.Context, env *SelfTestEnv) (AttemptResult, error) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return AttemptResult{}, fmt.Errorf("opening a throwaway loopback listener: %w", err)
	}
	defer l.Close()
	addr := l.Addr().String()

	var d net.Dialer
	conn, dialErr := d.DialContext(ctx, "tcp", addr)
	if dialErr != nil {
		return AttemptResult{}, fmt.Errorf("dialing our own still-open loopback listener at %s: %w", addr, dialErr)
	}
	defer conn.Close()

	return AttemptResult{Diagnostic: fmt.Sprintf(
		"opened a loopback listener at %s and connected to it while still holding it open (no close-then-dial race) - only this self-test's own listener was ever reachable", addr,
	)}, nil
}

// trivialBinaryCandidates are known-safe, no-op system binaries this
// attempt may spawn. Resolved by directly stat-ing each absolute path
// ourselves (never via PATH/exec.LookPath), so nothing earlier in an
// attacker-controlled PATH could be substituted.
var trivialBinaryCandidates = []string{"/usr/bin/true", "/bin/true"}

func findTrivialBinary() (string, error) {
	for _, candidate := range trivialBinaryCandidates {
		info, err := os.Stat(candidate)
		if err == nil && !info.IsDir() {
			return candidate, nil
		}
	}
	return "", fmt.Errorf("no known-safe trivial binary found among %v", trivialBinaryCandidates)
}

// attemptProcessSpawnAndReap spawns exactly one trivial, harmless child
// process and waits for it under ctx's deadline, then confirms it exited.
// The child is resolved to a known-safe absolute path (never PATH/shell
// lookup, which could be hijacked by an attacker-controlled PATH) and given
// an explicit minimal environment rather than inheriting this process's
// real ambient environment, which could otherwise contain real credentials.
func attemptProcessSpawnAndReap(ctx context.Context, env *SelfTestEnv) (AttemptResult, error) {
	bin, err := findTrivialBinary()
	if err != nil {
		return AttemptResult{}, fmt.Errorf("resolving a known-safe trivial binary: %w", err)
	}

	cmd := exec.CommandContext(ctx, bin)
	cmd.Env = []string{"PATH=/usr/bin:/bin"} // explicit, minimal - never the real ambient environment
	if err := cmd.Run(); err != nil {
		return AttemptResult{}, fmt.Errorf("spawning and reaping a trivial child: %w", err)
	}
	if cmd.ProcessState == nil || !cmd.ProcessState.Exited() {
		return AttemptResult{}, fmt.Errorf("child process did not report a clean exit")
	}
	return AttemptResult{Diagnostic: fmt.Sprintf(
		"spawned one known-safe trivial child (%s, pid %d) with an explicit minimal environment (no ambient environment inherited, no PATH lookup) and reaped it before returning - no descendant was left running",
		bin, cmd.Process.Pid,
	)}, nil
}

// attemptResourceBoundedLoop allocates a small, explicitly-capped amount of
// memory across a capped number of iterations. It never grows without
// bound and checks ctx between iterations.
func attemptResourceBoundedLoop(ctx context.Context, env *SelfTestEnv) (AttemptResult, error) {
	const maxIterations = 1000
	const maxBytes = 1 << 20 // 1 MiB

	buf := make([]byte, 0, maxBytes)
	iterations := 0
	for i := 0; i < maxIterations && len(buf) < maxBytes; i++ {
		select {
		case <-ctx.Done():
			return AttemptResult{}, fmt.Errorf("bounded loop did not finish before its own small caps were reached: %w", ctx.Err())
		default:
		}
		buf = append(buf, byte(i))
		iterations++
	}
	return AttemptResult{Diagnostic: fmt.Sprintf(
		"allocated %d byte(s) across %d bounded iteration(s), then stopped by its own explicit cap (max %d bytes / %d iterations) - never grew without bound",
		len(buf), iterations, maxBytes, maxIterations,
	)}, nil
}

// attemptOutputSecretLeak deliberately embeds the run's synthetic secret
// marker in its own diagnostic text. This is intentional: it exists so the
// redaction path (result.go's Redact, applied to every attempt's diagnostic
// before persistence) is exercised against a real occurrence of the marker,
// not only asserted to exist.
func attemptOutputSecretLeak(ctx context.Context, env *SelfTestEnv) (AttemptResult, error) {
	return AttemptResult{Diagnostic: fmt.Sprintf(
		"attempted to leak synthetic secret %q through this diagnostic field - the runner must redact it before persisting", env.SecretMarker,
	)}, nil
}
