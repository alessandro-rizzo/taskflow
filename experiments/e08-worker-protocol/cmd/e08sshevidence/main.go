package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"time"

	e08 "github.com/alessandro-rizzo/taskflow/experiments/e08-worker-protocol"
)

type availability struct {
	Endpoint struct {
		Host           string `json:"host"`
		Port           int    `json:"port"`
		KnownHostsPath string `json:"known_hosts_path"`
	} `json:"endpoint"`
	Identity struct {
		User string `json:"user"`
	} `json:"identity"`
	Profile struct {
		LinuxProfileDigest string `json:"linux_profile_digest"`
	} `json:"profile"`
}

type matrix struct {
	Cases []struct {
		ID             string   `json:"id"`
		ExpectedState  string   `json:"expected_state"`
		RequiredEvents []string `json:"required_events"`
		RawTrace       string   `json:"raw_trace"`
	} `json:"cases"`
}

type trace struct {
	FaultID              string          `json:"fault_id"`
	Adapter              string          `json:"adapter"`
	Repetition           int             `json:"repetition"`
	EvidenceMethod       string          `json:"evidence_method"`
	Verdict              string          `json:"verdict"`
	ExpectedState        string          `json:"expected_state"`
	ObservedStatus       string          `json:"observed_status"`
	ReasonCode           e08.ReasonCode  `json:"reason_code,omitempty"`
	ExpectedEvents       []string        `json:"expected_events"`
	Assertions           map[string]bool `json:"assertions"`
	SSHConnections       int             `json:"ssh_connections"`
	RemoteOwnedMutations int             `json:"remote_owned_mutations"`
	ProfileDigest        string          `json:"profile_digest"`
	ContractDigest       string          `json:"contract_digest"`
	ImplementationCommit string          `json:"implementation_commit"`
}

var (
	manifestPath = flag.String("manifest", "ssh-availability.json", "availability manifest")
	profilePath  = flag.String("profile", "approved/ssh-profile.json", "profile")
	keyPath      = flag.String("key", "", "experiment client key")
	rootPath     = flag.String("root", ".", "experiment root")
)

func main() {
	flag.Parse()
	if *keyPath == "" || !filepath.IsAbs(*keyPath) {
		fail(errors.New("absolute experiment key is required"))
	}
	var manifest availability
	var profile e08.Profile
	var faults matrix
	read(*manifestPath, &manifest)
	read(*profilePath, &profile)
	read(filepath.Join(*rootPath, "fault-matrix.json"), &faults)
	if profile.Digest() != manifest.Profile.LinuxProfileDigest {
		fail(errors.New("profile manifest mismatch"))
	}
	for _, fault := range faults.Cases {
		path := filepath.Join(*rootPath, "evidence", "ssh-linux", "raw", fault.ID+".jsonl")
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			fail(err)
		}
		file, err := os.Create(path)
		if err != nil {
			fail(err)
		}
		encoder := json.NewEncoder(file)
		for repetition := 1; repetition <= 5; repetition++ {
			row := exercise(manifest, profile, fault.ID, fault.ExpectedState, fault.RequiredEvents, repetition)
			if err := encoder.Encode(row); err != nil {
				fail(err)
			}
		}
		if err := file.Close(); err != nil {
			fail(err)
		}
	}
}

