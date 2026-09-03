package integrityfaults

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
)

// ManifestSchemaVersion is the only manifest schema version this package
// accepts. Pre-Gate-1 formats carry no compatibility promise (roadmap
// section 2.6); a breaking change bumps this string.
const ManifestSchemaVersion = "t1-integrity-faults-manifest/v1"

// DeclaredOutput is one output a Manifest promises is restorable, and the
// content digest it must match - distinct from Manifest.Digest, which
// covers the entry's primary Content. This lets Lookup detect an output
// that is present but altered, independently of one that is missing
// entirely (the ticket's fault scenario names both: "resume with missing
// or altered output").
type DeclaredOutput struct {
	Name   string
	Digest string // sha256 hex of the expected output content
}

// Manifest mirrors the required_fields shape fixtures/w2/graph.json
// declares for an Artifact[T] manifest (digest, size_bytes,
// produced_by_node, produced_by_profile), plus SourceDigest and
// DeclaredOutputs. This is example data for THIS fixture, not the future
// production manifest schema.
type Manifest struct {
	SchemaVersion string

	Digest            string
	SizeBytes         int64
	ProducedByNode    string
	ProducedByProfile string

	// SourceDigest is the Snapshot.Digest of the source tree this entry
	// was produced from. It is what lets Lookup distinguish "an entry
	// that is internally well-formed under its own identity key" from "an
	// entry that is stale because the source has since moved on" (AC #3) -
	// a distinction a bare identity string cannot make on its own, since
	// nothing requires an identity scheme to fully encode source state
	// (and in practice, coarser cache keys often do not).
	SourceDigest string

	DeclaredOutputs []DeclaredOutput
}

// Entry is one stored cache entry: content plus its manifest, keyed by a
// caller-supplied identity string. This package does not compute or define
// that identity (roadmap section 9 E04's cache-identity question is not
// this ticket's to answer) - fault tests construct identities directly.
type Entry struct {
	Identity string
	Content  []byte
	Manifest Manifest

	// Outputs holds the actual bytes available for each declared output
	// name. A fault test can leave a name out of Outputs (simulating a
	// missing output) or include it with content that does not match its
	// DeclaredOutput.Digest (simulating an altered-but-present output).
	Outputs map[string][]byte
}

// Event is one step in a Lookup's ordered trail, tagged with the call it
// belongs to (CallID) so a test asserting "success never appears" or
// "reject is the last event" can scope its assertion to exactly one
// Lookup invocation, even when a test performs several lookups in
// sequence (AC #4: precise, per-lookup evidence).
type Event struct {
	CallID   int
	Kind     string
	Identity string
	Detail   string
}

// Event kinds.
//
// IMPORTANT, read before treating this fixture's ordering as evidence of
// anything about the future production cache: EventReserve is logged
// BEFORE any lookup/verify step. This is deliberately consistent with what
// TF-001.04 measured in the actual prototype today
// (docs/evidence/t0/cache-characterisation.md: reservation/acquisition
// precedes cache resolution). It is the OPPOSITE of what E04's required
// demonstration #5 asks a correct future implementation to achieve ("a
// cache hit performs zero provider reservations/acquisitions"). This
// fixture's reserve-then-lookup order is NOT proof of E04 success, is NOT
// a recommendation, and must not be read as either - it exists only so
// this toy store's ordering does not silently contradict T0's own measured
// facts. See README.md's "What this is NOT" section for the same warning
// in one place a reader is more likely to see first.
const (
	EventReserve            = "reserve"
	EventLookupStart        = "lookup-start"
	EventLookupHit          = "lookup-hit"
	EventLookupMiss         = "lookup-miss"
	EventVerifyStart        = "verify-start"
	EventVerifySchemaOK     = "verify-schema-ok"
	EventVerifySchemaFail   = "verify-schema-fail"
	EventVerifySourceOK     = "verify-source-ok"
	EventVerifySourceFail   = "verify-source-fail"
	EventVerifyContentOK    = "verify-content-ok"
	EventVerifyContentFail  = "verify-content-fail"
	EventVerifyManifestOK   = "verify-manifest-ok"
	EventVerifyManifestFail = "verify-manifest-fail"
	EventVerifyOutputMissed = "verify-output-missing"
	EventVerifyOutputAlter  = "verify-output-altered"
	EventReject             = "reject"
	EventSuccess            = "success"
)

