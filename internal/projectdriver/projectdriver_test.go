package projectdriver_test

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

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
	"github.com/alessandro-rizzo/taskflow/flow"
	"github.com/alessandro-rizzo/taskflow/runner/command"
)

func main() {
	run := command.New()
	pipeline := flow.MustDefine("verify", func(p *flow.Builder) {
		p.Step("test", run.Run("true"))
	})
	os.Exit(driver.Main(driver.Config{Pipelines: []*flow.Pipeline{pipeline}}))
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
	second, err := loader.Build(context.Background(), project)
	if err != nil {
		t.Fatalf("cached Build() error = %v", err)
	}
	if first != second {
		t.Fatalf("cached binary = %q, want %q", second, first)
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
	path := filepath.Join(project, ".taskflow", "main.go")
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
		t.Fatal("driver source edit did not change cache digest")
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
