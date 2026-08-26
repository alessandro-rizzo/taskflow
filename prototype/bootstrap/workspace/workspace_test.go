package workspace_test

import (
	"archive/tar"
	"bytes"
	"context"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/arr/taskflow/workspace"
)

func TestExtractRejectsSymlinkEscapeAndSymlinkParentTraversal(t *testing.T) {
	t.Parallel()
	for _, test := range []struct {
		name    string
		prepare func(t *testing.T, root string)
		entries []tarEntry
	}{
		{
			name: "archive symlink dot-dot",
			entries: []tarEntry{
				{header: tar.Header{Name: "evil", Typeflag: tar.TypeSymlink, Linkname: ".."}},
				{header: tar.Header{Name: "evil/pwned", Typeflag: tar.TypeReg, Mode: 0o600}, body: "bad"},
			},
		},
		{
			name: "pre-existing symlink parent",
			prepare: func(t *testing.T, root string) {
				t.Helper()
				if err := os.Symlink("..", filepath.Join(root, "evil")); err != nil {
					t.Fatal(err)
				}
			},
			entries: []tarEntry{
				{header: tar.Header{Name: "evil/pwned", Typeflag: tar.TypeReg, Mode: 0o600}, body: "bad"},
			},
		},
	} {
		test := test
		t.Run(test.name, func(t *testing.T) {
			t.Parallel()
			parent := t.TempDir()
			root := filepath.Join(parent, "workspace")
			if err := os.Mkdir(root, 0o700); err != nil {
				t.Fatal(err)
			}
			if test.prepare != nil {
				test.prepare(t, root)
			}
			archive := makeTar(t, test.entries...)
			if err := workspace.Extract(context.Background(), root, &archive); err == nil {
				t.Fatal("Extract() error = nil, want symlink traversal rejection")
			}
			if _, err := os.Stat(filepath.Join(parent, "pwned")); !os.IsNotExist(err) {
				t.Fatalf("archive wrote outside workspace: %v", err)
			}
		})
	}
}

func TestExtractAllowsSafeRelativeSymlinkAndIsIdempotent(t *testing.T) {
	t.Parallel()
	root := t.TempDir()
	entries := []tarEntry{
		{header: tar.Header{Name: "target", Typeflag: tar.TypeReg, Mode: 0o600}, body: "value"},
		{header: tar.Header{Name: "sub", Typeflag: tar.TypeDir, Mode: 0o755}},
		{header: tar.Header{Name: "sub/link", Typeflag: tar.TypeSymlink, Linkname: "../target"}},
	}
	for attempt := 0; attempt < 2; attempt++ {
		archive := makeTar(t, entries...)
		if err := workspace.Extract(context.Background(), root, &archive); err != nil {
			t.Fatalf("Extract() attempt %d error = %v", attempt+1, err)
		}
	}
	value, err := os.ReadFile(filepath.Join(root, "sub", "link"))
	if err != nil {
		t.Fatal(err)
	}
	if string(value) != "value" {
		t.Fatalf("symlink content = %q", value)
	}
}

func TestNormalizeArchiveFiltersAndNormalizesHeaders(t *testing.T) {
	t.Parallel()
	raw := makeTar(t,
		tarEntry{header: tar.Header{
			Name: "dist", Typeflag: tar.TypeDir, Mode: 0o755,
			Uid: 501, Gid: 20, ModTime: time.Unix(99, 0),
		}},
		tarEntry{header: tar.Header{
			Name: "dist/file", Typeflag: tar.TypeReg, Mode: 0o4755,
			Uid: 501, Gid: 20, ModTime: time.Unix(99, 0),
		}, body: "result"},
	)
	var normalized bytes.Buffer
	if err := workspace.NormalizeArchive(
		context.Background(),
		&raw,
		[]string{"dist/**"},
		&normalized,
	); err != nil {
		t.Fatal(err)
	}
	reader := tar.NewReader(&normalized)
	for index, name := range []string{"dist", "dist/file"} {
		header, err := reader.Next()
		if err != nil {
			t.Fatal(err)
		}
		if header.Name != name || header.Uid != 0 || header.Gid != 0 ||
			header.Mode&0o7000 != 0 || !header.ModTime.Equal(time.Unix(0, 0).UTC()) {
			t.Fatalf("normalized header %d = %#v", index, header)
		}
	}
	if _, err := reader.Next(); err != io.EOF {
		t.Fatalf("final Next() error = %v, want EOF", err)
	}
}

func TestPackIsDeterministicAcrossModificationTimes(t *testing.T) {
	t.Parallel()
	root := t.TempDir()
	path := filepath.Join(root, "result")
	if err := os.WriteFile(path, []byte("same"), 0o600); err != nil {
		t.Fatal(err)
	}
	var first, second bytes.Buffer
	if err := workspace.Pack(context.Background(), root, []string{"result"}, &first); err != nil {
		t.Fatal(err)
	}
	newTime := time.Now().Add(24 * time.Hour)
	if err := os.Chtimes(path, newTime, newTime); err != nil {
		t.Fatal(err)
	}
	if err := workspace.Pack(context.Background(), root, []string{"result"}, &second); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(first.Bytes(), second.Bytes()) {
		t.Fatal("deterministic archive changed with modification time")
	}
}

type tarEntry struct {
	header tar.Header
	body   string
}

func makeTar(t *testing.T, entries ...tarEntry) bytes.Buffer {
	t.Helper()
	var archive bytes.Buffer
	writer := tar.NewWriter(&archive)
	for _, entry := range entries {
		header := entry.header
		if header.Typeflag == tar.TypeReg || header.Typeflag == tar.TypeRegA {
			header.Size = int64(len(entry.body))
		}
		if err := writer.WriteHeader(&header); err != nil {
			t.Fatal(err)
		}
		if entry.body != "" {
			if _, err := io.WriteString(writer, entry.body); err != nil {
				t.Fatal(err)
			}
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	return archive
}
