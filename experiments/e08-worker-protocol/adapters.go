package e08

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"time"
)

type AdapterConfig struct {
	Unavailable        bool
	ProfileMismatch    bool
	AcquireDelay       time.Duration
	CleanupDelay       time.Duration
	CleanupFailure     bool
	MaterializeFailure ReasonCode
	ExecFailure        ReasonCode
}

type InProcessAdapter struct {
	profile Profile
	config  AdapterConfig
	mu      sync.Mutex
	serial  int
	active  map[string]bool
}

func NewInProcessAdapter(config AdapterConfig) *InProcessAdapter {
	return &InProcessAdapter{
		config: config,
		active: make(map[string]bool),
		profile: Profile{
			MechanismID: "in-process-native", MechanismVersion: "v1-experimental",
			BaseImageDigest: Digest([]byte("local-host-observed")), OS: "local", OSBuild: "observed",
			Architecture: "native", Toolchains: []string{"shell:system"},
			RunnerDigest:          Digest([]byte("e08-in-process-runner-v1")),
			SandboxPolicyDigest:   Digest([]byte("attempt-owned-temp-root-v1")),
			ResetPolicyDigest:     Digest([]byte("remove-exact-temp-root-v1")),
			RequiredWorkerFeature: []string{"process", "filesystem", "cas"},
		},
	}
}

func (a *InProcessAdapter) ID() string       { return AdapterInProcess }
func (a *InProcessAdapter) Profile() Profile { return a.profile }

func (a *InProcessAdapter) TryReserve(_ context.Context, profileDigest string) (Reservation, error) {
	if a.config.Unavailable {
		return Reservation{Disposition: DispositionUnavailable, Profile: profileDigest}, &ProtocolError{Code: ReasonProviderUnavailable, Op: "TryReserve"}
	}
	if profileDigest != a.profile.Digest() {
		return Reservation{Disposition: DispositionMismatch, Profile: profileDigest}, nil
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	a.serial++
	reservation := Reservation{ID: fmt.Sprintf("taskflow-e08-local-reservation-%d", a.serial), Disposition: DispositionGranted, Profile: profileDigest}
	a.active[reservation.ID] = true
	return reservation, nil
}

func (a *InProcessAdapter) ReleaseReservation(_ context.Context, reservation Reservation) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	delete(a.active, reservation.ID)
	return nil
}

func (a *InProcessAdapter) Acquire(ctx context.Context, reservation Reservation) (Worker, error) {
	if a.config.AcquireDelay > 0 {
		timer := time.NewTimer(a.config.AcquireDelay)
		defer timer.Stop()
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-timer.C:
		}
	}
	return &inProcessWorker{id: reservation.ID + ":worker", profile: a.profile, config: a.config}, nil
}

type inProcessWorker struct {
	id      string
	profile Profile
	config  AdapterConfig
}

func (w *inProcessWorker) ID() string { return w.id }

func (w *inProcessWorker) Attest(_ context.Context, _ string) (string, error) {
	if w.config.ProfileMismatch {
		return Digest([]byte("unexpected-profile")), nil
	}
	return w.profile.Digest(), nil
}

func (w *inProcessWorker) CreateSandbox(_ context.Context, id string) (Sandbox, error) {
	root, err := os.MkdirTemp("", "taskflow-e08-in-process-")
	if err != nil {
		return nil, err
	}
	return &inProcessSandbox{id: id, root: root, config: w.config}, nil
}

type inProcessSandbox struct {
	id      string
	root    string
	config  AdapterConfig
	mu      sync.Mutex
	logs    []LogChunk
	cleaned bool
}

func (s *inProcessSandbox) ID() string { return s.id }

func (s *inProcessSandbox) Materialize(_ context.Context, expected string, data []byte) error {
	if s.config.MaterializeFailure != "" {
		return &ProtocolError{Code: s.config.MaterializeFailure, Op: "Materialize"}
	}
	if Digest(data) != expected {
		return &ProtocolError{Code: ReasonObjectDigestMismatch, Op: "Materialize"}
	}
	input := filepath.Join(s.root, "input")
	if err := os.MkdirAll(input, 0o700); err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(input, "source.txt"), data, 0o600)
}

func (s *inProcessSandbox) AcquireSession(_ context.Context, id string) (string, error) {
	return id, nil
}

