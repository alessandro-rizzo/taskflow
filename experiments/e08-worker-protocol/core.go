package e08

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"sync"
	"time"
)

type CAS struct {
	mu      sync.Mutex
	objects map[string][]byte
}

func NewCAS() *CAS { return &CAS{objects: make(map[string][]byte)} }

func (c *CAS) Put(expected string, data []byte) error {
	actual := Digest(data)
	if actual != expected {
		return &ProtocolError{Code: ReasonObjectDigestMismatch, Op: "CAS.Put", Err: fmt.Errorf("expected %s, got %s", expected, actual)}
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if prior, ok := c.objects[expected]; ok && Digest(prior) != expected {
		return &ProtocolError{Code: ReasonManifestTamper, Op: "CAS.Put"}
	}
	c.objects[expected] = append([]byte(nil), data...)
	return nil
}

func (c *CAS) PutChunk(objectDigest, chunkDigest string, data []byte, final bool) error {
	if Digest(data) != chunkDigest {
		return &ProtocolError{Code: ReasonChunkDigestMismatch, Op: "CAS.PutChunk"}
	}
	if final && Digest(data) != objectDigest {
		return &ProtocolError{Code: ReasonObjectDigestMismatch, Op: "CAS.PutChunk"}
	}
	if final {
		return c.Put(objectDigest, data)
	}
	return nil
}

func (c *CAS) Get(digest string) ([]byte, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	data, ok := c.objects[digest]
	if !ok {
		return nil, &ProtocolError{Code: ReasonMissingBlob, Op: "CAS.Get"}
	}
	if Digest(data) != digest {
		return nil, &ProtocolError{Code: ReasonManifestTamper, Op: "CAS.Get"}
	}
	return append([]byte(nil), data...), nil
}

type PublishedResult struct {
	CacheKey       string `json:"cache_key"`
	ArtifactDigest string `json:"artifact_digest"`
	ProfileDigest  string `json:"profile_digest"`
	SourceDigest   string `json:"source_digest"`
}

type ResultCache struct {
	mu      sync.Mutex
	results map[string]PublishedResult
}

func NewResultCache() *ResultCache { return &ResultCache{results: make(map[string]PublishedResult)} }

func (c *ResultCache) Lookup(key string, cas *CAS) (PublishedResult, bool) {
	c.mu.Lock()
	result, ok := c.results[key]
	c.mu.Unlock()
	if !ok {
		return PublishedResult{}, false
	}
	if _, err := cas.Get(result.ArtifactDigest); err != nil {
		return PublishedResult{}, false
	}
	return result, true
}

func (c *ResultCache) Publish(result PublishedResult) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if prior, exists := c.results[result.CacheKey]; exists {
		if prior == result {
			return nil
		}
		return &ProtocolError{Code: ReasonPublicationConflict, Op: "ResultCache.Publish"}
	}
	c.results[result.CacheKey] = result
	return nil
}

type OperationStore struct {
	mu      sync.Mutex
	results map[string]operationRecord
}

type operationRecord struct {
	PayloadDigest string
	Value         any
}

func NewOperationStore() *OperationStore {
	return &OperationStore{results: make(map[string]operationRecord)}
}

func (s *OperationStore) Apply(operationID, payloadDigest string, action func() (any, error)) (any, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if prior, ok := s.results[operationID]; ok {
		if prior.PayloadDigest != payloadDigest {
			return nil, &ProtocolError{Code: ReasonRevisionConflict, Op: operationID}
		}
		return prior.Value, nil
	}
	value, err := action()
	if err != nil {
		return nil, err
	}
	s.results[operationID] = operationRecord{PayloadDigest: payloadDigest, Value: value}
	return value, nil
}

type OrphanRegistry struct {
	mu      sync.Mutex
	orphans map[string]Orphan
}

func NewOrphanRegistry() *OrphanRegistry { return &OrphanRegistry{orphans: make(map[string]Orphan)} }

func (r *OrphanRegistry) Record(orphan Orphan) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.orphans[orphan.Kind+":"+orphan.OwnershipID] = orphan
}