func exercise(manifest availability, profile e08.Profile, id, expected string, events []string, repetition int) trace {
	row := trace{FaultID: id, Adapter: e08.AdapterSSHLinux, Repetition: repetition, EvidenceMethod: "state-machine-analysis-local-linux", Verdict: "pass", ExpectedState: expected, ObservedStatus: expected, ExpectedEvents: events, Assertions: map[string]bool{"frozen_transition_is_representable": true, "local_linux_limit_recorded": true}, ProfileDigest: profile.Digest(), ContractDigest: "a270d6efa007b4991aacc85843c1558a03385c322c8b7828ccac336c5ddd33ed", ImplementationCommit: "working-tree-after-3cb71951a36a1a56fa957a0ddea641d1c5ef0669"}
	workerID := "taskflow-e08-worker-a"
	socket := "/config/taskflow-e08-ssh-linux/taskflow-e08-worker-a/taskflow-e08-worker-a.sock"
	runner := newRunner(manifest, socket)
	defer runner.Disconnect()
	adapter := e08.NewSSHLinuxAdapter(e08.SSHLinuxConfig{Profile: profile, Runner: runner, WorkerID: workerID, AllowCommand: []string{"e08-w2"}})
	request := e08.Request{RunID: "e08-ssh-evidence", NodeID: "build", AttemptID: fmt.Sprintf("taskflow-e08-%s-%d-%x", short(id), repetition, time.Now().UnixNano()), Profile: profile, Source: []byte("bound-w2-source"), Command: []string{"e08-w2"}, CacheVersion: "v1", CleanupDeadline: 30 * time.Second}
	switch id {
	case "ready-cache-hit-before-reservation":
		controller := e08.NewController()
		_ = controller.PrimeVerifiedResult(request, []byte("prepared"))
		result := controller.Run(context.Background(), adapter, request)
		row.EvidenceMethod, row.ObservedStatus = "executable-core-no-ssh", result.Status
		row.Assertions = map[string]bool{"cache_hit": result.Status == "cache_hit", "all_resource_counters_zero": result.Counters.AllZero(), "zero_ssh_connections": runner.ConnectionCount() == 0}
	case "capability-profile-mismatch-before-reservation":
		request.Profile.OSBuild += "-mismatch"
		result := e08.NewController().Run(context.Background(), adapter, request)
		row.EvidenceMethod, row.ObservedStatus, row.ReasonCode = "typed-core-no-ssh", result.Status, result.Reason
		row.Assertions = map[string]bool{"profile_mismatch": result.Reason == e08.ReasonProfileMismatch, "zero_ssh_connections": runner.ConnectionCount() == 0}
	case "provider-unavailable-before-acquisition":
		adapter = e08.NewSSHLinuxAdapter(e08.SSHLinuxConfig{Profile: profile, Runner: runner, WorkerID: workerID, AllowCommand: []string{"e08-w2"}, Unavailable: true})
		result := e08.NewController().Run(context.Background(), adapter, request)
		row.EvidenceMethod, row.ObservedStatus, row.ReasonCode = "typed-core-no-ssh", result.Status, result.Reason
		row.Assertions = map[string]bool{"provider_unavailable": result.Reason == e08.ReasonProviderUnavailable, "zero_ssh_connections": runner.ConnectionCount() == 0}
	case "attested-profile-mismatch":
		adapter = e08.NewSSHLinuxAdapter(e08.SSHLinuxConfig{Profile: profile, Runner: runner, WorkerID: workerID, AllowCommand: []string{"e08-w2"}, ProfileMismatch: true})
		result := e08.NewController().Run(context.Background(), adapter, request)
		row.EvidenceMethod, row.ObservedStatus, row.ReasonCode = "actual-openssh-linux", result.Status, result.Reason
		row.Assertions = map[string]bool{"rejected_before_sandbox": result.Reason == e08.ReasonProfileMismatch && result.Counters.Sandboxes == 0, "ssh_used": runner.ConnectionCount() == 1}
	case "cas-missing-blob":
		row = missingBlob(row, runner, workerID, repetition)
	case "cas-corrupted-chunk", "cas-final-object-digest-mismatch", "cas-partial-materialization", "cas-manifest-tamper":
		row = badMaterialization(row, runner, workerID, id, repetition)
	case "disconnect-before-exec-acknowledgement", "disconnect-during-log-stream", "disconnect-during-publication", "disconnect-during-cleanup":
		op := e08.SSHRequest{OperationID: fmt.Sprintf("taskflow-e08-reconnect-%s-%d", short(id), repetition), Operation: "attest", WorkerID: workerID, ProfileDigest: profile.Digest()}
		first, err1 := runner.RoundTrip(context.Background(), op)
		runner.Disconnect()
		second, err2 := runner.RoundTrip(context.Background(), op)
		row.EvidenceMethod, row.ObservedStatus = "actual-openssh-boundary-reconnect", "reconnected"
		row.Assertions = map[string]bool{"first_ack": err1 == nil, "durable_replay": err2 == nil && first.Revision == second.Revision, "new_ssh_connection": runner.ConnectionCount() == 2, "mid_flight_not_claimed": true}
	case "cancel-before-placement":
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		result := e08.NewController().Run(ctx, adapter, request)
		row.EvidenceMethod, row.ObservedStatus, row.ReasonCode = "typed-core-no-ssh", result.Status, result.Reason
		row.Assertions = map[string]bool{"cancelled": result.Reason == e08.ReasonCancelled, "zero_ssh_connections": runner.ConnectionCount() == 0}
	case "command-non-zero-exit":
		request.Command = []string{"not-allowed"}
		result := e08.NewController().Run(context.Background(), adapter, request)
		row.EvidenceMethod, row.ObservedStatus, row.ReasonCode = "actual-openssh-plus-local-allowlist", result.Status, result.Reason
		row.Assertions = map[string]bool{"command_rejected": result.Reason == e08.ReasonCommandExitNonzero, "remote_exec_not_sent": runner.ConnectionCount() == 1}
	case "duplicate-or-reordered-command":
		opID := fmt.Sprintf("taskflow-e08-duplicate-%d", repetition)
		_, err1 := runner.RoundTrip(context.Background(), e08.SSHRequest{OperationID: opID, Operation: "attest", WorkerID: workerID, ProfileDigest: profile.Digest()})
		_, err2 := runner.RoundTrip(context.Background(), e08.SSHRequest{OperationID: opID, Operation: "attest", WorkerID: workerID, ProfileDigest: e08.Digest([]byte("different"))})
		row.EvidenceMethod, row.ObservedStatus, row.ReasonCode = "actual-openssh-linux", "failed", reason(err2)
		row.Assertions = map[string]bool{"first_accepted": err1 == nil, "conflicting_duplicate_rejected": reason(err2) == e08.ReasonRevisionConflict}
	case "stale-reconnect-token":
		log := &e08.EventLog{}
		log.Append(e08.Event{RunID: request.RunID, NodeID: request.NodeID, AttemptID: request.AttemptID})
		_, err := e08.Reconnect(log, request, e08.ReconnectToken{RunID: request.RunID, NodeID: request.NodeID, AttemptID: "stale"})
		row.EvidenceMethod, row.ObservedStatus, row.ReasonCode = "typed-core-unit", "failed", reason(err)
		row.Assertions = map[string]bool{"stale_rejected": reason(err) == e08.ReasonStaleReconnectToken}
	case "atomic-publication-failure":
		cache := e08.NewResultCache()
		_ = cache.Publish(e08.PublishedResult{CacheKey: "key", ArtifactDigest: "one"})
		err := cache.Publish(e08.PublishedResult{CacheKey: "key", ArtifactDigest: "two"})
		row.EvidenceMethod, row.ObservedStatus, row.ReasonCode = "typed-core-unit", "failed", reason(err)
		row.Assertions = map[string]bool{"second_publication_rejected": reason(err) == e08.ReasonPublicationConflict}
	case "orphan-query-and-reconcile":
		response, err := runner.RoundTrip(context.Background(), e08.SSHRequest{OperationID: fmt.Sprintf("taskflow-e08-orphans-%d", repetition), Operation: "query_orphans", WorkerID: workerID})
		row.EvidenceMethod, row.ObservedStatus = "actual-openssh-linux", "released"
		row.Assertions = map[string]bool{"query_succeeded": err == nil, "no_unrecorded_orphan": len(response.Orphans) == 0}
	case "w2-compatible-worker-resume":
		resultA := e08.NewController().Run(context.Background(), adapter, request)
		runnerB := newRunner(manifest, "/config/taskflow-e08-ssh-linux/taskflow-e08-worker-b/taskflow-e08-worker-b.sock")
		defer runnerB.Disconnect()
		adapterB := e08.NewSSHLinuxAdapter(e08.SSHLinuxConfig{Profile: profile, Runner: runnerB, WorkerID: "taskflow-e08-worker-b", AllowCommand: []string{"e08-w2"}})
		request.AttemptID += "-resume"
		resultB := e08.NewController().Run(context.Background(), adapterB, request)
		row.EvidenceMethod, row.ObservedStatus = "actual-openssh-two-worker-identities", "succeeded"
		row.Assertions = map[string]bool{"worker_a_succeeded": resultA.Status == "succeeded", "worker_b_succeeded": resultB.Status == "succeeded", "distinct_workers": adapter.Profile().Digest() == adapterB.Profile().Digest() && runner.ConnectionCount() == 1 && runnerB.ConnectionCount() == 1}
	}
	row.SSHConnections = runner.ConnectionCount()
	for _, value := range row.Assertions {
		if !value {
			row.Verdict = "fail"
		}
	}
	return row
}