func (s *inProcessSandbox) Exec(ctx context.Context, command []string) (ExecutionResult, error) {
	if s.config.ExecFailure != "" {
		return ExecutionResult{Reason: s.config.ExecFailure}, &ProtocolError{Code: s.config.ExecFailure, Op: "Exec"}
	}
	if len(command) == 0 {
		return ExecutionResult{}, &ProtocolError{Code: ReasonCommandExitNonzero, Op: "Exec", Err: errors.New("empty command")}
	}
	cmd := exec.CommandContext(ctx, command[0], command[1:]...)
	cmd.Dir = s.root
	cmd.Env = []string{"HOME=" + filepath.Join(s.root, "home"), "TMPDIR=" + filepath.Join(s.root, "tmp"), "PATH=/usr/bin:/bin"}
	if err := os.MkdirAll(filepath.Join(s.root, "home"), 0o700); err != nil {
		return ExecutionResult{}, err
	}
	if err := os.MkdirAll(filepath.Join(s.root, "tmp"), 0o700); err != nil {
		return ExecutionResult{}, err
	}
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	err := cmd.Run()
	logs := make([]LogChunk, 0, 2)
	if stdout.Len() > 0 {
		logs = append(logs, LogChunk{Cursor: uint64(len(logs) + 1), Stream: "stdout", Digest: Digest(stdout.Bytes()), Bytes: append([]byte(nil), stdout.Bytes()...)})
	}
	if stderr.Len() > 0 {
		logs = append(logs, LogChunk{Cursor: uint64(len(logs) + 1), Stream: "stderr", Digest: Digest(stderr.Bytes()), Bytes: append([]byte(nil), stderr.Bytes()...)})
	}
	s.mu.Lock()
	s.logs = append([]LogChunk(nil), logs...)
	s.mu.Unlock()
	result := ExecutionResult{ExitCode: 0, Output: append([]byte(nil), stdout.Bytes()...), Logs: logs, Reason: ReasonCompleted}
	if err != nil {
		if errors.Is(ctx.Err(), context.Canceled) || errors.Is(ctx.Err(), context.DeadlineExceeded) {
			result.Reason = ReasonCancelled
			return result, &ProtocolError{Code: ReasonCancelled, Op: "Exec", Err: ctx.Err()}
		}
		var exit *exec.ExitError
		if errors.As(err, &exit) {
			result.ExitCode = exit.ExitCode()
		}
		result.Reason = ReasonCommandExitNonzero
		return result, &ProtocolError{Code: ReasonCommandExitNonzero, Op: "Exec", Err: err}
	}
	return result, nil
}

func (s *inProcessSandbox) Cleanup(ctx context.Context) error {
	if s.config.CleanupDelay > 0 {
		timer := time.NewTimer(s.config.CleanupDelay)
		defer timer.Stop()
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-timer.C:
		}
	}
	if s.config.CleanupFailure {
		return &ProtocolError{Code: ReasonCleanupTimeout, Op: "Cleanup"}
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.cleaned {
		return nil
	}
	base := filepath.Base(s.root)
	if !filepath.IsAbs(s.root) || len(base) < len("taskflow-e08-in-process-")+1 || base[:len("taskflow-e08-in-process-")] != "taskflow-e08-in-process-" {
		return &ProtocolError{Code: ReasonOutputPathEscape, Op: "Cleanup", Err: fmt.Errorf("refusing unowned root")}
	}
	if err := os.RemoveAll(s.root); err != nil {
		return err
	}
	s.cleaned = true
	return nil
}

type MacOSStubAdapter struct {
	profile Profile
	config  AdapterConfig
	mu      sync.Mutex
	serial  int
	active  map[string]bool
}

func NewMacOSStubAdapter(config AdapterConfig) *MacOSStubAdapter {
	return &MacOSStubAdapter{
		config: config,
		active: make(map[string]bool),
		profile: Profile{
			MechanismID: "e06-macos-stub", MechanismVersion: "v1-experimental",
			BaseImageDigest: Digest([]byte("e06-stub-no-image")), OS: "macos", OSBuild: "25F84",
			Architecture: "arm64", Toolchains: []string{"xcode:26.6-17F113", "ios-sdk:26.5-23F81a", "ios-runtime:26.5-23F77"},
			RunnerDigest:          Digest([]byte("e08-macos-stub-runner-v1")),
			SandboxPolicyDigest:   Digest([]byte("e06-disposable-workspace-derived-data-stub-v1")),
			ResetPolicyDigest:     Digest([]byte("e06-session-reset-stub-v1")),
			RequiredWorkerFeature: []string{"xcode", "simulator-session", "namespace-lease"},
		},
	}
}

