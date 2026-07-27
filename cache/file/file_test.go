package file_test

import (
	"bytes"
	"context"
	"io"
	"testing"

	"github.com/alessandro-rizzo/taskflow/cache"
	cachefile "github.com/alessandro-rizzo/taskflow/cache/file"
)

func TestStoreRoundTrip(t *testing.T) {
	t.Parallel()

	store := cachefile.New(t.TempDir())
	key := cache.NewKey([]byte("step"), []byte("inputs"))
	want := []byte("opaque output archive")

	if err := store.Put(context.Background(), key, bytes.NewReader(want)); err != nil {
		t.Fatalf("Put() error = %v", err)
	}
	reader, found, err := store.Get(context.Background(), key)
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if !found {
		t.Fatal("Get() found = false, want true")
	}
	defer reader.Close()
	got, err := io.ReadAll(reader)
	if err != nil {
		t.Fatalf("ReadAll() error = %v", err)
	}
	if !bytes.Equal(got, want) {
		t.Fatalf("blob = %q, want %q", got, want)
	}
}

func TestStoreMiss(t *testing.T) {
	t.Parallel()

	store := cachefile.New(t.TempDir())
	reader, found, err := store.Get(context.Background(), cache.NewKey([]byte("missing")))
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if found || reader != nil {
		t.Fatalf("Get() = (%v, %t), want (nil, false)", reader, found)
	}
}
