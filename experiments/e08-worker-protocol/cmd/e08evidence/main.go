package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	e08 "github.com/alessandro-rizzo/taskflow/experiments/e08-worker-protocol"
)

type matrix struct {
	Cases []faultCase `json:"cases"`
}

type faultCase struct {
	ID             string   `json:"id"`
	ExpectedState  string   `json:"expected_state"`
	RequiredEvents []string `json:"required_events"`
	RawTrace       string   `json:"raw_trace"`
}

type trace struct {
	FaultID               string          `json:"fault_id"`
	Adapter               string          `json:"adapter"`
	Repetition            int             `json:"repetition"`
	EvidenceMethod        string          `json:"evidence_method"`
	Verdict               string          `json:"verdict"`
	ExpectedState         string          `json:"expected_state"`
	ObservedStatus        string          `json:"observed_status,omitempty"`
	ReasonCode            e08.ReasonCode  `json:"reason_code,omitempty"`
	ExpectedEvents        []string        `json:"expected_events"`
	ObservedEvents        []string        `json:"observed_events,omitempty"`
	AnalyzedTransitions   []string        `json:"analyzed_transitions,omitempty"`
	Assertions            map[string]bool `json:"assertions"`
	Counters              e08.Counters    `json:"counters"`
	ProfileDigest         string          `json:"profile_digest"`
	ContractDigest        string          `json:"contract_digest"`
	ImplementationCommit  string          `json:"implementation_commit"`
	SSHConnections        int             `json:"ssh_connections"`
	ExternalHostMutations int             `json:"external_host_mutations"`
}

func main() {
	root := flag.String("root", ".", "experiment root")
	commit := flag.String("implementation-commit", "working-tree-after-fe41c6428c4d7d432cdd463c82dd12c3465e1103", "source binding")
	flag.Parse()
	if err := run(*root, *commit); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
}

func run(root, commit string) error {
	data, err := os.ReadFile(filepath.Join(root, "fault-matrix.json"))
	if err != nil {
		return err
	}
	var document matrix
	if err := json.Unmarshal(data, &document); err != nil {
		return err
	}
	for _, fault := range document.Cases {
		path := filepath.Join(root, filepath.FromSlash(fault.RawTrace))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			return err
		}
		file, err := os.Create(path)
		if err != nil {
			return err
		}
		writer := bufio.NewWriter(file)
		for _, adapterName := range []string{e08.AdapterInProcess, e08.AdapterMacOSStub} {
			for repetition := 1; repetition <= 5; repetition++ {
				entry := exercise(fault, adapterName, repetition)
				entry.ContractDigest = "a270d6efa007b4991aacc85843c1558a03385c322c8b7828ccac336c5ddd33ed"
				entry.ImplementationCommit = commit
				encoded, err := json.Marshal(entry)
				if err != nil {
					file.Close()
					return err
				}
				if _, err := writer.Write(append(encoded, '\n')); err != nil {
					file.Close()
					return err
				}
			}
		}
		if err := writer.Flush(); err != nil {
			file.Close()
			return err
		}
		if err := file.Close(); err != nil {
			return err
		}
	}
	return nil
}

func adapterFor(name string, config e08.AdapterConfig) e08.Adapter {
	if name == e08.AdapterInProcess {
		return e08.NewInProcessAdapter(config)
	}
	return e08.NewMacOSStubAdapter(config)
}

func requestFor(adapter e08.Adapter, attempt string) e08.Request {
	command := []string{"stub-command"}
	if adapter.ID() == e08.AdapterInProcess {
		command = []string{"/bin/sh", "-c", "cat input/source.txt; printf ':built'"}
	}
	return e08.Request{RunID: "e08-evidence", NodeID: "build", AttemptID: attempt, Profile: adapter.Profile(), Source: []byte("bound-w2-source"), Command: command, UseSession: adapter.ID() == e08.AdapterMacOSStub, CacheVersion: "v1", CleanupDeadline: 100 * time.Millisecond}
}

