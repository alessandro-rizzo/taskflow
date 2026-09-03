package integrityfaults

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func digestOf(content []byte) string {
	sum := sha256.Sum256(content)
	return hex.EncodeToString(sum[:])
}

// validEntry builds an Entry whose Manifest (including DeclaredOutput
// digests) is computed correctly from content/outputs, so tests start from
// a genuinely valid baseline and corrupt exactly one dimension at a time.
// sourceDigest may be "" for tests that do not care about source
// provenance.
func validEntry(identity string, content []byte, sourceDigest string, outputs map[string][]byte, declaredNames []string) Entry {
	declared := make([]DeclaredOutput, 0, len(declaredNames))
	for _, name := range declaredNames {
		declared = append(declared, DeclaredOutput{Name: name, Digest: digestOf(outputs[name])})
	}
	return Entry{
		Identity: identity,
		Content:  content,
		Manifest: Manifest{
			SchemaVersion:     ManifestSchemaVersion,
			Digest:            digestOf(content),
			SizeBytes:         int64(len(content)),
			ProducedByNode:    "build",
			ProducedByProfile: "linux-go1.25-amd64-example",
			SourceDigest:      sourceDigest,
			DeclaredOutputs:   declared,
		},
		Outputs: outputs,
	}
}

func lastEventKind(events []Event) string {
	if len(events) == 0 {
		return ""
	}
	return events[len(events)-1].Kind
}

func containsEventKind(events []Event, kind string) bool {
	for _, e := range events {
		if e.Kind == kind {
			return true
		}
	}
	return false
}

func TestLookupSucceedsOnValidEntry(t *testing.T) {
	s := NewStore()
	s.Put(validEntry("id-1", []byte("hello"), "", map[string][]byte{"out": []byte("x")}, []string{"out"}))

	e, callID, err := s.Lookup("id-1", "")
	if err != nil {
		t.Fatalf("expected success, got: %v", err)
	}
	if string(e.Content) != "hello" {
		t.Fatalf("unexpected content: %q", e.Content)
	}
	events := s.EventsForCall(callID)
	if containsEventKind(events, EventReject) {
		t.Fatalf("valid entry logged a reject event: %+v", events)
	}
	if lastEventKind(events) != EventSuccess {
		t.Fatalf("expected the last event to be %q, got %q (%+v)", EventSuccess, lastEventKind(events), events)
	}
}

func TestLookupMissLogsNoVerificationEvents(t *testing.T) {
	s := NewStore()
	_, callID, err := s.Lookup("does-not-exist", "")
	if !errors.Is(err, ErrMiss) {
		t.Fatalf("expected ErrMiss, got: %v", err)
	}
	events := s.EventsForCall(callID)
	for _, kind := range []string{EventVerifyStart, EventVerifyContentOK, EventVerifyManifestOK, EventSuccess} {
		if containsEventKind(events, kind) {
			t.Fatalf("a genuine miss must not attempt verification; found event %q in %+v", kind, events)
		}
	}
	if lastEventKind(events) != EventLookupMiss {
		t.Fatalf("expected last event %q, got %q", EventLookupMiss, lastEventKind(events))
	}
}

// TestLookupRejectsUnrecognizedManifestSchemaVersion demonstrates that
// ManifestSchemaVersion is actually enforced, not just documented. An
// independent Opus review of the Codex-review fixes found the doc comment
// claimed this package "accepts" only ManifestSchemaVersion while nothing
// in Lookup actually checked it - a probe entry with a bogus schema
// version looked up successfully. Fixed by adding a real check, verified
// here.
func TestLookupRejectsUnrecognizedManifestSchemaVersion(t *testing.T) {
	s := NewStore()
	e := validEntry("id-schema-mismatch", []byte("content"), "", nil, nil)
	e.Manifest.SchemaVersion = "totally-bogus/v99"
	s.Put(e)

	_, callID, err := s.Lookup("id-schema-mismatch", "")
	if !errors.Is(err, ErrManifestSchemaVersion) {
		t.Fatalf("expected ErrManifestSchemaVersion, got: %v", err)
	}
	assertRejectedBeforeSuccess(t, s.EventsForCall(callID), EventVerifySchemaFail)
}

