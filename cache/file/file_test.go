package file_test

import (
	"bytes"
	"context"
	"io"
	"os"
	"path/filepath"
	"testing"

	"github.com/alessandro-rizzo/taskflow/cache"
	cachefile "github.com/alessandro-rizzo/taskflow/cache/file"
)

func TestStoreRoundTrip(t *testing.T) {
	t.Parallel()
	store := cachefile.New(t.TempDir())
	key := cache.NewKey([]byte("step"), []byte("inputs"))
	want := []byte("opaque output archive")
	entry, err := store.Put(context.Background(), key, bytes.NewReader(want))
	if err != nil {
		t.Fatalf("Put() error = %v", err)
	}
	gotEntry, reader, found, err := store.Open(context.Background(), key)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	if !found {
		t.Fatal("Open() found = false, want true")
	}
	defer reader.Close()
	got, err := io.ReadAll(reader)
	if err != nil {
		t.Fatalf("ReadAll() error = %v", err)
	}
	if !bytes.Equal(got, want) || gotEntry.Manifest != entry.Manifest {
		t.Fatalf("blob/manifest mismatch: got %q %#v want %q %#v", got, gotEntry, want, entry)
	}
	exists, err := store.Exists(context.Background(), key, entry.Manifest)
	if err != nil || !exists {
		t.Fatalf("Exists() = %t, %v, want true, nil", exists, err)
	}
}

func TestStoreMiss(t *testing.T) {
	t.Parallel()
	store := cachefile.New(t.TempDir())
	_, reader, found, err := store.Open(context.Background(), cache.NewKey([]byte("missing")))
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	if found || reader != nil {
		t.Fatalf("Open() = (%v, %t), want (nil, false)", reader, found)
	}
}

func TestStoreRejectsCorruptBlob(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	store := cachefile.New(dir)
	key := cache.NewKey([]byte("corrupt"))
	if _, err := store.Put(context.Background(), key, bytes.NewReader([]byte("original"))); err != nil {
		t.Fatal(err)
	}
	value := string(key)
	blob := filepath.Join(dir, value[:2], value[2:]+".tar")
	if err := os.WriteFile(blob, []byte("changed!"), 0o600); err != nil {
		t.Fatal(err)
	}
	_, reader, _, err := store.Open(context.Background(), key)
	if reader != nil {
		reader.Close()
	}
	if err == nil {
		t.Fatal("Open() error = nil, want manifest mismatch")
	}
}
