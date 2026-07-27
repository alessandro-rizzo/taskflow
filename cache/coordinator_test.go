package cache_test

import (
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/alessandro-rizzo/taskflow/cache"
	cachefile "github.com/alessandro-rizzo/taskflow/cache/file"
	"github.com/alessandro-rizzo/taskflow/flow"
	"github.com/alessandro-rizzo/taskflow/process"
	"github.com/alessandro-rizzo/taskflow/runner"
	"github.com/alessandro-rizzo/taskflow/runner/taskfile"
	"github.com/alessandro-rizzo/taskflow/target"
	"github.com/alessandro-rizzo/taskflow/target/local"
)

func TestIdentityChangesForEveryDeclaredExecutionInput(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	input := filepath.Join(root, "input.txt")
	if err := os.WriteFile(input, []byte("one"), 0o600); err != nil {
		t.Fatal(err)
	}
	task := taskfile.New()
	pipeline := flow.MustDefine("verify", func(p *flow.Builder) {
		p.Step(
			"build",
			task.Run("build"),
			flow.Inputs("input.txt"),
			flow.Outputs("result.txt"),
			flow.EnvironmentKeys("PATH"),
			flow.Toolchain("go", "go", "version"),
			flow.WithCache(flow.CacheReadWrite, "v1"),
		)
	})
	step, _ := pipeline.Step("build")
	store := cachefile.New(filepath.Join(t.TempDir(), "cache"))
	coordinator := cache.Coordinator{Store: store, WorkspaceRoot: root}
	baseResolved, err := task.Resolve(ctx, step.Run)
	if err != nil {
		t.Fatal(err)
	}
	baseEnvironment := target.Identity{
		OS: "linux", Architecture: "arm64", Image: "image-1",
		Environment: map[string]string{"PATH": "/one"},
		Toolchains:  map[string]string{"go": "go1.24"},
	}
	base, err := coordinator.ComputeIdentity(
		ctx, "verify", step, baseResolved, baseEnvironment, map[string]string{"dep": "one"},
	)
	if err != nil {
		t.Fatal(err)
	}

	binaryAdapter := taskfile.Adapter{Binary: "task-v4-beta", Version: "v4"}
	binaryResolved, err := binaryAdapter.Resolve(ctx, step.Run)
	if err != nil {
		t.Fatal(err)
	}
	assertDifferentKey(t, coordinator, step, base, binaryResolved, baseEnvironment, map[string]string{"dep": "one"})

	changedEnvironment := baseEnvironment
	changedEnvironment.Environment = map[string]string{"PATH": "/two"}
	assertDifferentKey(t, coordinator, step, base, baseResolved, changedEnvironment, map[string]string{"dep": "one"})

	changedToolchain := baseEnvironment
	changedToolchain.Toolchains = map[string]string{"go": "go1.25"}
	assertDifferentKey(t, coordinator, step, base, baseResolved, changedToolchain, map[string]string{"dep": "one"})

	assertDifferentKey(t, coordinator, step, base, baseResolved, baseEnvironment, map[string]string{"dep": "two"})

	changedOutputs := step
	changedOutputs.Outputs = []string{"other.txt"}
	assertDifferentKey(
		t, coordinator, changedOutputs, base, baseResolved, baseEnvironment,
		map[string]string{"dep": "one"},
	)

	if err := os.WriteFile(input, []byte("two"), 0o600); err != nil {
		t.Fatal(err)
	}
	assertDifferentKey(t, coordinator, step, base, baseResolved, baseEnvironment, map[string]string{"dep": "one"})
}

