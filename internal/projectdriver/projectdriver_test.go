package projectdriver_test

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/alessandro-rizzo/taskflow/internal/projectdriver"
)

func TestBuildCachesAndRunsCompiledDriver(t *testing.T) {
	repository := repositoryRoot(t)
	project := t.TempDir()
	writeFile(t, filepath.Join(project, "go.mod"), fmt.Sprintf(`module fixture

go 1.24.0

require github.com/alessandro-rizzo/taskflow v0.0.0

replace github.com/alessandro-rizzo/taskflow => %s
`, filepath.ToSlash(repository)))
	writeFile(t, filepath.Join(project, ".taskflow", "main.go"), `package main

import (
	"os"

	"github.com/alessandro-rizzo/taskflow/driver"
	"fixture/pipelines"
)

func main() {
	os.Exit(driver.Main(driver.Config{Pipelines: pipelines.All()}))
}
`)
	writeFile(t, filepath.Join(project, "pipelines", "pipelines.go"), `package pipelines

import (
	"github.com/alessandro-rizzo/taskflow/flow"
	"github.com/alessandro-rizzo/taskflow/runner/command"
)

func All() []*flow.Pipeline {
	run := command.New()
	pipeline := flow.MustDefine("verify", func(p *flow.Builder) {
		p.Step("test", run.Run("true"))
	})
	return []*flow.Pipeline{pipeline}
}
`)
	var stdout, stderr bytes.Buffer
	loader := projectdriver.Loader{
		Version:  "test",
		CacheDir: t.TempDir(),
		Stdout:   &stdout,
		Stderr:   &stderr,
	}
	first, err := loader.Build(context.Background(), project)
	if err != nil {
		t.Fatalf("Build() error = %v, stderr = %s", err, stderr.String())
	}
	oldTime := time.Unix(100, 0)
	if err := os.Chtimes(first, oldTime, oldTime); err != nil {
		t.Fatal(err)
	}
	second, err := loader.Build(context.Background(), project)
	if err != nil {
		t.Fatalf("cached Build() error = %v", err)
	}
	if first != second {
		t.Fatalf("cached binary = %q, want %q", second, first)
	}
	info, err := os.Stat(second)
	if err != nil {
		t.Fatal(err)
	}
	if !info.ModTime().Equal(oldTime) {
		t.Fatalf("cached driver was rebuilt: modtime = %s", info.ModTime())
	}
	if err := loader.Run(context.Background(), project, first, []string{"list"}); err != nil {
		t.Fatalf("Run(list) error = %v", err)
	}
	if stdout.String() != "verify\n" {
		t.Fatalf("list output = %q, stderr = %q", stdout.String(), stderr.String())
	}

	digestBefore, err := loader.SourceDigest(project)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(project, "pipelines", "pipelines.go")
	contents, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	writeFile(t, path, strings.Replace(string(contents), `"verify"`, `"changed"`, 1))
	digestAfter, err := loader.SourceDigest(project)
	if err != nil {
		t.Fatal(err)
	}
	if digestBefore == digestAfter {
		t.Fatal("imported main-module source edit did not change cache digest")
	}
}

func TestFindRootWalksParents(t *testing.T) {
	root := t.TempDir()
	if err := os.Mkdir(filepath.Join(root, ".taskflow"), 0o700); err != nil {
		t.Fatal(err)
	}
	nested := filepath.Join(root, "one", "two")
	if err := os.MkdirAll(nested, 0o700); err != nil {
		t.Fatal(err)
	}
	got, err := projectdriver.FindRoot(nested)
	if err != nil {
		t.Fatal(err)
	}
	if got != root {
		t.Fatalf("FindRoot() = %q, want %q", got, root)
	}
}

func TestRunForwardsCancellationToDriverForGracefulShutdown(t *testing.T) {
	t.Parallel()
	root := t.TempDir()
	binary := filepath.Join(root, "driver")
	writeFile(t, binary, `#!/bin/sh
if [ "$1" = "__taskflow_handshake" ]; then
  printf '{"protocol":1}\n'
  exit 0
fi
trap 'printf interrupted > interrupted; exit 1' INT TERM
printf started > started
while :; do sleep 0.05; done
`)
	if err := os.Chmod(binary, 0o700); err != nil {
		t.Fatal(err)
	}
	loader := projectdriver.Loader{}
	ctx, cancel := context.WithCancel(context.Background())
	finished := make(chan error, 1)
	go func() {
		finished <- loader.Run(ctx, root, binary, []string{"run"})
	}()
	deadline := time.Now().Add(2 * time.Second)
	for {
		if _, err := os.Stat(filepath.Join(root, "started")); err == nil {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("driver did not start")
		}
		time.Sleep(5 * time.Millisecond)
	}
	cancel()
	select {
	case err := <-finished:
		var exitErr *projectdriver.ExitError
		if !errors.As(err, &exitErr) {
			t.Fatalf("Run() error = %v, want driver exit status", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Run() did not wait for graceful driver shutdown")
	}
	if contents, err := os.ReadFile(filepath.Join(root, "interrupted")); err != nil ||
		string(contents) != "interrupted" {
		t.Fatalf("driver did not handle interrupt: contents=%q error=%v", contents, err)
	}
}

func repositoryRoot(t *testing.T) string {
	t.Helper()
	_, source, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller failed")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(source), "..", ".."))
}

func writeFile(t *testing.T, path, contents string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(contents), 0o600); err != nil {
		t.Fatal(err)
	}
}