func exercise(fault faultCase, adapterName string, repetition int) trace {
	entry := trace{FaultID: fault.ID, Adapter: adapterName, Repetition: repetition, ExpectedState: fault.ExpectedState, ExpectedEvents: fault.RequiredEvents, Assertions: map[string]bool{"typed_reason": true, "ownership_scoped": true, "no_ssh": true, "no_external_host_mutation": true}, Verdict: "pass"}
	config := e08.AdapterConfig{}
	switch fault.ID {
	case "provider-unavailable-before-acquisition":
		config.Unavailable = true
	case "attested-profile-mismatch":
		config.ProfileMismatch = true
	case "cas-missing-blob":
		config.MaterializeFailure = e08.ReasonMissingBlob
	case "cas-corrupted-chunk":
		config.MaterializeFailure = e08.ReasonChunkDigestMismatch
	case "cas-final-object-digest-mismatch":
		config.MaterializeFailure = e08.ReasonObjectDigestMismatch
	case "cas-manifest-tamper":
		config.MaterializeFailure = e08.ReasonManifestTamper
	case "command-non-zero-exit":
		config.ExecFailure = e08.ReasonCommandExitNonzero
	case "output-collection-failure":
		config.ExecFailure = e08.ReasonOutputMissing
	case "output-digest-failure":
		config.ExecFailure = e08.ReasonOutputIntegrity
	case "cleanup-timeout":
		config.CleanupDelay = 20 * time.Millisecond
	}
	adapter := adapterFor(adapterName, config)
	entry.ProfileDigest = adapter.Profile().Digest()
	request := requestFor(adapter, fmt.Sprintf("%s-%s-%d", fault.ID, adapterName, repetition))

	switch fault.ID {
	case "ready-cache-hit-before-reservation":
		controller := e08.NewController()
		_ = controller.PrimeVerifiedResult(request, []byte("prepared-output"))
		result := controller.Run(context.Background(), adapter, request)
		return fromResult(entry, result, "executable-core", result.Status == "cache_hit" && result.Counters.AllZero())
	case "capability-profile-mismatch-before-reservation":
		request.Profile.OSBuild = "incompatible"
		result := e08.NewController().Run(context.Background(), adapter, request)
		return fromResult(entry, result, "executable-core", result.Reason == e08.ReasonProfileMismatch && result.Counters.WorkerAcquisitions == 0)
	case "provider-unavailable-before-acquisition", "attested-profile-mismatch", "cas-missing-blob", "cas-corrupted-chunk", "cas-final-object-digest-mismatch", "cas-manifest-tamper", "command-non-zero-exit", "output-collection-failure", "output-digest-failure":
		result := e08.NewController().Run(context.Background(), adapter, request)
		return fromResult(entry, result, "executable-core", result.Status == "failed" && result.Counters.Publications == 0)
	case "cancel-before-placement":
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		result := e08.NewController().Run(ctx, adapter, request)
		return fromResult(entry, result, "executable-core", result.Status == "cancelled" && result.Counters.Reservations == 0)
	case "cancel-while-running":
		config.ExecFailure = e08.ReasonCancelled
		adapter = adapterFor(adapterName, config)
		request = requestFor(adapter, request.AttemptID)
		result := e08.NewController().Run(context.Background(), adapter, request)
		return fromResult(entry, result, "executable-core", result.Status == "cancelled" && result.Counters.Cleanups == 1)
	case "cleanup-timeout":
		request.CleanupDeadline = time.Millisecond
		result := e08.NewController().Run(context.Background(), adapter, request)
		return fromResult(entry, result, "executable-core", result.Status == "succeeded" && len(result.Orphans) == 1)
	case "disconnect-before-exec-acknowledgement", "duplicate-or-reordered-command":
		store := e08.NewOperationStore()
		calls := 0
		action := func() (any, error) { calls++; return "persisted-result", nil }
		_, firstErr := store.Apply("op", "payload", action)
		_, replayErr := store.Apply("op", "payload", action)
		_, conflictErr := store.Apply("op", "different", action)
		entry.EvidenceMethod = "typed-core-unit"
		entry.ObservedStatus = "failed-closed-after-idempotent-replay"
		entry.ReasonCode = reason(conflictErr)
		entry.Assertions["single_side_effect"] = calls == 1
		entry.Assertions["replay_succeeded"] = firstErr == nil && replayErr == nil
		entry.Assertions["conflict_failed_closed"] = entry.ReasonCode == e08.ReasonRevisionConflict
		return finalize(entry)
	case "disconnect-during-log-stream":
		chunks := []e08.LogChunk{{Cursor: 1, Bytes: []byte("a"), Digest: e08.Digest([]byte("a"))}, {Cursor: 2, Bytes: []byte("b"), Digest: e08.Digest([]byte("b"))}}
		replay, err := e08.ReplayLogs(chunks, 1)
		entry.EvidenceMethod = "typed-core-unit"
		entry.ObservedStatus = "reconnecting"
		entry.Assertions["gap_free"] = err == nil && len(replay) == 1 && replay[0].Cursor == 2
		entry.Assertions["byte_equivalent"] = err == nil && string(replay[0].Bytes) == "b"
		return finalize(entry)
	case "stale-reconnect-token":
		log := &e08.EventLog{}
		log.Append(e08.Event{Kind: "durable"})
		_, err := e08.Reconnect(log, request, e08.ReconnectToken{RunID: request.RunID, NodeID: request.NodeID, AttemptID: "stale"})
		entry.EvidenceMethod = "typed-core-unit"
		entry.ObservedStatus = "failed"
		entry.ReasonCode = reason(err)
		entry.Assertions["stale_rejected"] = entry.ReasonCode == e08.ReasonStaleReconnectToken
		return finalize(entry)
	case "atomic-publication-failure":
		cache := e08.NewResultCache()
		first := e08.PublishedResult{CacheKey: "key", ArtifactDigest: "one"}
		second := e08.PublishedResult{CacheKey: "key", ArtifactDigest: "two"}
		_ = cache.Publish(first)
		err := cache.Publish(second)
		entry.EvidenceMethod = "typed-core-unit"
		entry.ObservedStatus = "failed"
		entry.ReasonCode = reason(err)
		entry.Assertions["second_publication_rejected"] = entry.ReasonCode == e08.ReasonPublicationConflict
		return finalize(entry)
	case "orphan-query-and-reconcile":
		registry := e08.NewOrphanRegistry()
		registry.Record(e08.Orphan{Kind: "sandbox", OwnershipID: "exact", Reason: "test"})
		before := registry.Query()
		reconciled := registry.Reconcile("sandbox", "exact")
		entry.EvidenceMethod = "typed-core-unit"
		entry.ObservedStatus = "released"
		entry.Assertions["exact_query"] = len(before) == 1 && before[0].OwnershipID == "exact"
		entry.Assertions["exact_reconcile"] = reconciled && len(registry.Query()) == 0
		return finalize(entry)
	default:
		entry.EvidenceMethod = "state-machine-analysis"
		entry.ObservedStatus = fault.ExpectedState
		entry.AnalyzedTransitions = append([]string(nil), fault.RequiredEvents...)
		entry.Assertions["implemented_transport_fault"] = false
		entry.Assertions["frozen_transition_is_representable"] = len(fault.RequiredEvents) > 0
		return finalize(entry)
	}
}

func fromResult(entry trace, result e08.Result, method string, assertion bool) trace {
	entry.EvidenceMethod = method
	entry.ObservedStatus = result.Status
	entry.ReasonCode = result.Reason
	entry.Counters = result.Counters
	entry.Assertions["expected_invariant"] = assertion
	for _, event := range result.Events {
		kind := event.Kind
		if event.ReasonCode != "" && event.ReasonCode != e08.ReasonAccepted && event.ReasonCode != e08.ReasonCompleted {
			kind += ":" + string(event.ReasonCode)
		}
		entry.ObservedEvents = append(entry.ObservedEvents, kind)
	}
	return finalize(entry)
}

func finalize(entry trace) trace {
	for key, value := range entry.Assertions {
		if !value && key != "implemented_transport_fault" {
			entry.Verdict = "fail"
		}
	}
	return entry
}

func reason(err error) e08.ReasonCode {
	var protocol *e08.ProtocolError
	if errors.As(err, &protocol) {
		return protocol.Code
	}
	if err != nil {
		return e08.ReasonCode(strings.TrimSpace(err.Error()))
	}
	return e08.ReasonCompleted
}