func (r *OrphanRegistry) Query() []Orphan {
	r.mu.Lock()
	defer r.mu.Unlock()
	result := make([]Orphan, 0, len(r.orphans))
	for _, orphan := range r.orphans {
		result = append(result, orphan)
	}
	sort.Slice(result, func(i, j int) bool {
		if result[i].Kind == result[j].Kind {
			return result[i].OwnershipID < result[j].OwnershipID
		}
		return result[i].Kind < result[j].Kind
	})
	return result
}

func (r *OrphanRegistry) Reconcile(kind, ownershipID string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	key := kind + ":" + ownershipID
	if _, ok := r.orphans[key]; !ok {
		return false
	}
	delete(r.orphans, key)
	return true
}

type Adapter interface {
	ID() string
	Profile() Profile
	TryReserve(context.Context, string) (Reservation, error)
	Acquire(context.Context, Reservation) (Worker, error)
	ReleaseReservation(context.Context, Reservation) error
}

type Worker interface {
	ID() string
	Attest(context.Context, string) (string, error)
	CreateSandbox(context.Context, string) (Sandbox, error)
}

type Sandbox interface {
	ID() string
	Materialize(context.Context, string, []byte) error
	AcquireSession(context.Context, string) (string, error)
	Exec(context.Context, []string) (ExecutionResult, error)
	Cleanup(context.Context) error
}

type Controller struct {
	CAS        *CAS
	Cache      *ResultCache
	Operations *OperationStore
	Orphans    *OrphanRegistry
}

func NewController() *Controller {
	return &Controller{
		CAS:        NewCAS(),
		Cache:      NewResultCache(),
		Operations: NewOperationStore(),
		Orphans:    NewOrphanRegistry(),
	}
}

// PrimeVerifiedResult is test-harness preparation: it installs immutable
// verified bytes under the same semantic result identity used by Run.
func (c *Controller) PrimeVerifiedResult(request Request, output []byte) error {
	artifactDigest := Digest(output)
	if err := c.CAS.Put(artifactDigest, output); err != nil {
		return err
	}
	return c.Cache.Publish(PublishedResult{
		CacheKey:       CacheKey(request),
		ArtifactDigest: artifactDigest,
		ProfileDigest:  request.Profile.Digest(),
		SourceDigest:   Digest(request.Source),
	})
}

func CacheKey(request Request) string {
	identity := struct {
		Schema       string   `json:"schema"`
		RunNode      string   `json:"run_node"`
		Profile      string   `json:"profile"`
		Source       string   `json:"source"`
		Command      []string `json:"command"`
		Session      bool     `json:"session"`
		CacheVersion string   `json:"cache_version"`
	}{
		Schema:       "taskflow-e08-result-key/v1-experimental",
		RunNode:      request.NodeID,
		Profile:      request.Profile.Digest(),
		Source:       Digest(request.Source),
		Command:      append([]string(nil), request.Command...),
		Session:      request.UseSession,
		CacheVersion: request.CacheVersion,
	}
	encoded, err := json.Marshal(identity)
	if err != nil {
		panic(err)
	}
	return Digest(encoded)
}

