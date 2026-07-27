package taskfile_test

import (
	"context"
	"reflect"
	"testing"

	"github.com/alessandro-rizzo/taskflow/runner/taskfile"
)

func TestResolve(t *testing.T) {
	t.Parallel()

	adapter := taskfile.New()
	invocation := adapter.Run("be:test", "-run", "TestAPI").
		WithDir("backend").
		WithEnv("CHECK", "true")

	spec, err := adapter.Resolve(context.Background(), invocation)
	if err != nil {
		t.Fatalf("Resolve() error = %v", err)
	}
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
}
