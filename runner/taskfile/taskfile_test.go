package taskfile_test

import (
	"context"
	"reflect"
	"testing"

	"github.com/arr/taskflow/runner/taskfile"
)

func TestResolve(t *testing.T) {
	t.Parallel()

	adapter := taskfile.New()
	invocation := adapter.Run("be:test", "-run", "TestAPI").
		WithDir("backend").
		WithEnv("CHECK", "true")

	resolved, err := adapter.Resolve(context.Background(), invocation)
	if err != nil {
		t.Fatalf("Resolve() error = %v", err)
	}
	spec := resolved.Process
	if got, want := spec.Program, "task"; got != want {
		t.Errorf("Program = %q, want %q", got, want)
	}
	if got, want := spec.Args, []string{"be:test", "--", "-run", "TestAPI"}; !reflect.DeepEqual(got, want) {
		t.Errorf("Args = %#v, want %#v", got, want)
	}
	if got, want := spec.Dir, "backend"; got != want {
		t.Errorf("Dir = %q, want %q", got, want)
	}
	if got, want := spec.Env["CHECK"], "true"; got != want {
		t.Errorf("Env[CHECK] = %q, want %q", got, want)
	}
	if got, want := resolved.Identity.Configuration["binary"], "task"; got != want {
		t.Errorf("identity binary = %q, want %q", got, want)
	}
}
