package e08

import (
	"context"
	"reflect"
	"testing"
)

type recordingSSHRunner struct {
	profile string
	calls   []SSHRequest
}

func (r *recordingSSHRunner) ConnectionCount() int { return len(r.calls) }

func (r *recordingSSHRunner) RoundTrip(_ context.Context, request SSHRequest) (SSHResponse, error) {
	r.calls = append(r.calls, request)
	response := SSHResponse{Version: SSHEnvelopeVersion, OperationID: request.OperationID, Revision: uint64(len(r.calls)), Status: "ok", Reason: ReasonCompleted, WorkerID: request.WorkerID, SandboxID: request.SandboxID}
	switch request.Operation {
	case "attest":
		response.ProfileDigest = r.profile
	case "exec":
		response.Output = append([]byte("ssh-linux:"), []byte("source-v1")...)
		response.Logs = []LogChunk{{Cursor: 1, Stream: "stdout", Digest: Digest(response.Output)}}
	}
	return response, nil
}

func testSSHProfile() Profile {
	return Profile{
		MechanismID: "local-linux-openssh", MechanismVersion: "v1-experimental",
		BaseImageDigest: Digest([]byte("linux-image")), OS: "linux", OSBuild: "test",
		Architecture: "arm64", Toolchains: []string{"e08-worker:test"},
		RunnerDigest: Digest([]byte("worker")), SandboxPolicyDigest: Digest([]byte("owned-root")),
		ResetPolicyDigest: Digest([]byte("exact-cleanup")), RequiredWorkerFeature: []string{"openssh", "process", "filesystem", "cas"},
	}
}

func TestSSHLinuxAdapterDrivesCore(t *testing.T) {
	profile := testSSHProfile()
	runner := &recordingSSHRunner{profile: profile.Digest()}
	adapter := NewSSHLinuxAdapter(SSHLinuxConfig{Profile: profile, Runner: runner, WorkerID: "taskflow-e08-worker-a", AllowCommand: []string{"e08-w2"}})
	request := Request{RunID: "ssh", NodeID: "build", AttemptID: "ssh-attempt", Profile: profile, Source: []byte("source-v1"), Command: []string{"e08-w2"}, CacheVersion: "v1"}
	result := NewController().Run(context.Background(), adapter, request)
	if result.Status != "succeeded" || result.Reason != ReasonCompleted || result.Counters.ReservationReleases != 1 {
		t.Fatalf("result = %#v", result)
	}
	want := []string{"attest", "create_sandbox", "materialize", "exec", "cleanup"}
	got := make([]string, 0, len(runner.calls))
	for _, call := range runner.calls {
		got = append(got, call.Operation)
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("operations = %v, want %v", got, want)
	}
	if adapter.Connections() != len(want) {
		t.Fatalf("connections = %d", adapter.Connections())
	}
}

func TestSSHLinuxReadyHitOpensNoConnection(t *testing.T) {
	profile := testSSHProfile()
	runner := &recordingSSHRunner{profile: profile.Digest()}
	adapter := NewSSHLinuxAdapter(SSHLinuxConfig{Profile: profile, Runner: runner, WorkerID: "taskflow-e08-worker-a", AllowCommand: []string{"e08-w2"}})
	request := Request{RunID: "ssh", NodeID: "build", AttemptID: "cache-hit", Profile: profile, Source: []byte("source-v1"), Command: []string{"e08-w2"}, CacheVersion: "v1"}
	controller := NewController()
	if err := controller.PrimeVerifiedResult(request, []byte("prepared")); err != nil {
		t.Fatal(err)
	}
	result := controller.Run(context.Background(), adapter, request)
	if result.Status != "cache_hit" || !result.Counters.AllZero() || adapter.Connections() != 0 {
		t.Fatalf("cache hit touched SSH: %#v, connections=%d", result, adapter.Connections())
	}
}

func TestSSHLinuxRejectsCommandOutsideManifest(t *testing.T) {
	profile := testSSHProfile()
	runner := &recordingSSHRunner{profile: profile.Digest()}
	adapter := NewSSHLinuxAdapter(SSHLinuxConfig{Profile: profile, Runner: runner, WorkerID: "taskflow-e08-worker-a", AllowCommand: []string{"e08-w2"}})
	request := Request{RunID: "ssh", NodeID: "build", AttemptID: "bad-command", Profile: profile, Source: []byte("source-v1"), Command: []string{"sh", "-c", "id"}, CacheVersion: "v1"}
	result := NewController().Run(context.Background(), adapter, request)
	if result.Reason != ReasonCommandExitNonzero {
		t.Fatalf("reason = %s", result.Reason)
	}
	for _, call := range runner.calls {
		if call.Operation == "exec" {
			t.Fatal("unapproved command reached transport")
		}
	}
}