func (c *Controller) Run(ctx context.Context, adapter Adapter, request Request) Result {
	if request.CleanupDeadline <= 0 {
		request.CleanupDeadline = 30 * time.Second
	}
	log := &EventLog{}
	counters := Counters{}
	profileDigest := request.Profile.Digest()
	cacheKey := CacheKey(request)
	emit := func(machine, kind, prior, state string, reason ReasonCode, ownership string) {
		log.Append(Event{
			Adapter: adapter.ID(), RunID: request.RunID, NodeID: request.NodeID,
			AttemptID: request.AttemptID, OperationID: request.AttemptID + ":" + kind,
			Machine: machine, Kind: kind, PriorState: prior, State: state,
			ReasonCode: reason, ProfileDigest: profileDigest, OwnershipID: ownership,
		})
	}
	emit("node-attempt", "cache_lookup_started", "ready", "cache_lookup", ReasonAccepted, "")
	if cached, ok := c.Cache.Lookup(cacheKey, c.CAS); ok {
		emit("node-attempt", "verified_result_found", "cache_lookup", "cache_hit", ReasonCacheHit, "")
		emit("node-attempt", "artifact_handles_returned", "cache_hit", "cache_hit", ReasonCacheHit, "")
		return Result{Status: "cache_hit", Reason: ReasonCacheHit, CacheKey: cacheKey, ProfileDigest: profileDigest, ArtifactDigest: cached.ArtifactDigest, Counters: counters, Events: log.Events()}
	}
	emit("node-attempt", "result_absent_or_invalid", "cache_lookup", "reservation_requested", ReasonCacheMiss, "")
	if err := ctx.Err(); err != nil {
		emit("node-attempt", "cancel_requested", "reservation_requested", "cancelling", ReasonCancelled, "")
		emit("node-attempt", "cancellation_acknowledged", "cancelling", "cancelled", ReasonCancelled, "")
		emit("reservation", "reservation_released", "requested", "released", ReasonCancelled, "")
		return Result{Status: "cancelled", Reason: ReasonCancelled, CacheKey: cacheKey, ProfileDigest: profileDigest, Counters: counters, Events: log.Events()}
	}

	counters.Reservations++
	reservation, err := adapter.TryReserve(ctx, profileDigest)
	if err != nil || reservation.Disposition != DispositionGranted {
		reason := ReasonProviderUnavailable
		if reservation.Disposition == DispositionMismatch {
			reason = ReasonProfileMismatch
		}
		emit("node-attempt", "placement_failed", "reservation_requested", "failed", reason, reservation.ID)
		return Result{Status: "failed", Reason: reason, CacheKey: cacheKey, ProfileDigest: profileDigest, Counters: counters, Events: log.Events()}
	}
	emit("reservation", "capacity_granted", "requested", "granted", ReasonAccepted, reservation.ID)

	counters.WorkerAcquisitions++
	worker, err := adapter.Acquire(ctx, reservation)
	if err != nil {
		reason := ReasonWorkerLost
		kind := "worker_declared_lost"
		state := "lost"
		if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
			reason = ReasonCancelled
			kind = "cancellation_acknowledged"
			state = "cancelled"
		}
		emit("node-attempt", kind, "reserved", state, reason, reservation.ID)
		return c.finishWithCleanup(request, adapter, reservation, nil, log, counters, cacheKey, profileDigest, reason)
	}
	emit("node-attempt", "worker_attached", "reserved", "worker_acquired", ReasonAccepted, worker.ID())

	counters.Attestations++
	attested, err := worker.Attest(ctx, profileDigest)
	if err != nil || attested != profileDigest {
		emit("worker-attachment", "attestation_mismatch", "attached", "quarantined", ReasonProfileMismatch, worker.ID())
		return c.finishWithCleanup(request, adapter, reservation, nil, log, counters, cacheKey, profileDigest, ReasonProfileMismatch)
	}
	emit("node-attempt", "profile_attested", "worker_acquired", "attested", ReasonAccepted, worker.ID())

	counters.Sandboxes++
	sandbox, err := worker.CreateSandbox(ctx, request.AttemptID+":sandbox")
	if err != nil {
		emit("node-attempt", "sandbox_create_failed", "attested", "failed", ReasonProviderUnavailable, worker.ID())
		return c.finishWithCleanup(request, adapter, reservation, nil, log, counters, cacheKey, profileDigest, ReasonProviderUnavailable)
	}
	emit("node-attempt", "sandbox_created", "attested", "sandbox_created", ReasonAccepted, sandbox.ID())

	if request.UseSession {
		counters.Sessions++
		sessionID, sessionErr := sandbox.AcquireSession(ctx, request.AttemptID+":session")
		if sessionErr != nil {
			emit("session", "session_acquire_failed", "acquiring", "lost", ReasonProviderUnavailable, request.AttemptID+":session")
			return c.finishWithCleanup(request, adapter, reservation, sandbox, log, counters, cacheKey, profileDigest, ReasonProviderUnavailable)
		}
		emit("node-attempt", "session_acquired", "sandbox_created", "session_acquired", ReasonAccepted, sessionID)
	}

	sourceDigest := Digest(request.Source)
	if err := c.CAS.Put(sourceDigest, request.Source); err != nil {
		emit("node-attempt", "materialization_failed", "sandbox_created", "failed", ReasonObjectDigestMismatch, sandbox.ID())
		return c.finishWithCleanup(request, adapter, reservation, sandbox, log, counters, cacheKey, profileDigest, ReasonObjectDigestMismatch)
	}
	verified, err := c.CAS.Get(sourceDigest)
	if err != nil {
		emit("node-attempt", "materialization_failed", "materializing", "failed", reasonOf(err), sandbox.ID())
		return c.finishWithCleanup(request, adapter, reservation, sandbox, log, counters, cacheKey, profileDigest, reasonOf(err))
	}
	if err := sandbox.Materialize(ctx, sourceDigest, verified); err != nil {
		emit("node-attempt", "materialization_failed", "materializing", "failed", reasonOf(err), sandbox.ID())
		return c.finishWithCleanup(request, adapter, reservation, sandbox, log, counters, cacheKey, profileDigest, reasonOf(err))
	}
	emit("node-attempt", "inputs_verified", "materializing", "inputs_materialized", ReasonAccepted, sandbox.ID())

	counters.Executions++
	emit("node-attempt", "execution_started", "inputs_materialized", "executing", ReasonAccepted, sandbox.ID())
	execution, err := sandbox.Exec(ctx, request.Command)
	if err != nil {
		reason := reasonOf(err)
		emit("node-attempt", "exit_failed", "executing", "failed", reason, sandbox.ID())
		result := c.finishWithCleanup(request, adapter, reservation, sandbox, log, counters, cacheKey, profileDigest, reason)
		result.Logs = execution.Logs
		return result
	}
	emit("node-attempt", "exit_succeeded", "executing", "publishing", ReasonCompleted, sandbox.ID())

	artifactDigest := Digest(execution.Output)
	if err := c.CAS.Put(artifactDigest, execution.Output); err != nil {
		emit("publication", "output_integrity_failed", "verifying", "rejected", reasonOf(err), sandbox.ID())
		return c.finishWithCleanup(request, adapter, reservation, sandbox, log, counters, cacheKey, profileDigest, reasonOf(err))
	}
	counters.Publications++
	published := PublishedResult{CacheKey: cacheKey, ArtifactDigest: artifactDigest, ProfileDigest: profileDigest, SourceDigest: sourceDigest}
	if err := c.Cache.Publish(published); err != nil {
		emit("publication", "publication_failed", "publishing", "rejected", reasonOf(err), sandbox.ID())
		return c.finishWithCleanup(request, adapter, reservation, sandbox, log, counters, cacheKey, profileDigest, reasonOf(err))
	}
	emit("node-attempt", "outputs_published", "publishing", "succeeded", ReasonCompleted, sandbox.ID())
	result := c.finishWithCleanup(request, adapter, reservation, sandbox, log, counters, cacheKey, profileDigest, ReasonCompleted)
	result.Status = "succeeded"
	result.ArtifactDigest = artifactDigest
	result.Logs = execution.Logs
	return result
}

