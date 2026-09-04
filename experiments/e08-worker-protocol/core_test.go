package e08

import (
	"context"
	"errors"
	"reflect"
	"testing"
	"time"
)

func requestFor(adapter Adapter, attempt string) Request {
	command := []string{"stub-command"}
	useSession := adapter.ID() == AdapterMacOSStub
	if adapter.ID() == AdapterInProcess {
		command = []string{"/bin/sh", "-c", "cat input/source.txt; printf ':built'"}
	}
	return Request{
		RunID: "run-e08", NodeID: "build", AttemptID: attempt,
		Profile: adapter.Profile(), Source: []byte("source-v1"), Command: command,
		UseSession: useSession, CacheVersion: "v1", ExpectedOutput: "stdout",
		CleanupDeadline: time.Second,
	}
}

func TestOneControllerDrivesInProcessAndMacOSStub(t *testing.T) {
	for _, adapter := range []Adapter{NewInProcessAdapter(AdapterConfig{}), NewMacOSStubAdapter(AdapterConfig{})} {
		t.Run(adapter.ID(), func(t *testing.T) {
			controller := NewController()
			result := controller.Run(context.Background(), adapter, requestFor(adapter, "attempt-1"))
			if result.Status != "succeeded" || result.Reason != ReasonCompleted || result.ArtifactDigest == "" {
				t.Fatalf("result = %#v", result)
			}
			if result.Counters.Reservations != 1 || result.Counters.WorkerAcquisitions != 1 || result.Counters.Attestations != 1 || result.Counters.Sandboxes != 1 || result.Counters.Executions != 1 || result.Counters.Publications != 1 || result.Counters.Cleanups != 1 || result.Counters.ReservationReleases != 1 {
				t.Fatalf("counters = %#v", result.Counters)
			}
			if adapter.ID() == AdapterMacOSStub && result.Counters.Sessions != 1 {
				t.Fatalf("macOS session count = %d", result.Counters.Sessions)
			}
			if adapter.ID() == AdapterInProcess && result.Counters.Sessions != 0 {
				t.Fatalf("stateless Linux-shaped local session count = %d", result.Counters.Sessions)
			}
		})
	}
}

func TestReadyCacheHitDoesNoCapacityWork(t *testing.T) {
	for _, adapter := range []Adapter{NewInProcessAdapter(AdapterConfig{}), NewMacOSStubAdapter(AdapterConfig{})} {
		t.Run(adapter.ID(), func(t *testing.T) {
			controller := NewController()
			request := requestFor(adapter, "attempt-prime")
			prime := controller.Run(context.Background(), adapter, request)
			if prime.Status != "succeeded" {
				t.Fatalf("prime status = %s", prime.Status)
			}
			request.AttemptID = "attempt-hit"
			hit := controller.Run(context.Background(), adapter, request)
			if hit.Status != "cache_hit" || !hit.Counters.AllZero() {
				t.Fatalf("hit = %#v", hit)
			}
			for _, event := range hit.Events {
				switch event.Kind {
				case "capacity_granted", "worker_attached", "profile_attested", "sandbox_created", "session_acquired", "execution_started", "outputs_published", "cleanup_started":
					t.Fatalf("capacity event on hit: %#v", event)
				}
			}
		})
	}
}

func TestTryReserveDoesNotAcquireDelayedWorker(t *testing.T) {
	for _, adapter := range []Adapter{NewInProcessAdapter(AdapterConfig{AcquireDelay: time.Second}), NewMacOSStubAdapter(AdapterConfig{AcquireDelay: time.Second})} {
		started := time.Now()
		reservation, err := adapter.TryReserve(context.Background(), adapter.Profile().Digest())
		if err != nil || reservation.Disposition != DispositionGranted {
			t.Fatalf("%s reservation = %#v, %v", adapter.ID(), reservation, err)
		}
		if elapsed := time.Since(started); elapsed > 100*time.Millisecond {
			t.Fatalf("%s TryReserve blocked for %s", adapter.ID(), elapsed)
		}
	}
}

func TestProfileMismatchFailsBeforeSandbox(t *testing.T) {
	for _, adapter := range []Adapter{NewInProcessAdapter(AdapterConfig{ProfileMismatch: true}), NewMacOSStubAdapter(AdapterConfig{ProfileMismatch: true})} {
		result := NewController().Run(context.Background(), adapter, requestFor(adapter, "attempt-mismatch"))
		if result.Reason != ReasonProfileMismatch || result.Counters.Sandboxes != 0 || result.Counters.Executions != 0 || result.Counters.Publications != 0 {
			t.Fatalf("result = %#v", result)
		}
	}
}

func TestCASRejectsCorruptionAndMissingObjects(t *testing.T) {
	cas := NewCAS()
	data := []byte("expected")
	if err := cas.Put(Digest(data), []byte("corrupt")); !hasReason(err, ReasonObjectDigestMismatch) {
		t.Fatalf("corrupt Put error = %v", err)
	}
	if err := cas.PutChunk(Digest(data), Digest([]byte("chunk")), []byte("corrupt"), false); !hasReason(err, ReasonChunkDigestMismatch) {
		t.Fatalf("corrupt PutChunk error = %v", err)
	}
	if _, err := cas.Get(Digest(data)); !hasReason(err, ReasonMissingBlob) {
		t.Fatalf("missing Get error = %v", err)
	}
}