// TestLookupDetectsCorruptContentIndependentlyOfManifest demonstrates AC #1's
// first leg: artifact content corruption is detected even though the
// manifest (built from the ORIGINAL content) is otherwise internally
// consistent in every other field.
func TestLookupDetectsCorruptContentIndependentlyOfManifest(t *testing.T) {
	s := NewStore()
	e := validEntry("id-content-corrupt", []byte("original content"), "", nil, nil)
	// Corrupt one byte of the stored content IN PLACE (same length),
	// exactly as if storage silently returned bit-flipped bytes of
	// identical size - so size_bytes still matches len(Content) and the
	// manifest check alone cannot catch this; only the content-digest
	// check can. This isolation matters: an earlier version of this test
	// corrupted content with a different length, which happened to also
	// trip the manifest size check and made this test pass even with the
	// content check disabled - caught by deliberately disabling the
	// content check and confirming this test failed for the wrong reason.
	corrupted := []byte("original content")
	corrupted[0] = 'X'
	e.Content = corrupted
	s.Put(e)

	_, callID, err := s.Lookup("id-content-corrupt", "")
	if !errors.Is(err, ErrContentCorrupt) {
		t.Fatalf("expected ErrContentCorrupt, got: %v", err)
	}
	assertRejectedBeforeSuccess(t, s.EventsForCall(callID), EventVerifyContentFail)
}

// TestLookupDetectsCorruptManifestIndependentlyOfContent demonstrates AC #1's
// second leg: manifest metadata corruption (size_bytes, here) is detected
// even though the stored content bytes exactly match the manifest's own
// content digest.
func TestLookupDetectsCorruptManifestIndependentlyOfContent(t *testing.T) {
	s := NewStore()
	e := validEntry("id-manifest-corrupt", []byte("unmodified content"), "", nil, nil)
	// Content and its digest are untouched; only a manifest field
	// (size_bytes) is wrong, as if the manifest record was corrupted or
	// hand-edited independently of the content it describes.
	e.Manifest.SizeBytes += 1000
	s.Put(e)

	_, callID, err := s.Lookup("id-manifest-corrupt", "")
	if !errors.Is(err, ErrManifestCorrupt) {
		t.Fatalf("expected ErrManifestCorrupt, got: %v", err)
	}
	events := s.EventsForCall(callID)
	assertRejectedBeforeSuccess(t, events, EventVerifyManifestFail)
	if containsEventKind(events, EventVerifyContentFail) {
		t.Fatalf("manifest-only corruption must not also report a content failure: %+v", events)
	}
}

// TestLookupDetectsMissingDeclaredOutput demonstrates AC #1's third leg
// (resume output presence): a manifest that declares an output the store
// does not actually have must be rejected, even though the primary
// content/manifest are both valid - the "resume with missing output" case.
func TestLookupDetectsMissingDeclaredOutput(t *testing.T) {
	s := NewStore()
	e := validEntry("id-missing-output", []byte("valid content"), "",
		map[string][]byte{"report.json": []byte("{}")}, // coverage.html deliberately absent from Outputs
		[]string{"report.json", "coverage.html"},
	)
	s.Put(e)

	_, callID, err := s.Lookup("id-missing-output", "")
	if !errors.Is(err, ErrOutputMissing) {
		t.Fatalf("expected ErrOutputMissing, got: %v", err)
	}
	assertRejectedBeforeSuccess(t, s.EventsForCall(callID), EventVerifyOutputMissed)
}

// TestLookupDetectsAlteredDeclaredOutputIndependentlyOfMissing demonstrates
// the other half of the ticket's own fault scenario wording, "resume with
// missing OR altered output": a declared output that IS present in
// storage, but whose content no longer matches the digest the manifest
// declared for it, must be rejected as altered - a distinct error from
// ErrOutputMissing, so a caller can tell "we never got this output" apart
// from "we got something, but it's not what was recorded."
func TestLookupDetectsAlteredDeclaredOutputIndependentlyOfMissing(t *testing.T) {
	s := NewStore()
	e := validEntry("id-altered-output", []byte("valid content"), "",
		map[string][]byte{"report.json": []byte(`{"pass":true}`)},
		[]string{"report.json"},
	)
	// The declared digest still describes the ORIGINAL output content;
	// only the stored bytes are altered afterward, as if storage silently
	// returned a different (but present) file.
	e.Outputs["report.json"] = []byte(`{"pass":false}`)
	s.Put(e)

	_, callID, err := s.Lookup("id-altered-output", "")
	if !errors.Is(err, ErrOutputAltered) {
		t.Fatalf("expected ErrOutputAltered, got: %v", err)
	}
	if errors.Is(err, ErrOutputMissing) {
		t.Fatalf("an altered-but-present output must not also report ErrOutputMissing")
	}
	assertRejectedBeforeSuccess(t, s.EventsForCall(callID), EventVerifyOutputAlter)
}

