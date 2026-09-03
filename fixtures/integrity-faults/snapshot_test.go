package integrityfaults

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// TestSourceMutationAfterSnapshotDoesNotAlterDeclaredSource demonstrates
// AC #2: once Take has returned, mutating the live source directory must
// not change that Snapshot's already-declared Digest/Files. This is not a
// timing race to avoid; it is a structural guarantee (Take never re-reads
// root after returning), and this test proves it by mutating the directory
// well after Take returns and asserting the original Snapshot value is
// byte-for-byte identical to what it was immediately after Take.
func TestSourceMutationAfterSnapshotDoesNotAlterDeclaredSource(t *testing.T) {
	dir := t.TempDir()
	original := filepath.Join(dir, "main.go")
	if err := os.WriteFile(original, []byte("package main\n"), 0o644); err != nil {
		t.Fatalf("seed source file: %v", err)
	}

	snap, err := Take(dir)
	if err != nil {
		t.Fatalf("Take: %v", err)
	}

	// Copy the snapshot's declared state before mutating, so we can prove
	// it is unchanged afterward rather than merely re-reading the same
	// (possibly-mutated-in-place) struct fields.
	wantDigest := snap.Digest
	wantFiles := make(map[string]string, len(snap.Files))
	for k, v := range snap.Files {
		wantFiles[k] = v
	}

	// Mutate the live source after the snapshot was taken: edit the
	// existing file, and add a new one.
	if err := os.WriteFile(original, []byte("package main\n\nfunc main() {}\n"), 0o644); err != nil {
		t.Fatalf("mutate source file: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, "extra.go"), []byte("package main\n"), 0o644); err != nil {
		t.Fatalf("add new source file: %v", err)
	}

	if snap.Digest != wantDigest {
		t.Fatalf("snapshot Digest changed after live source mutation: got %s, want %s", snap.Digest, wantDigest)
	}
	if !reflect.DeepEqual(snap.Files, wantFiles) {
		t.Fatalf("snapshot Files changed after live source mutation: got %v, want %v", snap.Files, wantFiles)
	}

	// A NEW snapshot of the now-mutated directory is expected to differ -
	// that is the correct, orthogonal behavior (a fresh Take legitimately
	// observes the new state); it is not evidence against AC #2, which is
	// specifically about the FIRST snapshot's declared identity.
	after, err := Take(dir)
	if err != nil {
		t.Fatalf("Take after mutation: %v", err)
	}
	if after.Digest == wantDigest {
		t.Fatalf("expected a fresh Take of the mutated directory to produce a different digest, got the same one - test fixture is not actually exercising a mutation")
	}
}

func TestTakeIsOrderIndependent(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "b.txt"), []byte("b"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "a.txt"), []byte("a"), 0o644); err != nil {
		t.Fatal(err)
	}
	first, err := Take(dir)
	if err != nil {
		t.Fatal(err)
	}

	dir2 := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir2, "a.txt"), []byte("a"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir2, "b.txt"), []byte("b"), 0o644); err != nil {
		t.Fatal(err)
	}
	second, err := Take(dir2)
	if err != nil {
		t.Fatal(err)
	}

	if first.Digest != second.Digest {
		t.Fatalf("expected identical content across two directories to produce the same Digest regardless of write order, got %s vs %s", first.Digest, second.Digest)
	}
}