func TestOperationReplayIsIdempotentAndConflictFailsClosed(t *testing.T) {
	store := NewOperationStore()
	calls := 0
	action := func() (any, error) { calls++; return "result", nil }
	first, err := store.Apply("op-1", "payload-a", action)
	if err != nil {
		t.Fatal(err)
	}
	second, err := store.Apply("op-1", "payload-a", action)
	if err != nil || first != second || calls != 1 {
		t.Fatalf("replay = %v %v calls=%d err=%v", first, second, calls, err)
	}
	if _, err := store.Apply("op-1", "payload-b", action); !hasReason(err, ReasonRevisionConflict) {
		t.Fatalf("conflict error = %v", err)
	}
}

func TestEventReplayUsesGapFreeCursor(t *testing.T) {
	log := &EventLog{}
	for _, kind := range []string{"one", "two", "three"} {
		log.Append(Event{Kind: kind})
	}
	replay := log.Replay(1)
	if got := []uint64{replay[0].Sequence, replay[1].Sequence}; !reflect.DeepEqual(got, []uint64{2, 3}) {
		t.Fatalf("replay sequences = %v", got)
	}
	if replay[0].Kind != "two" || replay[1].Kind != "three" {
		t.Fatalf("replay = %#v", replay)
	}
}

func TestReconnectRejectsStaleOwnershipAndReplaysRevision(t *testing.T) {
	request := requestFor(NewMacOSStubAdapter(AdapterConfig{}), "attempt-reconnect")
	log := &EventLog{}
	log.Append(Event{Kind: "one"})
	log.Append(Event{Kind: "two"})
	replay, err := Reconnect(log, request, ReconnectToken{RunID: request.RunID, NodeID: request.NodeID, AttemptID: request.AttemptID, Revision: 1})
	if err != nil || len(replay) != 1 || replay[0].Kind != "two" {
		t.Fatalf("reconnect = %#v, %v", replay, err)
	}
	if _, err := Reconnect(log, request, ReconnectToken{RunID: request.RunID, NodeID: request.NodeID, AttemptID: "stale"}); !hasReason(err, ReasonStaleReconnectToken) {
		t.Fatalf("stale reconnect error = %v", err)
	}
}

func TestLogReplayVerifiesCursorAndBytes(t *testing.T) {
	chunks := []LogChunk{{Cursor: 1, Bytes: []byte("a"), Digest: Digest([]byte("a"))}, {Cursor: 2, Bytes: []byte("b"), Digest: Digest([]byte("b"))}}
	replay, err := ReplayLogs(chunks, 1)
	if err != nil || len(replay) != 1 || replay[0].Cursor != 2 {
		t.Fatalf("log replay = %#v, %v", replay, err)
	}
	chunks[1].Bytes = []byte("changed")
	if _, err := ReplayLogs(chunks, 0); !hasReason(err, ReasonOutputIntegrity) {
		t.Fatalf("corrupt replay error = %v", err)
	}
}

func TestCancellationStopsExecutionAndCleanupIsDetached(t *testing.T) {
	adapter := NewInProcessAdapter(AdapterConfig{})
	controller := NewController()
	request := requestFor(adapter, "attempt-cancel")
	request.Command = []string{"/bin/sh", "-c", "sleep 5"}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	result := controller.Run(ctx, adapter, request)
	if result.Status != "cancelled" || result.Reason != ReasonCancelled || result.Counters.Cleanups != 1 || len(result.Orphans) != 0 {
		t.Fatalf("result = %#v", result)
	}
}

func TestCleanupTimeoutRecordsExactOrphan(t *testing.T) {
	adapter := NewMacOSStubAdapter(AdapterConfig{CleanupDelay: 100 * time.Millisecond})
	request := requestFor(adapter, "attempt-orphan")
	request.CleanupDeadline = time.Millisecond
	controller := NewController()
	result := controller.Run(context.Background(), adapter, request)
	if result.Status != "succeeded" || len(result.Orphans) != 1 {
		t.Fatalf("result = %#v", result)
	}
	orphan := result.Orphans[0]
	if orphan.Kind != "sandbox" || orphan.OwnershipID != "attempt-orphan:sandbox" {
		t.Fatalf("orphan = %#v", orphan)
	}
	if !controller.Orphans.Reconcile(orphan.Kind, orphan.OwnershipID) || len(controller.Orphans.Query()) != 0 {
		t.Fatal("exact orphan did not reconcile")
	}
}

func TestMacOSStubIsNonMutatingAndCarriesE06Identity(t *testing.T) {
	adapter := NewMacOSStubAdapter(AdapterConfig{})
	profile := adapter.Profile()
	if profile.OS != "macos" || profile.OSBuild != "25F84" || profile.Architecture != "arm64" || len(profile.Toolchains) != 3 {
		t.Fatalf("profile = %#v", profile)
	}
	worker, err := adapter.Acquire(context.Background(), Reservation{ID: "stub", Disposition: DispositionGranted, Profile: profile.Digest()})
	if err != nil {
		t.Fatal(err)
	}
	sandbox, err := worker.CreateSandbox(context.Background(), "stub-sandbox")
	if err != nil {
		t.Fatal(err)
	}
	stub, ok := sandbox.(*macOSStubSandbox)
	if !ok || stub.session != "" || stub.source != nil {
		t.Fatalf("stub unexpectedly touched external state: %#v", sandbox)
	}
}

func hasReason(err error, reason ReasonCode) bool {
	var protocol *ProtocolError
	return errors.As(err, &protocol) && protocol.Code == reason
}
