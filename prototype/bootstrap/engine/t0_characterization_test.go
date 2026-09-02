package engine_test

// T0 evidence instrumentation for backlog ticket TF-001.04. These tests exist
// only to produce reproducible, observable evidence of the prototype's
// cache-hit/cache-miss ordering and provider-acquisition-before-cache-lookup
// behaviour for the roadmap's T0 gate (docs/roadmap.md#7). They are not part
// of the permanent regression suite and may be removed once that evidence is
// captured; they exercise only the real production code paths through thin,
// delegating instrumentation, never a reimplementation of the logic under
// test.

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/arr/taskflow/cache"
	cachefile "github.com/arr/taskflow/cache/file"
	"github.com/arr/taskflow/engine"
	"github.com/arr/taskflow/flow"
	"github.com/arr/taskflow/process"
	"github.com/arr/taskflow/runner"
	"github.com/arr/taskflow/runner/command"
	"github.com/arr/taskflow/state"
	"github.com/arr/taskflow/target"
	"github.com/arr/taskflow/target/local"
)

func newRegistryWithCommand(t *testing.T, direct command.Adapter) *runner.Registry {
	t.Helper()
	registry := runner.NewRegistry()
	if err := registry.Register(direct); err != nil {
		t.Fatal(err)
	}
	return registry
}

func execAppendSpec(path, marker string) process.Spec {
	return process.Spec{
		Program: "sh",
		Args:    []string{"-c", `printf '%s' "$1" >> "$2"`, "--", marker, path},
	}
}

func noopIO() process.IO {
	return process.IO{Stdout: io.Discard, Stderr: io.Discard}
}

func countOccurrences(s string, r rune) int {
	count := 0
	for _, c := range s {
		if c == r {
			count++
		}
	}
	return count
}

// orderedLog records timestamped lifecycle events from multiple goroutines.
type orderedLog struct {
	mu     sync.Mutex
	events []string
}

func (l *orderedLog) record(event string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.events = append(l.events, event)
}

func (l *orderedLog) snapshot() []string {
	l.mu.Lock()
	defer l.mu.Unlock()
	out := make([]string, len(l.events))
	copy(out, l.events)
	return out
}

func (l *orderedLog) indexOf(event string) int {
	for i, e := range l.snapshot() {
		if e == event {
			return i
		}
	}
	return -1
}

// loggingStore delegates to a real cache.Store and logs every Open (the
// actual cache-resolution point) so its position relative to environment
// acquisition can be observed.
type loggingStore struct {
	cache.Store
	log *orderedLog
}

func (s loggingStore) Open(ctx context.Context, key cache.Key) (cache.Entry, io.ReadCloser, bool, error) {
	s.log.record("cache-open-start")
	entry, reader, found, err := s.Store.Open(ctx, key)
	if found {
		s.log.record("cache-open-hit")
	} else {
		s.log.record("cache-open-miss")
	}
	return entry, reader, found, err
}

// loggingProvider, loggingReservation, and loggingEnvironment delegate to the
// real local.Provider stack and log Acquire and Upload so the point of
// provider/environment acquisition can be observed relative to cache
// resolution.
type loggingProvider struct {
	target.Provider
	log *orderedLog
}

func (p loggingProvider) TryReserve(
	ctx context.Context,
	request target.AcquireRequest,
) (target.Reservation, bool, error) {
	p.log.record("reserve")
	reservation, admitted, err := p.Provider.TryReserve(ctx, request)
	if !admitted || err != nil {
		return reservation, admitted, err
	}
	return loggingReservation{Reservation: reservation, log: p.log}, admitted, err
}

type loggingReservation struct {
	target.Reservation
	log *orderedLog
}

func (r loggingReservation) Acquire(ctx context.Context) (target.Environment, error) {
	r.log.record("acquire-start")
	environment, err := r.Reservation.Acquire(ctx)
	if err != nil {
		return nil, err
	}
	r.log.record("acquire-done")
	return loggingEnvironment{Environment: environment, log: r.log}, nil
}