func (c *Controller) finishWithCleanup(request Request, adapter Adapter, reservation Reservation, sandbox Sandbox, log *EventLog, counters Counters, cacheKey, profileDigest string, reason ReasonCode) Result {
	status := "failed"
	if reason == ReasonCancelled {
		status = "cancelled"
	}
	if reason == ReasonCompleted {
		status = "succeeded"
	}
	counters.Cleanups++
	prior := status
	ownershipID := reservation.ID
	if sandbox != nil {
		ownershipID = sandbox.ID()
	}
	log.Append(Event{Adapter: adapter.ID(), RunID: request.RunID, NodeID: request.NodeID, AttemptID: request.AttemptID, OperationID: request.AttemptID + ":cleanup", Machine: "node-attempt", Kind: "cleanup_started", PriorState: prior, State: "cleaning", ReasonCode: reason, ProfileDigest: profileDigest, OwnershipID: ownershipID})
	cleanupCtx, cancel := context.WithTimeout(context.WithoutCancel(context.Background()), request.CleanupDeadline)
	defer cancel()
	if sandbox != nil {
		if err := sandbox.Cleanup(cleanupCtx); err != nil {
			orphan := Orphan{Kind: "sandbox", OwnershipID: sandbox.ID(), Reason: ReasonCleanupTimeout.String()}
			c.Orphans.Record(orphan)
			log.Append(Event{Adapter: adapter.ID(), RunID: request.RunID, NodeID: request.NodeID, AttemptID: request.AttemptID, OperationID: request.AttemptID + ":cleanup-timeout", Machine: "node-attempt", Kind: "cleanup_deadline_exceeded", PriorState: "cleaning", State: "cleanup_warning", ReasonCode: ReasonCleanupTimeout, ProfileDigest: profileDigest, OwnershipID: sandbox.ID()})
			log.Append(Event{Adapter: adapter.ID(), RunID: request.RunID, NodeID: request.NodeID, AttemptID: request.AttemptID, OperationID: request.AttemptID + ":orphan", Machine: "node-attempt", Kind: "orphan_recorded", PriorState: "cleanup_warning", State: "orphaned", ReasonCode: ReasonOrphanConfirmed, ProfileDigest: profileDigest, OwnershipID: sandbox.ID()})
		} else {
			log.Append(Event{Adapter: adapter.ID(), RunID: request.RunID, NodeID: request.NodeID, AttemptID: request.AttemptID, OperationID: request.AttemptID + ":sandbox-released", Machine: "sandbox", Kind: "resources_released", PriorState: "cleaning", State: "released", ReasonCode: ReasonCompleted, ProfileDigest: profileDigest, OwnershipID: sandbox.ID(), Details: map[string]string{"resource_kind": "sandbox"}})
		}
	}
	counters.ReservationReleases++
	if err := adapter.ReleaseReservation(cleanupCtx, reservation); err != nil {
		orphan := Orphan{Kind: "reservation", OwnershipID: reservation.ID, Reason: ReasonCleanupTimeout.String()}
		c.Orphans.Record(orphan)
		log.Append(Event{Adapter: adapter.ID(), RunID: request.RunID, NodeID: request.NodeID, AttemptID: request.AttemptID, OperationID: request.AttemptID + ":reservation-orphan", Machine: "reservation", Kind: "orphan_recorded", PriorState: "releasing", State: "orphaned", ReasonCode: ReasonOrphanConfirmed, ProfileDigest: profileDigest, OwnershipID: reservation.ID})
	} else {
		log.Append(Event{Adapter: adapter.ID(), RunID: request.RunID, NodeID: request.NodeID, AttemptID: request.AttemptID, OperationID: request.AttemptID + ":reservation-released", Machine: "reservation", Kind: "reservation_released", PriorState: "granted", State: "released", ReasonCode: ReasonCompleted, ProfileDigest: profileDigest, OwnershipID: reservation.ID, Details: map[string]string{"resource_kind": "reservation"}})
	}
	return Result{Status: status, Reason: reason, CacheKey: cacheKey, ProfileDigest: profileDigest, Counters: counters, Events: log.Events(), Orphans: c.Orphans.Query()}
}

