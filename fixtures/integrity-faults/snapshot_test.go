package integrityfaults

import (
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestTakeRejectsEveryDescendantSymlinkPolicy(t *testing.T) {
	external := t.TempDir()
	externalSecret := "external-secret-must-not-appear"
	if err := os.WriteFile(filepath.Join(external, "secret.txt"), []byte(externalSecret), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(external, "secret-dir"), 0o755); err != nil {
		t.Fatal(err)
	}

	tests := []struct {
		name   string
		target func(root string) string
	}{
		{
			name: "out-of-root file",
			target: func(string) string {
				return filepath.Join(external, "secret.txt")
			},
		},
		{
			name: "out-of-root directory",
			target: func(string) string {
				return filepath.Join(external, "secret-dir")
			},
		},
		{
			name: "dangling link",
			target: func(string) string {
				return "missing-target"
			},
		},
		{
			name: "in-root file",
			target: func(string) string {
				return "ordinary.txt"
			},
		},
		{
			name: "in-root directory",
			target: func(string) string {
				return "ordinary-dir"
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			root := t.TempDir()
			if err := os.WriteFile(filepath.Join(root, "ordinary.txt"), []byte("ordinary"), 0o644); err != nil {
				t.Fatal(err)
			}
			if err := os.Mkdir(filepath.Join(root, "ordinary-dir"), 0o755); err != nil {
				t.Fatal(err)
			}
			const linkName = "offending-link"
			if err := os.Symlink(tt.target(root), filepath.Join(root, linkName)); err != nil {
				t.Skipf("symlinks unavailable: %v", err)
			}

			snapshot, err := Take(root)
			if !errors.Is(err, ErrSnapshotSymlink) {
				t.Fatalf("expected ErrSnapshotSymlink, got %v", err)
			}
			if !strings.Contains(err.Error(), linkName) {
				t.Fatalf("diagnostic %q does not identify relative path %q", err, linkName)
			}
			if strings.Contains(err.Error(), root) || strings.Contains(err.Error(), external) {
				t.Fatalf("diagnostic must contain only the relative link path, got %q", err)
			}
			if !strings.Contains(err.Error(), ErrSnapshotSymlink.Error()) {
				t.Fatalf("diagnostic %q does not explain the symlink policy", err)
			}
			if strings.Contains(err.Error(), externalSecret) {
				t.Fatalf("diagnostic leaked external content: %q", err)
			}
			if !reflect.DeepEqual(snapshot, Snapshot{}) {
				t.Fatalf("rejected snapshot returned partial state: %+v", snapshot)
			}
		})
	}
}

func TestTakeRejectsSymlinkRoot(t *testing.T) {
	realRoot := t.TempDir()
	link := filepath.Join(t.TempDir(), "source-root")
	if err := os.Symlink(realRoot, link); err != nil {
		t.Skipf("symlinks unavailable: %v", err)
	}

	snapshot, err := Take(link)
	if !errors.Is(err, ErrSnapshotSymlink) {
		t.Fatalf("expected ErrSnapshotSymlink, got %v", err)
	}
	if !strings.Contains(err.Error(), `"."`) {
		t.Fatalf("root-symlink diagnostic %q does not identify the relative root path", err)
	}
	if !reflect.DeepEqual(snapshot, Snapshot{}) {
		t.Fatalf("rejected snapshot returned partial state: %+v", snapshot)
	}
}

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
	if len(first.Files) != 2 || first.Files["a.txt"] == "" || first.Files["b.txt"] == "" {
		t.Fatalf("expected both ordinary files in snapshot, got %v", first.Files)
	}
	if !reflect.DeepEqual(first.Files, second.Files) {
		t.Fatalf("expected identical ordinary file identities, got %v vs %v", first.Files, second.Files)
	}
}