func (a *MacOSStubAdapter) ID() string       { return AdapterMacOSStub }
func (a *MacOSStubAdapter) Profile() Profile { return a.profile }

func (a *MacOSStubAdapter) TryReserve(_ context.Context, profileDigest string) (Reservation, error) {
	if a.config.Unavailable {
		return Reservation{Disposition: DispositionUnavailable, Profile: profileDigest}, &ProtocolError{Code: ReasonProviderUnavailable, Op: "TryReserve"}
	}
	if profileDigest != a.profile.Digest() {
		return Reservation{Disposition: DispositionMismatch, Profile: profileDigest}, nil
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	a.serial++
	reservation := Reservation{ID: fmt.Sprintf("taskflow-e08-macos-stub-reservation-%d", a.serial), Disposition: DispositionGranted, Profile: profileDigest}
	a.active[reservation.ID] = true
	return reservation, nil
}

func (a *MacOSStubAdapter) ReleaseReservation(_ context.Context, reservation Reservation) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	delete(a.active, reservation.ID)
	return nil
}

func (a *MacOSStubAdapter) Acquire(ctx context.Context, reservation Reservation) (Worker, error) {
	if a.config.AcquireDelay > 0 {
		timer := time.NewTimer(a.config.AcquireDelay)
		defer timer.Stop()
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-timer.C:
		}
	}
	return &macOSStubWorker{id: reservation.ID + ":worker", profile: a.profile, config: a.config}, nil
}

type macOSStubWorker struct {
	id      string
	profile Profile
	config  AdapterConfig
}

func (w *macOSStubWorker) ID() string { return w.id }

func (w *macOSStubWorker) Attest(_ context.Context, _ string) (string, error) {
	if w.config.ProfileMismatch {
		return Digest([]byte("unexpected-macos-stub-profile")), nil
	}
	return w.profile.Digest(), nil
}

func (w *macOSStubWorker) CreateSandbox(_ context.Context, id string) (Sandbox, error) {
	return &macOSStubSandbox{id: id, config: w.config}, nil
}

type macOSStubSandbox struct {
	id      string
	config  AdapterConfig
	source  []byte
	session string
	cleaned bool
}

func (s *macOSStubSandbox) ID() string { return s.id }

func (s *macOSStubSandbox) Materialize(_ context.Context, expected string, data []byte) error {
	if s.config.MaterializeFailure != "" {
		return &ProtocolError{Code: s.config.MaterializeFailure, Op: "Materialize"}
	}
	if Digest(data) != expected {
		return &ProtocolError{Code: ReasonObjectDigestMismatch, Op: "Materialize"}
	}
	s.source = append([]byte(nil), data...)
	return nil
}

func (s *macOSStubSandbox) AcquireSession(_ context.Context, id string) (string, error) {
	s.session = id
	return id, nil
}

func (s *macOSStubSandbox) Exec(ctx context.Context, command []string) (ExecutionResult, error) {
	select {
	case <-ctx.Done():
		return ExecutionResult{Reason: ReasonCancelled}, &ProtocolError{Code: ReasonCancelled, Op: "Exec", Err: ctx.Err()}
	default:
	}
	if s.config.ExecFailure != "" {
		return ExecutionResult{Reason: s.config.ExecFailure}, &ProtocolError{Code: s.config.ExecFailure, Op: "Exec"}
	}
	if len(command) == 0 {
		return ExecutionResult{}, &ProtocolError{Code: ReasonCommandExitNonzero, Op: "Exec"}
	}
	output := append([]byte("macos-stub:"), s.source...)
	chunk := LogChunk{Cursor: 1, Stream: "stdout", Digest: Digest(output), Bytes: append([]byte(nil), output...)}
	return ExecutionResult{ExitCode: 0, Output: output, Logs: []LogChunk{chunk}, Reason: ReasonCompleted}, nil
}

func (s *macOSStubSandbox) Cleanup(ctx context.Context) error {
	if s.config.CleanupDelay > 0 {
		timer := time.NewTimer(s.config.CleanupDelay)
		defer timer.Stop()
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-timer.C:
		}
	}
	if s.config.CleanupFailure {
		return &ProtocolError{Code: ReasonCleanupTimeout, Op: "Cleanup"}
	}
	s.source = nil
	s.session = ""
	s.cleaned = true
	return nil
}