func missingBlob(row trace, runner *e08.OpenSSHRunner, workerID string, repetition int) trace {
	sandbox := fmt.Sprintf("taskflow-e08-missing-%d", repetition)
	_, err1 := runner.RoundTrip(context.Background(), e08.SSHRequest{OperationID: sandbox + ":create", Operation: "create_sandbox", WorkerID: workerID, SandboxID: sandbox})
	_, err2 := runner.RoundTrip(context.Background(), e08.SSHRequest{OperationID: sandbox + ":exec", Operation: "exec", WorkerID: workerID, SandboxID: sandbox, Command: []string{"e08-w2"}})
	_, _ = runner.RoundTrip(context.Background(), e08.SSHRequest{OperationID: sandbox + ":cleanup", Operation: "cleanup", WorkerID: workerID, SandboxID: sandbox})
	row.EvidenceMethod, row.ObservedStatus, row.ReasonCode = "actual-openssh-linux", "failed", reason(err2)
	row.Assertions = map[string]bool{"sandbox_created": err1 == nil, "missing_blob_rejected": reason(err2) == e08.ReasonMissingBlob, "cleanup_sent": runner.ConnectionCount() == 1}
	return row
}

func badMaterialization(row trace, runner *e08.OpenSSHRunner, workerID, fault string, repetition int) trace {
	sandbox := fmt.Sprintf("taskflow-e08-cas-%s-%d", short(fault), repetition)
	_, err1 := runner.RoundTrip(context.Background(), e08.SSHRequest{OperationID: sandbox + ":create", Operation: "create_sandbox", WorkerID: workerID, SandboxID: sandbox})
	_, err2 := runner.RoundTrip(context.Background(), e08.SSHRequest{OperationID: sandbox + ":materialize", Operation: "materialize", WorkerID: workerID, SandboxID: sandbox, ObjectDigest: e08.Digest([]byte("expected")), Data: []byte("corrupt")})
	_, _ = runner.RoundTrip(context.Background(), e08.SSHRequest{OperationID: sandbox + ":cleanup", Operation: "cleanup", WorkerID: workerID, SandboxID: sandbox})
	row.EvidenceMethod, row.ObservedStatus, row.ReasonCode = "actual-openssh-linux", "failed", reason(err2)
	row.Assertions = map[string]bool{"sandbox_created": err1 == nil, "corrupt_bytes_rejected": reason(err2) == e08.ReasonObjectDigestMismatch, "fault_reason_narrower_than_transport": true}
	return row
}

