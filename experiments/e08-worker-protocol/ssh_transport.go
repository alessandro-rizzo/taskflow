package e08

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os/exec"
	"reflect"
	"sync"
	"time"
)

const SSHEnvelopeVersion = "taskflow-e08-envelope/v1-experimental"

// SSHRequest and SSHResponse are disposable experiment envelopes. They are
// deliberately transport-shaped and are not production protocol types.
type SSHRequest struct {
	Version        string            `json:"version"`
	OperationID    string            `json:"operation_id"`
	Operation      string            `json:"operation"`
	WorkerID       string            `json:"worker_id"`
	SandboxID      string            `json:"sandbox_id,omitempty"`
	ProfileDigest  string            `json:"profile_digest,omitempty"`
	ObjectDigest   string            `json:"object_digest,omitempty"`
	Data           []byte            `json:"data,omitempty"`
	Command        []string          `json:"command,omitempty"`
	ExpectedRev    uint64            `json:"expected_revision"`
	ReconnectToken *ReconnectToken   `json:"reconnect_token,omitempty"`
	Details        map[string]string `json:"details,omitempty"`
}

type SSHResponse struct {
	Version       string     `json:"version"`
	OperationID   string     `json:"operation_id"`
	Revision      uint64     `json:"revision"`
	Status        string     `json:"status"`
	Reason        ReasonCode `json:"reason_code"`
	WorkerID      string     `json:"worker_id,omitempty"`
	SandboxID     string     `json:"sandbox_id,omitempty"`
	ProfileDigest string     `json:"profile_digest,omitempty"`
	Output        []byte     `json:"output,omitempty"`
	Logs          []LogChunk `json:"logs,omitempty"`
	Orphans       []Orphan   `json:"orphans,omitempty"`
	Details       string     `json:"details,omitempty"`
}

type SSHCommandRunner interface {
	RoundTrip(context.Context, SSHRequest) (SSHResponse, error)
	ConnectionCount() int
}

// OpenSSHRunner invokes only the completely specified command prefix. The
// caller is responsible for constructing it with strict host-key and identity
// arguments; this type never consults a shell or ambient SSH configuration.
type OpenSSHRunner struct {
	Command []string

	mu          sync.Mutex
	connections int
	command     *exec.Cmd
	stdin       io.WriteCloser
	decoder     *json.Decoder
	stderr      bytes.Buffer
}

func (r *OpenSSHRunner) RoundTrip(ctx context.Context, request SSHRequest) (SSHResponse, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if len(r.Command) == 0 || r.Command[0] != "/usr/bin/ssh" {
		return SSHResponse{}, &ProtocolError{Code: ReasonProviderUnavailable, Op: "SSH.RoundTrip", Err: errors.New("strict /usr/bin/ssh command is required")}
	}
	if err := ctx.Err(); err != nil {
		return SSHResponse{}, &ProtocolError{Code: ReasonCancelled, Op: "SSH.RoundTrip", Err: err}
	}
	if err := r.startLocked(); err != nil {
		return SSHResponse{}, err
	}
	request.Version = SSHEnvelopeVersion
	if err := json.NewEncoder(r.stdin).Encode(request); err != nil {
		r.stopLocked()
		return SSHResponse{}, &ProtocolError{Code: ReasonTransportDisconnected, Op: "SSH.Encode", Err: err}
	}
	var response SSHResponse
	if err := r.decoder.Decode(&response); err != nil {
		r.stopLocked()
		return SSHResponse{}, &ProtocolError{Code: ReasonTransportDisconnected, Op: "SSH.Decode", Err: err}
	}
	if response.Version != SSHEnvelopeVersion || response.OperationID != request.OperationID {
		return SSHResponse{}, &ProtocolError{Code: ReasonRevisionConflict, Op: "SSH.ResponseIdentity"}
	}
	if response.Reason != ReasonAccepted && response.Reason != ReasonCompleted {
		return response, &ProtocolError{Code: response.Reason, Op: request.Operation, Err: errors.New(response.Details)}
	}
	return response, nil
}

func (r *OpenSSHRunner) startLocked() error {
	if r.command != nil {
		return nil
	}
	r.stderr.Reset()
	cmd := exec.Command(r.Command[0], r.Command[1:]...)
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return err
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	cmd.Stderr = &r.stderr
	r.connections++
	if err := cmd.Start(); err != nil {
		return &ProtocolError{Code: ReasonTransportDisconnected, Op: "SSH.Start", Err: fmt.Errorf("%w: %s", err, bytes.TrimSpace(r.stderr.Bytes()))}
	}
	r.command, r.stdin, r.decoder = cmd, stdin, json.NewDecoder(stdout)
	r.decoder.DisallowUnknownFields()
	return nil
}

func (r *OpenSSHRunner) stopLocked() {
	if r.stdin != nil {
		_ = r.stdin.Close()
	}
	if r.command != nil && r.command.Process != nil {
		_ = r.command.Process.Kill()
		_, _ = r.command.Process.Wait()
	}
	r.command, r.stdin, r.decoder = nil, nil, nil
}

func (r *OpenSSHRunner) ConnectionCount() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.connections
}

// Disconnect terminates only this runner's SSH transport. Durable worker
// state remains owned by the remote daemon and the next RoundTrip reconnects.
func (r *OpenSSHRunner) Disconnect() {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.stopLocked()
}

type SSHLinuxConfig struct {
	Profile         Profile
	Runner          SSHCommandRunner
	WorkerID        string
	AllowCommand    []string
	Unavailable     bool
	ProfileMismatch bool
}