// TestLookupRejectsStaleEntryUnderSameIdentityAfterSourceMutation is the
// genuine AC #3 "stale ready-cache entry" demonstration. An earlier version
// of this fixture only tested that a DIFFERENT identity key produced a
// miss (an independent Codex review correctly identified that an ordinary
// miss on a different key is not a stale-entry rejection - the two are
// different claims). This test instead stores one entry under identity X,
// produced from source snapshot A, and looks up that SAME identity X while
// declaring the CURRENT source snapshot to be B (post-mutation) - proving
// the entry is rejected as stale even though it is found under its own key
// and is otherwise perfectly well-formed, not silently served as a hit.
func TestLookupRejectsStaleEntryUnderSameIdentityAfterSourceMutation(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, dir, "main.go", "package main\n")
	before, err := Take(dir)
	if err != nil {
		t.Fatal(err)
	}

	s := NewStore()
	const identity = "id-reused-across-source-mutation"
	s.Put(validEntry(identity, []byte("built from pre-mutation source"), before.Digest, nil, nil))

	// Confirm the entry is genuinely valid and servable before the source
	// changes, so the later rejection is attributable to staleness, not to
	// some other defect in the entry.
	if _, _, err := s.Lookup(identity, before.Digest); err != nil {
		t.Fatalf("expected the entry to be a valid hit against its own source digest, got: %v", err)
	}

	// Source legitimately changes.
	writeFile(t, dir, "main.go", "package main\n\nfunc main() {}\n")
	after, err := Take(dir)
	if err != nil {
		t.Fatal(err)
	}
	if after.Digest == before.Digest {
		t.Fatal("test fixture bug: mutation did not change the snapshot digest")
	}

	// SAME identity key, but the caller now declares the CURRENT source
	// digest to be `after`. The entry is still found (it is still stored
	// under `identity`), but must be rejected as stale before any success
	// is reported.
	_, callID, err := s.Lookup(identity, after.Digest)
	if !errors.Is(err, ErrStaleSource) {
		t.Fatalf("expected ErrStaleSource for a same-identity entry reused after the source moved on, got: %v", err)
	}
	events := s.EventsForCall(callID)
	if !containsEventKind(events, EventLookupHit) {
		t.Fatalf("expected the entry to still be FOUND (lookup-hit) before being rejected as stale - otherwise this is indistinguishable from an ordinary miss: %+v", events)
	}
	assertRejectedBeforeSuccess(t, events, EventVerifySourceFail)
}

// TestLookupMissOnDifferentIdentityIsOrdinaryNotStale keeps the original
// scenario as a real, if more modest, demonstration: looking up a
// different identity key naturally does not find the entry stored under
// the old one. This is a genuine and useful property, but - per the Codex
// review - it must not be conflated with stale-entry REJECTION (see
// TestLookupRejectsStaleEntryUnderSameIdentityAfterSourceMutation above for
// that).
func TestLookupMissOnDifferentIdentityIsOrdinaryNotStale(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, dir, "main.go", "package main\n")
	before, err := Take(dir)
	if err != nil {
		t.Fatal(err)
	}

	s := NewStore()
	s.Put(validEntry(before.Digest, []byte("built from pre-mutation source"), before.Digest, nil, nil))

	writeFile(t, dir, "main.go", "package main\n\nfunc main() {}\n")
	after, err := Take(dir)
	if err != nil {
		t.Fatal(err)
	}

	_, callID, err := s.Lookup(after.Digest, after.Digest)
	if !errors.Is(err, ErrMiss) {
		t.Fatalf("expected an ordinary ErrMiss for a never-stored identity, got: %v", err)
	}
	if containsEventKind(s.EventsForCall(callID), EventLookupHit) {
		t.Fatalf("an ordinary miss must not report lookup-hit")
	}
}

func writeFile(t *testing.T, dir, name, content string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, name), []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func assertRejectedBeforeSuccess(t *testing.T, events []Event, wantFailureKind string) {
	t.Helper()
	if containsEventKind(events, EventSuccess) {
		t.Fatalf("a rejected lookup must never log %q: %+v", EventSuccess, events)
	}
	if lastEventKind(events) != EventReject {
		t.Fatalf("expected the last event to be %q, got %q (%+v)", EventReject, lastEventKind(events), events)
	}
	if len(events) < 2 || events[len(events)-2].Kind != wantFailureKind {
		t.Fatalf("expected %q to immediately precede %q, got %+v", wantFailureKind, EventReject, events)
	}
}
