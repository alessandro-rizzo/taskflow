package ssh_test

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/alessandro-rizzo/taskflow/process"
	"github.com/alessandro-rizzo/taskflow/target"
	"github.com/alessandro-rizzo/taskflow/target/ssh"
	"github.com/alessandro-rizzo/taskflow/workspace"
)

func TestProviderTransfersExecutesAndCleansRemoteWorkspace(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	fakeSSH := filepath.Join(t.TempDir(), "ssh")
	if err := os.WriteFile(
		fakeSSH,
		[]byte("#!/bin/sh\nshift\nexec /bin/sh -c \"$1\"\n"),
		0o700,
	); err != nil {
		t.Fatal(err)
	}
	provider, err := ssh.New(ssh.Config{
		Host: "fixture", Root: filepath.ToSlash(root), Binary: fakeSSH,
		MaxConcurrency: 1, Cleanup: true,
		Resources: map[string]int64{"cpu": 2},
	})
	if err != nil {
		t.Fatal(err)
	}
	reservation, admitted, err := provider.TryReserve(ctx, target.AcquireRequest{
		RunID: "run-1", StepID: "build", Resources: map[string]int64{"cpu": 1},
	})
	if err != nil || !admitted {
		t.Fatalf("TryReserve() = %v, %v", admitted, err)
	}
	defer reservation.Release()
	environment, err := reservation.Acquire(ctx)
	if err != nil {
		t.Fatal(err)
	}

	source := t.TempDir()
	if err := os.WriteFile(filepath.Join(source, "input.txt"), []byte("hello\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	var archive bytes.Buffer
	if err := workspace.Pack(ctx, source, []string{"input.txt"}, &archive); err != nil {
		t.Fatal(err)
	}
	if err := environment.Upload(ctx, &archive); err != nil {
		t.Fatalf("Upload() error = %v", err)
	}
	if _, err := environment.Exec(
		ctx,
		process.Spec{Program: "sh", Args: []string{"-c", "tr a-z A-Z < input.txt > output.txt"}},
		process.IO{},
	); err != nil {
		t.Fatalf("Exec() error = %v", err)
	}
	archive.Reset()
	if err := environment.Download(ctx, []string{"output.txt"}, &archive); err != nil {
		t.Fatalf("Download() error = %v", err)
	}
	destination := t.TempDir()
	if err := workspace.Extract(ctx, destination, &archive); err != nil {
		t.Fatal(err)
	}
	output, err := os.ReadFile(filepath.Join(destination, "output.txt"))
	if err != nil {
		t.Fatal(err)
	}
	if string(output) != "HELLO\n" {
		t.Fatalf("output = %q", output)
	}
	if err := environment.Release(ctx, target.Release{Success: true}); err != nil {
		t.Fatalf("Release() error = %v", err)
	}
	if _, err := os.Stat(filepath.Join(root, "run-1", "build")); !os.IsNotExist(err) {
		t.Fatalf("remote workspace remains after cleanup: %v", err)
	}
}