var (
	// ErrManifestSchemaVersion is returned when a found entry's
	// Manifest.SchemaVersion does not equal ManifestSchemaVersion - the
	// package cannot safely interpret a manifest whose schema it does not
	// recognize, so this is checked before any other verification step.
	ErrManifestSchemaVersion = errors.New("manifest schema_version does not match the version this package accepts")
	// ErrStaleSource is returned when an entry is found under the
	// requested identity, but the source digest the caller says is
	// current does not match the source digest the entry was produced
	// from - the entry is stale relative to the source, independent of
	// whether its own stored bytes are internally consistent.
	ErrStaleSource = errors.New("entry was produced from a different source snapshot than the one currently declared")
	// ErrContentCorrupt is returned when stored content's own sha256 does
	// not match the digest its manifest declares.
	ErrContentCorrupt = errors.New("content digest does not match manifest digest")
	// ErrManifestCorrupt is returned when a manifest field other than the
	// content digest is inconsistent with the stored content - here,
	// size_bytes - independent of whether the content digest itself is
	// valid.
	ErrManifestCorrupt = errors.New("manifest size_bytes does not match actual content length")
	// ErrOutputMissing is returned when a manifest declares an output
	// that is not present in storage at all.
	ErrOutputMissing = errors.New("manifest declares an output that is not present in storage")
	// ErrOutputAltered is returned when a declared output IS present but
	// its content digest does not match what the manifest declared -
	// distinct from ErrOutputMissing.
	ErrOutputAltered = errors.New("a declared output is present but its content does not match the declared digest")
	// ErrMiss is returned when no entry exists for the requested identity
	// - a genuine cache miss, not a corruption or staleness finding.
	ErrMiss = errors.New("no entry for identity")
)

// Store is a toy, in-memory, single-process cache store - not a candidate
// production cache design (see README.md). Every Lookup appends to Events
// in the exact order steps occurred, tagged with a per-call CallID, so
// tests can assert ordering for one specific call directly rather than
// trusting a claim about it or scanning a log shared across calls.
type Store struct {
	entries map[string]Entry
	Events  []Event
	nextID  int
}

// NewStore returns an empty Store.
func NewStore() *Store {
	return &Store{entries: map[string]Entry{}}
}

func (s *Store) log(callID int, kind, identity, detail string) {
	s.Events = append(s.Events, Event{CallID: callID, Kind: kind, Identity: identity, Detail: detail})
}

// Put stores an entry exactly as given, including any deliberately
// corrupted content, manifest, source digest, or incomplete/altered
// Outputs a fault test constructs. Put performs no validation; only
// Lookup does, matching how a real cache accepts a write and validates on
// read.
func (s *Store) Put(e Entry) {
	s.entries[e.Identity] = e
}

// EventsForCall returns only the events logged during one specific Lookup
// call, identified by the callID Lookup returns.
func (s *Store) EventsForCall(callID int) []Event {
	var out []Event
	for _, e := range s.Events {
		if e.CallID == callID {
			out = append(out, e)
		}
	}
	return out
}