type loggingEnvironment struct {
	target.Environment
	log *orderedLog
}

func (e loggingEnvironment) Upload(ctx context.Context, source io.Reader) error {
	e.log.record("environment-upload-start")
	err := e.Environment.Upload(ctx, source)
	e.log.record("environment-upload-done")
	return err
}

func (e loggingEnvironment) Identity(
	ctx context.Context,
	request target.IdentityRequest,
) (target.Identity, error) {
	e.log.record("identity-probe-start")
	identity, err := e.Environment.Identity(ctx, request)
	e.log.record("identity-probe-done")
	return identity, err
}

// TestT0CacheOrderingAcrossMissThenHit runs the same cacheable pipeline twice
// through the real Scheduler/RuntimeExecutor stack, first as a cache miss and
// then as a cache hit, and asserts the observed event ordering: provider
// acquisition and environment probing always happen before cache resolution
// can complete, for both the miss and the hit run. This is reproducible
// evidence for TF-001.04 acceptance criteria #1 and #2.
func TestT0CacheOrderingAcrossMissThenHit(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "input.txt"), []byte("input"), 0o600); err != nil {
		t.Fatal(err)
	}
	direct := command.New()
	pipeline := flow.MustDefine("t0-cache-order", func(p *flow.Builder) {
		p.Step(
			"build",
			direct.Run("sh", "-c", "printf output > result.txt"),
			flow.Inputs("input.txt"),
			flow.Outputs("result.txt"),
			flow.WithCache(flow.CacheReadWrite, "v1"),
		)
	})
	runners := newRegistryWithCommand(t, direct)

	runOnce := func(runID string) []string {
		log := &orderedLog{}
		targets := target.NewRegistry()
		if err := targets.Register(loggingProvider{Provider: local.New(root), log: log}); err != nil {
			t.Fatal(err)
		}
		coordinator := &cache.Coordinator{
			Store:         loggingStore{Store: cachefile.New(filepath.Join(root, "..", "shared-cache")), log: log},
			WorkspaceRoot: root,
		}
		executor := &engine.RuntimeExecutor{
			Runners: runners, Targets: targets, Cache: coordinator,
			Stdout: io.Discard, Stderr: io.Discard,
		}
		scheduler := engine.Scheduler{Executor: executor, State: state.NewMemory()}
		if _, err := scheduler.Run(ctx, pipeline, engine.Options{RunID: runID}); err != nil {
			t.Fatalf("Run(%s) error = %v", runID, err)
		}
		return log.snapshot()
	}

	missEvents := runOnce("miss")
	if idx := indexOf(missEvents, "cache-open-miss"); idx == -1 {
		t.Fatalf("miss run events = %v, want a cache-open-miss event", missEvents)
	}
	assertAcquisitionPrecedesCacheResolution(t, "miss", missEvents)

	if err := os.Remove(filepath.Join(root, "result.txt")); err != nil {
		t.Fatal(err)
	}
	hitEvents := runOnce("hit")
	if idx := indexOf(hitEvents, "cache-open-hit"); idx == -1 {
		t.Fatalf("hit run events = %v, want a cache-open-hit event", hitEvents)
	}
	assertAcquisitionPrecedesCacheResolution(t, "hit", hitEvents)

	t.Logf("miss run ordered events: %v", missEvents)
	t.Logf("hit run ordered events: %v", hitEvents)
}