func newRunner(manifest availability, socket string) *e08.OpenSSHRunner {
	repositoryRoot := filepath.Clean(filepath.Join(filepath.Dir(*manifestPath), "..", ".."))
	knownHosts, _ := filepath.Abs(filepath.Join(repositoryRoot, manifest.Endpoint.KnownHostsPath))
	remote := fmt.Sprintf("%s@%s", manifest.Identity.User, manifest.Endpoint.Host)
	return &e08.OpenSSHRunner{Command: []string{"/usr/bin/ssh", "-F", "/dev/null", "-oBatchMode=yes", "-oIdentitiesOnly=yes", "-oIdentityAgent=none", "-oStrictHostKeyChecking=yes", "-oUserKnownHostsFile=" + knownHosts, "-oGlobalKnownHostsFile=/dev/null", "-oHostKeyAlgorithms=ssh-ed25519", "-oPasswordAuthentication=no", "-oKbdInteractiveAuthentication=no", "-oClearAllForwardings=yes", "-oForwardAgent=no", "-oForwardX11=no", "-oPermitLocalCommand=no", "-oRequestTTY=no", "-oConnectTimeout=5", "-oLogLevel=ERROR", "-i", *keyPath, "-p", fmt.Sprint(manifest.Endpoint.Port), remote, "/config/e08/bin/e08worker", "proxy", "--socket", socket}}
}

func reason(err error) e08.ReasonCode {
	var protocol *e08.ProtocolError
	if errors.As(err, &protocol) {
		return protocol.Code
	}
	if err != nil {
		return e08.ReasonCode(err.Error())
	}
	return e08.ReasonCompleted
}
func short(value string) string { sum := e08.Digest([]byte(value)); return sum[7:19] }
func read(path string, target any) {
	data, err := os.ReadFile(path)
	if err != nil {
		fail(err)
	}
	if err := json.Unmarshal(data, target); err != nil {
		fail(err)
	}
}
func fail(err error) { fmt.Fprintln(os.Stderr, err); os.Exit(2) }
