package local_test

import (
	"bytes"
	"context"
	"testing"

	"github.com/alessandro-rizzo/taskflow/process"
	"github.com/alessandro-rizzo/taskflow/target"
	"github.com/alessandro-rizzo/taskflow/target/local"
)

func TestEnvironmentExec(t *testing.T) {
	t.Parallel()

	provider := local.New(t.TempDir())
	environment, err := provider.Acquire(context.Background(), target.AcquireRequest{
		RunID:  "run",
		StepID: "step",
	})
	if err != nil {
		t.Fatalf("Acquire() error = %v", err)
	}
	var stdout bytes.Buffer
	result, err := environment.Exec(
		context.Background(),
		process.Spec{
			Program: "sh",
			Args:    []string{"-c", `printf '%s' "$VALUE"`},
			Env:     map[string]string{"VALUE": "hello"},
		},
		process.IO{Stdout: &stdout},
	)
	if err != nil {
		t.Fatalf("Exec() error = %v", err)
	}
	if result.ExitCode != 0 {
		t.Fatalf("ExitCode = %d, want 0", result.ExitCode)
	}
	if got, want := stdout.String(), "hello"; got != want {
		t.Fatalf("stdout = %q, want %q", got, want)
	}
}

func TestEnvironmentRejectsEscapingDirectory(t *testing.T) {
	t.Parallel()

	provider := local.New(t.TempDir())
	environment, err := provider.Acquire(context.Background(), target.AcquireRequest{
		RunID:  "run",
		StepID: "step",
	})
	if err != nil {
		t.Fatalf("Acquire() error = %v", err)
	}
	_, err = environment.Exec(
		context.Background(),
		process.Spec{Program: "true", Dir: "../outside"},
		process.IO{},
	)
	if err == nil {
		t.Fatal("Exec() error = nil, want workspace escape error")
	}
}
