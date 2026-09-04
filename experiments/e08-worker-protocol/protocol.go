package e08

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"sync"
	"time"
)

const (
	AdapterInProcess = "in-process"
	AdapterMacOSStub = "macos-e06-stub"
)

type ReasonCode string

const (
	ReasonAccepted              ReasonCode = "accepted"
	ReasonCacheHit              ReasonCode = "cache-hit"
	ReasonCacheMiss             ReasonCode = "cache-miss"
	ReasonProfileMismatch       ReasonCode = "profile-mismatch"
	ReasonProviderUnavailable   ReasonCode = "provider-unavailable"
	ReasonMissingBlob           ReasonCode = "missing-blob"
	ReasonChunkDigestMismatch   ReasonCode = "chunk-digest-mismatch"
	ReasonObjectDigestMismatch  ReasonCode = "object-digest-mismatch"
	ReasonManifestTamper        ReasonCode = "manifest-tamper"
	ReasonTransportDisconnected ReasonCode = "transport-disconnected"
	ReasonWorkerLost            ReasonCode = "worker-lost"
	ReasonCancelled             ReasonCode = "cancelled"
	ReasonCommandExitNonzero    ReasonCode = "command-exit-nonzero"
	ReasonRevisionConflict      ReasonCode = "revision-conflict"
	ReasonStaleReconnectToken   ReasonCode = "stale-reconnect-token"
	ReasonOutputMissing         ReasonCode = "output-missing"
	ReasonOutputPathEscape      ReasonCode = "output-path-escape"
	ReasonOutputIntegrity       ReasonCode = "output-integrity-failed"
	ReasonPublicationConflict   ReasonCode = "publication-conflict"
	ReasonPublicationIO         ReasonCode = "publication-io-failed"
	ReasonCleanupTimeout        ReasonCode = "cleanup-timeout"
	ReasonCallerLost            ReasonCode = "caller-lost"
	ReasonOrphanConfirmed       ReasonCode = "orphan-confirmed"
	ReasonOrphanUnknown         ReasonCode = "orphan-unknown"
	ReasonCompleted             ReasonCode = "completed"
)

type Event struct {
	Sequence      uint64            `json:"sequence"`
	Revision      uint64            `json:"revision"`
	Adapter       string            `json:"adapter"`
	RunID         string            `json:"run_id"`
	NodeID        string            `json:"node_id"`
	AttemptID     string            `json:"attempt_id"`
	OperationID   string            `json:"operation_id"`
	Machine       string            `json:"machine"`
	Kind          string            `json:"kind"`
	PriorState    string            `json:"prior_state,omitempty"`
	State         string            `json:"state,omitempty"`
	ReasonCode    ReasonCode        `json:"reason_code"`
	ProfileDigest string            `json:"profile_digest,omitempty"`
	ObjectDigest  string            `json:"object_digest,omitempty"`
	LogCursor     uint64            `json:"log_cursor,omitempty"`
	OwnershipID   string            `json:"ownership_id,omitempty"`
	Details       map[string]string `json:"details,omitempty"`
}

type EventLog struct {
	mu       sync.Mutex
	revision uint64
	events   []Event
}

func (l *EventLog) Append(event Event) Event {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.revision++
	event.Sequence = uint64(len(l.events) + 1)
	event.Revision = l.revision
	l.events = append(l.events, event)
	return event
}

func (l *EventLog) Replay(after uint64) []Event {
	l.mu.Lock()
	defer l.mu.Unlock()
	if after >= uint64(len(l.events)) {
		return nil
	}
	return append([]Event(nil), l.events[after:]...)
}

func (l *EventLog) Events() []Event { return l.Replay(0) }

type Profile struct {
	MechanismID           string   `json:"mechanism_id"`
	MechanismVersion      string   `json:"mechanism_version"`
	BaseImageDigest       string   `json:"base_image_digest"`
	OS                    string   `json:"os"`
	OSBuild               string   `json:"os_build"`
	Architecture          string   `json:"architecture"`
	Toolchains            []string `json:"toolchains"`
	RunnerDigest          string   `json:"runner_digest"`
	SandboxPolicyDigest   string   `json:"sandbox_policy_digest"`
	ResetPolicyDigest     string   `json:"reset_policy_digest"`
	RequiredWorkerFeature []string `json:"required_worker_features"`
}

func (p Profile) Digest() string {
	data, err := json.Marshal(p)
	if err != nil {
		panic(err)
	}
	return Digest(data)
}

func Digest(data []byte) string {
	sum := sha256.Sum256(data)
	return "sha256:" + hex.EncodeToString(sum[:])
}

type Disposition string

const (
	DispositionGranted     Disposition = "granted"
	DispositionQueued      Disposition = "queued"
	DispositionMismatch    Disposition = "mismatch"
	DispositionUnavailable Disposition = "unavailable"
)

type Reservation struct {
	ID          string      `json:"reservation_id"`
	Disposition Disposition `json:"disposition"`
	Profile     string      `json:"profile_digest"`
}

type Counters struct {
	Reservations        int `json:"reservation"`
	WorkerWakes         int `json:"worker_wake"`
	WorkerAcquisitions  int `json:"worker_acquisition"`
	Attestations        int `json:"attestation"`
	Sandboxes           int `json:"sandbox"`
	Sessions            int `json:"session"`
	Executions          int `json:"execution"`
	Publications        int `json:"publication"`
	Cleanups            int `json:"cleanup"`
	ReservationReleases int `json:"reservation_release"`
}

func (c Counters) AllZero() bool {
	return c == (Counters{})
}

type LogChunk struct {
	Cursor uint64 `json:"cursor"`
	Stream string `json:"stream"`
	Digest string `json:"bytes_digest"`
	Bytes  []byte `json:"-"`
}

type ExecutionResult struct {
	ExitCode int
	Output   []byte
	Logs     []LogChunk
	Reason   ReasonCode
}

type Request struct {
	RunID           string
	NodeID          string
	AttemptID       string
	Profile         Profile
	Source          []byte
	Command         []string
	UseSession      bool
	CacheVersion    string
	ExpectedOutput  string
	CleanupDeadline time.Duration
}

// ReconnectToken is deliberately semantic rather than transport-specific.
// Its encoding and authentication are outside this experiment.
type ReconnectToken struct {
	RunID     string `json:"run_id"`
	NodeID    string `json:"node_id"`
	AttemptID string `json:"attempt_id"`
	Revision  uint64 `json:"last_durable_revision"`
	LogCursor uint64 `json:"last_acknowledged_log_cursor"`
}

type Result struct {
	Status         string     `json:"status"`
	Reason         ReasonCode `json:"reason_code"`
	CacheKey       string     `json:"cache_key"`
	ProfileDigest  string     `json:"profile_digest"`
	ArtifactDigest string     `json:"artifact_digest,omitempty"`
	Counters       Counters   `json:"counters"`
	Events         []Event    `json:"events"`
	Logs           []LogChunk `json:"logs,omitempty"`
	Orphans        []Orphan   `json:"orphans,omitempty"`
}

type Orphan struct {
	Kind        string `json:"kind"`
	OwnershipID string `json:"ownership_id"`
	Reason      string `json:"reason"`
}

type ProtocolError struct {
	Code ReasonCode
	Op   string
	Err  error
}

func (e *ProtocolError) Error() string {
	if e.Err == nil {
		return fmt.Sprintf("%s: %s", e.Op, e.Code)
	}
	return fmt.Sprintf("%s: %s: %v", e.Op, e.Code, e.Err)
}

func (e *ProtocolError) Unwrap() error { return e.Err }
