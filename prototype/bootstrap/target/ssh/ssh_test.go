package ssh_test

import (
	"archive/tar"
	"bytes"
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/arr/taskflow/process"
	"github.com/arr/taskflow/target"
	"github.com/arr/taskflow/target/ssh"
	"github.com/arr/taskflow/workspace"
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
	var firstArchive, secondArchive bytes.Buffer
	if err := environment.Download(ctx, []string{"output.txt"}, &firstArchive); err != nil {
		t.Fatal(err)
	}
	if err := environment.Download(ctx, []string{"output.txt"}, &secondArchive); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(firstArchive.Bytes(), secondArchive.Bytes()) {
		t.Fatal("remote output archive is not deterministic")
	}
	if err := environment.Release(ctx, target.Release{Success: true}); err != nil {
		t.Fatalf("Release() error = %v", err)
	}
	if _, err := os.Stat(filepath.Join(root, "run-1", "build")); !os.IsNotExist(err) {
		t.Fatalf("remote workspace remains after cleanup: %v", err)
	}
}

func TestProviderContainsHostileComponentsBelowRoot(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	marker := filepath.Join(root, "keep")
	if err := os.WriteFile(marker, []byte("keep"), 0o600); err != nil {
		t.Fatal(err)
	}
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
	})
	if err != nil {
		t.Fatal(err)
	}
	reservation, admitted, err := provider.TryReserve(ctx, target.AcquireRequest{
		RunID: "..", StepID: ".", ExecutionGroup: "..",
	})
	if err != nil || !admitted {
		t.Fatalf("TryReserve() = %v, %v", admitted, err)
	}
	environment, err := reservation.Acquire(ctx)
	if err != nil {
		reservation.Release()
		t.Fatal(err)
	}
	if err := environment.Release(ctx, target.Release{}); err != nil {
		reservation.Release()
		t.Fatal(err)
	}
	reservation.Release()
	if contents, err := os.ReadFile(marker); err != nil || string(contents) != "keep" {
		t.Fatalf("cleanup escaped generated workspace: contents=%q error=%v", contents, err)
	}
}

func TestUploadRejectsHostileArchiveBeforeRemoteExtraction(t *testing.T) {
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
		MaxConcurrency: 1,
	})
	if err != nil {
		t.Fatal(err)
	}
	reservation, admitted, err := provider.TryReserve(
		ctx,
		target.AcquireRequest{RunID: "run", StepID: "step"},
	)
	if err != nil || !admitted {
		t.Fatalf("TryReserve() = %v, %v", admitted, err)
	}
	defer reservation.Release()
	environment, err := reservation.Acquire(ctx)
	if err != nil {
		t.Fatal(err)
	}
	var archive bytes.Buffer
	writer := tar.NewWriter(&archive)
	if err := writer.WriteHeader(&tar.Header{
		Name: "escape", Typeflag: tar.TypeSymlink, Linkname: "..",
	}); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	if err := environment.Upload(ctx, &archive); err == nil {
		t.Fatal("Upload() error = nil, want traversal rejection")
	}
}