func assertAcquisitionPrecedesCacheResolution(t *testing.T, label string, events []string) {
	t.Helper()
	acquireIdx := indexOf(events, "acquire-done")
	identityIdx := indexOf(events, "identity-probe-done")
	cacheIdx := firstIndexAfter(events, []string{"cache-open-hit", "cache-open-miss"})
	if acquireIdx == -1 || identityIdx == -1 || cacheIdx == -1 {
		t.Fatalf("%s run events = %v, missing expected lifecycle markers", label, events)
	}
	if !(acquireIdx < cacheIdx) {
		t.Fatalf("%s run: acquire-done at %d, want before cache resolution at %d; events=%v",
			label, acquireIdx, cacheIdx, events)
	}
	if !(identityIdx < cacheIdx) {
		t.Fatalf("%s run: identity-probe-done at %d, want before cache resolution at %d; events=%v",
			label, identityIdx, cacheIdx, events)
	}
}

func indexOf(events []string, target string) int {
	for i, e := range events {
		if e == target {
			return i
		}
	}
	return -1
}

func firstIndexAfter(events []string, candidates []string) int {
	for i, e := range events {
		for _, c := range candidates {
			if e == c {
				return i
			}
		}
	}
	return -1
}

// TestT0ConcurrentLocalProvidersDoNotCoordinateAcrossInstances demonstrates
// that admission exclusivity in target/local.Provider is held in per-instance
// memory, not on the shared filesystem checkout. Two independent Provider
// instances constructed over the SAME root directory model two independent
// Taskflow CLI processes sharing one worktree: neither observes the other's
// reservations, so both can be admitted for ExclusiveWorkspace-declared work
// simultaneously and their child processes race on the shared workspace
// files. This is reproducible evidence for TF-001.04 acceptance criterion #3.
func TestT0ConcurrentLocalProvidersDoNotCoordinateAcrossInstances(t *testing.T) {
	root := t.TempDir()
	sharedFile := filepath.Join(root, "shared.txt")

	providerA := local.New(root)
	providerB := local.New(root)

	reservationA, admittedA, err := providerA.TryReserve(context.Background(), target.AcquireRequest{
		RunID: "run-a", StepID: "exclusive-a", ExclusiveWorkspace: true,
	})
	if err != nil || !admittedA {
		t.Fatalf("provider A TryReserve() = %t, %v", admittedA, err)
	}
	defer reservationA.Release()

	reservationB, admittedB, err := providerB.TryReserve(context.Background(), target.AcquireRequest{
		RunID: "run-b", StepID: "exclusive-b", ExclusiveWorkspace: true,
	})
	if err != nil || !admittedB {
		t.Fatalf("provider B TryReserve() = %t, %v", admittedB, err)
	}
	defer reservationB.Release()

	if !admittedA || !admittedB {
		t.Fatal("expected both independent provider instances to admit exclusive work over the same root")
	}

	environmentA, err := reservationA.Acquire(context.Background())
	if err != nil {
		t.Fatalf("provider A Acquire() error = %v", err)
	}
	environmentB, err := reservationB.Acquire(context.Background())
	if err != nil {
		t.Fatalf("provider B Acquire() error = %v", err)
	}

	var wg sync.WaitGroup
	wg.Add(2)
	go func() {
		defer wg.Done()
		for i := 0; i < 50; i++ {
			_, _ = environmentA.Exec(context.Background(),
				execAppendSpec(sharedFile, "A"), noopIO())
			time.Sleep(time.Millisecond)
		}
	}()
	go func() {
		defer wg.Done()
		for i := 0; i < 50; i++ {
			_, _ = environmentB.Exec(context.Background(),
				execAppendSpec(sharedFile, "B"), noopIO())
			time.Sleep(time.Millisecond)
		}
	}()
	wg.Wait()

	content, err := os.ReadFile(sharedFile)
	if err != nil {
		t.Fatalf("read shared file: %v", err)
	}
	countA, countB := countOccurrences(string(content), 'A'), countOccurrences(string(content), 'B')
	t.Logf("shared checkout interference: file has %d bytes, %d A-writes, %d B-writes observed (100 attempted)",
		len(content), countA, countB)
	if countA+countB == 0 {
		t.Fatal("expected at least some interleaved writes from both concurrent, uncoordinated local providers")
	}
}