// Lookup reserves, looks up, and - only if an entry is found - independently
// verifies manifest schema version, source freshness, content integrity,
// manifest consistency, and declared-output presence/content, in that
// order, before ever logging or returning success. currentSourceDigest is
// the caller's current source
// Snapshot.Digest (or "" if the caller does not track source provenance,
// in which case the source-freshness check is skipped rather than
// spuriously failing every lookup). Any verification failure returns its
// specific error immediately; the EventReject entry it causes is always
// the last event Lookup logs for that call, and EventSuccess is never
// logged on a failing path (AC #3: "a stale or corrupt ready-cache entry
// is rejected before returning success").
//
// Lookup returns a callID alongside the usual (Entry, error) so a caller
// can scope assertions to exactly this call via EventsForCall.
func (s *Store) Lookup(identity, currentSourceDigest string) (Entry, int, error) {
	s.nextID++
	callID := s.nextID

	s.log(callID, EventReserve, identity, "")
	s.log(callID, EventLookupStart, identity, "")

	e, ok := s.entries[identity]
	if !ok {
		s.log(callID, EventLookupMiss, identity, "")
		return Entry{}, callID, ErrMiss
	}
	s.log(callID, EventLookupHit, identity, "")

	s.log(callID, EventVerifyStart, identity, "")

	if e.Manifest.SchemaVersion != ManifestSchemaVersion {
		detail := fmt.Sprintf("manifest schema_version %q != %q", e.Manifest.SchemaVersion, ManifestSchemaVersion)
		s.log(callID, EventVerifySchemaFail, identity, detail)
		s.log(callID, EventReject, identity, ErrManifestSchemaVersion.Error())
		return Entry{}, callID, ErrManifestSchemaVersion
	}
	s.log(callID, EventVerifySchemaOK, identity, "")

	if currentSourceDigest != "" && e.Manifest.SourceDigest != currentSourceDigest {
		detail := fmt.Sprintf("entry source digest %s != current source digest %s", e.Manifest.SourceDigest, currentSourceDigest)
		s.log(callID, EventVerifySourceFail, identity, detail)
		s.log(callID, EventReject, identity, ErrStaleSource.Error())
		return Entry{}, callID, ErrStaleSource
	}
	if currentSourceDigest != "" {
		s.log(callID, EventVerifySourceOK, identity, "")
	}

	sum := sha256.Sum256(e.Content)
	contentDigest := hex.EncodeToString(sum[:])
	if contentDigest != e.Manifest.Digest {
		detail := fmt.Sprintf("content digest %s != manifest digest %s", contentDigest, e.Manifest.Digest)
		s.log(callID, EventVerifyContentFail, identity, detail)
		s.log(callID, EventReject, identity, ErrContentCorrupt.Error())
		return Entry{}, callID, ErrContentCorrupt
	}
	s.log(callID, EventVerifyContentOK, identity, "")

	if e.Manifest.SizeBytes != int64(len(e.Content)) {
		detail := fmt.Sprintf("manifest size_bytes %d != actual content length %d", e.Manifest.SizeBytes, len(e.Content))
		s.log(callID, EventVerifyManifestFail, identity, detail)
		s.log(callID, EventReject, identity, ErrManifestCorrupt.Error())
		return Entry{}, callID, ErrManifestCorrupt
	}
	s.log(callID, EventVerifyManifestOK, identity, "")

	for _, declared := range e.Manifest.DeclaredOutputs {
		content, ok := e.Outputs[declared.Name]
		if !ok {
			detail := fmt.Sprintf("declared output %q not present in storage", declared.Name)
			s.log(callID, EventVerifyOutputMissed, identity, detail)
			s.log(callID, EventReject, identity, ErrOutputMissing.Error())
			return Entry{}, callID, ErrOutputMissing
		}
		sum := sha256.Sum256(content)
		gotDigest := hex.EncodeToString(sum[:])
		if gotDigest != declared.Digest {
			detail := fmt.Sprintf("declared output %q digest %s != actual content digest %s", declared.Name, declared.Digest, gotDigest)
			s.log(callID, EventVerifyOutputAlter, identity, detail)
			s.log(callID, EventReject, identity, ErrOutputAltered.Error())
			return Entry{}, callID, ErrOutputAltered
		}
	}

	s.log(callID, EventSuccess, identity, "")
	return e, callID, nil
}