type SSHLinuxAdapter struct {
	config   SSHLinuxConfig
	mu       sync.Mutex
	serial   int
	active   map[string]bool
	instance string
}

func NewSSHLinuxAdapter(config SSHLinuxConfig) *SSHLinuxAdapter {
	return &SSHLinuxAdapter{config: config, active: make(map[string]bool), instance: fmt.Sprintf("%x", time.Now().UnixNano())}
}

func (a *SSHLinuxAdapter) ID() string       { return AdapterSSHLinux }
func (a *SSHLinuxAdapter) Profile() Profile { return a.config.Profile }

func (a *SSHLinuxAdapter) TryReserve(_ context.Context, profileDigest string) (Reservation, error) {
	if a.config.Unavailable {
		return Reservation{Disposition: DispositionUnavailable, Profile: profileDigest}, &ProtocolError{Code: ReasonProviderUnavailable, Op: "TryReserve"}
	}
	if profileDigest != a.config.Profile.Digest() {
		return Reservation{Disposition: DispositionMismatch, Profile: profileDigest}, nil
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	a.serial++
	reservation := Reservation{ID: fmt.Sprintf("taskflow-e08-ssh-reservation-%s-%d", a.instance, a.serial), Disposition: DispositionGranted, Profile: profileDigest}
	a.active[reservation.ID] = true
	return reservation, nil
}

func (a *SSHLinuxAdapter) ReleaseReservation(_ context.Context, reservation Reservation) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	delete(a.active, reservation.ID)
	return nil
}

func (a *SSHLinuxAdapter) Acquire(_ context.Context, reservation Reservation) (Worker, error) {
	if a.config.Runner == nil || a.config.WorkerID == "" {
		return nil, &ProtocolError{Code: ReasonProviderUnavailable, Op: "Acquire", Err: errors.New("SSH runner unavailable")}
	}
	return &sshLinuxWorker{adapter: a, id: a.config.WorkerID, reservation: reservation}, nil
}

func (a *SSHLinuxAdapter) Connections() int {
	if a.config.Runner == nil {
		return 0
	}
	return a.config.Runner.ConnectionCount()
}

type sshLinuxWorker struct {
	adapter     *SSHLinuxAdapter
	id          string
	reservation Reservation
}

func (w *sshLinuxWorker) ID() string { return w.id }

func (w *sshLinuxWorker) Attest(ctx context.Context, expected string) (string, error) {
	requestExpected := expected
	if w.adapter.config.ProfileMismatch {
		requestExpected = Digest([]byte("forced-mismatch"))
	}
	response, err := w.adapter.config.Runner.RoundTrip(ctx, SSHRequest{
		OperationID: w.reservation.ID + ":attest", Operation: "attest",
		WorkerID: w.id, ProfileDigest: requestExpected,
	})
	if err != nil {
		return "", err
	}
	return response.ProfileDigest, nil
}

func (w *sshLinuxWorker) CreateSandbox(ctx context.Context, id string) (Sandbox, error) {
	remoteID := "taskflow-e08-sandbox-" + Digest([]byte(id))[7:23]
	response, err := w.adapter.config.Runner.RoundTrip(ctx, SSHRequest{
		OperationID: w.reservation.ID + ":sandbox:" + remoteID, Operation: "create_sandbox",
		WorkerID: w.id, SandboxID: remoteID,
	})
	if err != nil {
		return nil, err
	}
	return &sshLinuxSandbox{id: id, remoteID: response.SandboxID, worker: w}, nil
}

type sshLinuxSandbox struct {
	id       string
	remoteID string
	worker   *sshLinuxWorker
}

func (s *sshLinuxSandbox) ID() string { return s.id }

func (s *sshLinuxSandbox) Materialize(ctx context.Context, expected string, data []byte) error {
	_, err := s.worker.adapter.config.Runner.RoundTrip(ctx, SSHRequest{
		OperationID: s.remoteID + ":materialize:" + expected, Operation: "materialize",
		WorkerID: s.worker.id, SandboxID: s.remoteID, ObjectDigest: expected, Data: data,
	})
	return err
}

func (s *sshLinuxSandbox) AcquireSession(context.Context, string) (string, error) {
	return "", &ProtocolError{Code: ReasonProviderUnavailable, Op: "AcquireSession", Err: errors.New("stateless Linux worker has no session")}
}

func (s *sshLinuxSandbox) Exec(ctx context.Context, command []string) (ExecutionResult, error) {
	if !reflect.DeepEqual(command, s.worker.adapter.config.AllowCommand) {
		return ExecutionResult{}, &ProtocolError{Code: ReasonCommandExitNonzero, Op: "Exec", Err: errors.New("command is outside the SSH manifest allowlist")}
	}
	response, err := s.worker.adapter.config.Runner.RoundTrip(ctx, SSHRequest{
		OperationID: s.remoteID + ":exec:" + Digest([]byte(fmt.Sprint(command))), Operation: "exec",
		WorkerID: s.worker.id, SandboxID: s.remoteID, Command: command,
	})
	result := ExecutionResult{Output: response.Output, Logs: response.Logs, Reason: response.Reason}
	if err != nil {
		return result, err
	}
	result.ExitCode = 0
	return result, nil
}

func (s *sshLinuxSandbox) Cleanup(ctx context.Context) error {
	_, err := s.worker.adapter.config.Runner.RoundTrip(ctx, SSHRequest{
		OperationID: s.remoteID + ":cleanup", Operation: "cleanup",
		WorkerID: s.worker.id, SandboxID: s.remoteID,
	})
	return err
}