func TestCoordinatorPublishesRestoresAndValidatesManifest(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	output := filepath.Join(root, "result.txt")
	if err := os.WriteFile(output, []byte("cached"), 0o600); err != nil {
		t.Fatal(err)
	}
	store := cachefile.New(filepath.Join(t.TempDir(), "cache"))
	coordinator := cache.Coordinator{Store: store, WorkspaceRoot: root}
	provider := local.New(root)
	reservation, admitted, err := provider.TryReserve(ctx, target.AcquireRequest{
		RunID: "run", StepID: "step",
	})
	if err != nil || !admitted {
		t.Fatalf("TryReserve() = %v, %v", admitted, err)
	}
	defer reservation.Release()
	environment, err := reservation.Acquire(ctx)
	if err != nil {
		t.Fatal(err)
	}
	key := cache.NewKey([]byte("identity"))
	entry, err := coordinator.Publish(ctx, key, environment, []string{"result.txt"})
	if err != nil {
		t.Fatalf("Publish() error = %v", err)
	}
	valid, err := coordinator.Valid(ctx, string(key), entry.Manifest)
	if err != nil || !valid {
		t.Fatalf("Valid() = %v, %v", valid, err)
	}
	if err := os.Remove(output); err != nil {
		t.Fatal(err)
	}
	restored, hit, err := coordinator.Restore(ctx, key, environment)
	if err != nil || !hit {
		t.Fatalf("Restore() = %#v, %v, %v", restored, hit, err)
	}
	contents, err := os.ReadFile(output)
	if err != nil {
		t.Fatal(err)
	}
	if string(contents) != "cached" {
		t.Fatalf("restored output = %q", contents)
	}
}

func TestPublishDoesNotDeadlockWhenStoreRejectsBeforeReading(t *testing.T) {
	t.Parallel()
	coordinator := cache.Coordinator{Store: rejectingStore{}}
	finished := make(chan error, 1)
	go func() {
		_, err := coordinator.Publish(
			context.Background(),
			cache.NewKey([]byte("failure")),
			endlessDownloadEnvironment{},
			[]string{"result"},
		)
		finished <- err
	}()
	select {
	case err := <-finished:
		if err == nil {
			t.Fatal("Publish() error = nil")
		}
	case <-time.After(time.Second):
		t.Fatal("Publish() deadlocked after store rejected the stream")
	}
}

func assertDifferentKey(
	t *testing.T,
	coordinator cache.Coordinator,
	step flow.Step,
	base cache.Identity,
	resolved runner.Resolved,
	environment target.Identity,
	dependencies map[string]string,
) {
	t.Helper()
	identity, err := coordinator.ComputeIdentity(
		context.Background(),
		"verify",
		step,
		resolved,
		environment,
		dependencies,
	)
	if err != nil {
		t.Fatal(err)
	}
	if identity.Key == base.Key {
		t.Fatalf("cache key did not change from %s", base.Key)
	}
}

type rejectingStore struct{}

func (rejectingStore) Open(
	context.Context,
	cache.Key,
) (cache.Entry, io.ReadCloser, bool, error) {
	return cache.Entry{}, nil, false, nil
}

func (rejectingStore) Put(context.Context, cache.Key, io.Reader) (cache.Entry, error) {
	return cache.Entry{}, errors.New("reject before reading")
}

func (rejectingStore) Exists(context.Context, cache.Key, string) (bool, error) {
	return false, nil
}

type endlessDownloadEnvironment struct{}

func (endlessDownloadEnvironment) ID() string {
	return "endless"
}

func (endlessDownloadEnvironment) Identity(
	context.Context,
	target.IdentityRequest,
) (target.Identity, error) {
	return target.Identity{}, nil
}

func (endlessDownloadEnvironment) Exec(
	context.Context,
	process.Spec,
	process.IO,
) (process.Result, error) {
	return process.Result{}, nil
}

func (endlessDownloadEnvironment) Upload(context.Context, io.Reader) error {
	return nil
}

func (endlessDownloadEnvironment) Download(
	_ context.Context,
	_ []string,
	destination io.Writer,
) error {
	block := make([]byte, 64*1024)
	for {
		if _, err := destination.Write(block); err != nil {
			return err
		}
	}
}

func (endlessDownloadEnvironment) Release(context.Context, target.Release) error {
	return nil
}
