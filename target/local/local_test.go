package local_test

import (
	"bytes"
	"context"
	"testing"

	"github.com/alessandro-rizzo/taskflow/process"
	"github.com/alessandro-rizzo/taskflow/target"
	"github.com/alessandro-rizzo/taskflow/target/local"
)

func acquire(t *testing.T, provider *local.Provider) target.Environment {
	t.Helper()
	reservation, admitted, err := provider.TryReserve(
		context.Background(), target.AcquireRequest{RunID: "run", StepID: "step"},
	)
	if err != nil || !admitted {
		t.Fatalf("TryReserve() = %t, %v", admitted, err)
	}
	t.Cleanup(reservation.Release)
	environment, err := reservation.Acquire(context.Background())
	if err != nil {
		t.Fatalf("Acquire() error = %v", err)
	}
	return environment
}

func TestEnvironmentExecAndIdentity(t *testing.T) {
	t.Parallel()
	environment := acquire(t, local.New(t.TempDir()))
	var stdout bytes.Buffer
	result, err := environment.Exec(
		context.Background(),
		process.Spec{
			Program: "sh", Args: []string{"-c", `printf '%s' "$VALUE"`},
			Env: map[string]string{"VALUE": "hello"},
		},
		process.IO{Stdout: &stdout},
	)
	if err != nil || result.ExitCode != 0 {
		t.Fatalf("Exec() = %#v, %v", result, err)
	}
	if got, want := stdout.String(), "hello"; got != want {
		t.Fatalf("stdout = %q, want %q", got, want)
	}
	identity, err := environment.Identity(context.Background(), target.IdentityRequest{
		Environment: []string{"VALUE"}, Overrides: map[string]string{"VALUE": "selected"},
		Toolchains: []target.Probe{{Name: "shell", Program: "sh", Args: []string{"--version"}}},
	})
	if err != nil {
		t.Fatalf("Identity() error = %v", err)
	}
	if identity.Environment["VALUE"] != "selected" || identity.Toolchains["shell"] == "" {
		t.Fatalf("Identity() = %#v", identity)
	}
}

func TestEnvironmentRejectsEscapingDirectory(t *testing.T) {
	t.Parallel()
	environment := acquire(t, local.New(t.TempDir()))
	_, err := environment.Exec(
		context.Background(),
		process.Spec{Program: "true", Dir: "../outside"},
		process.IO{},
	)
	if err == nil {
		t.Fatal("Exec() error = nil, want workspace escape error")
	}
}

func TestProviderReservesFiniteResources(t *testing.T) {
	t.Parallel()
	provider := local.New(t.TempDir())
	capabilities, err := provider.Capabilities(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	first, admitted, err := provider.TryReserve(context.Background(), target.AcquireRequest{
		RunID: "run", StepID: "all-cpu",
		Resources: map[string]int64{"cpu": capabilities.Resources["cpu"]},
	})
	if err != nil || !admitted {
		t.Fatalf("first TryReserve() = %v, %v", admitted, err)
	}
	_, admitted, err = provider.TryReserve(context.Background(), target.AcquireRequest{
		RunID: "run", StepID: "one-more", Resources: map[string]int64{"cpu": 1},
	})
	if err != nil {
		t.Fatal(err)
	}
	if admitted {
		t.Fatal("second resource reservation admitted beyond capacity")
	}
	first.Release()
	second, admitted, err := provider.TryReserve(context.Background(), target.AcquireRequest{
		RunID: "run", StepID: "after-release", Resources: map[string]int64{"cpu": 1},
	})
	if err != nil || !admitted {
		t.Fatalf("post-release TryReserve() = %v, %v", admitted, err)
	}
	second.Release()
}

func TestProviderSerializesExclusiveWorkspaceExecutions(t *testing.T) {
	t.Parallel()
	provider := local.New(t.TempDir())
	shared, admitted, err := provider.TryReserve(context.Background(), target.AcquireRequest{
		RunID: "run", StepID: "shared",
	})
	if err != nil || !admitted {
		t.Fatalf("shared TryReserve() = %v, %v", admitted, err)
	}
	_, admitted, err = provider.TryReserve(context.Background(), target.AcquireRequest{
		RunID: "run", StepID: "cacheable", ExclusiveWorkspace: true,
	})
	if err != nil {
		t.Fatal(err)
	}
	if admitted {
		t.Fatal("exclusive execution admitted while shared execution was active")
	}
	shared.Release()

	exclusive, admitted, err := provider.TryReserve(context.Background(), target.AcquireRequest{
		RunID: "run", StepID: "cacheable", ExclusiveWorkspace: true,
	})
	if err != nil || !admitted {
		t.Fatalf("exclusive TryReserve() = %v, %v", admitted, err)
	}
	_, admitted, err = provider.TryReserve(context.Background(), target.AcquireRequest{
		RunID: "run", StepID: "other",
	})
	if err != nil {
		t.Fatal(err)
	}
	if admitted {
		t.Fatal("shared execution admitted while exclusive execution was active")
	}
	exclusive.Release()
}