// Reconnect validates semantic ownership and replays only durable events after
// the caller's last revision. It deliberately says nothing about wire framing.
func Reconnect(log *EventLog, request Request, token ReconnectToken) ([]Event, error) {
	if token.RunID != request.RunID || token.NodeID != request.NodeID || token.AttemptID != request.AttemptID {
		return nil, &ProtocolError{Code: ReasonStaleReconnectToken, Op: "Reconnect"}
	}
	return log.Replay(token.Revision), nil
}

func ReplayLogs(logs []LogChunk, after uint64) ([]LogChunk, error) {
	result := make([]LogChunk, 0, len(logs))
	for _, chunk := range logs {
		if chunk.Cursor == 0 || Digest(chunk.Bytes) != chunk.Digest {
			return nil, &ProtocolError{Code: ReasonOutputIntegrity, Op: "ReadLogs"}
		}
		if chunk.Cursor > after {
			if len(result) > 0 && chunk.Cursor != result[len(result)-1].Cursor+1 {
				return nil, &ProtocolError{Code: ReasonRevisionConflict, Op: "ReadLogs"}
			}
			result = append(result, chunk)
		}
	}
	return result, nil
}

func reasonOf(err error) ReasonCode {
	if err == nil {
		return ReasonCompleted
	}
	var protocol *ProtocolError
	if errors.As(err, &protocol) {
		return protocol.Code
	}
	if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		return ReasonCancelled
	}
	return ReasonCommandExitNonzero
}

func (r ReasonCode) String() string { return string(r) }
