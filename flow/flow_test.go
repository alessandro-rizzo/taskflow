package flow_test

import (
	"strings"
	"testing"

	"github.com/alessandro-rizzo/taskflow/flow"
	"github.com/alessandro-rizzo/taskflow/runner/command"
)

func TestDefineBuildsTypedDAG(t *testing.T) {
	t.Parallel()

	run := command.New()
	pipeline, err := flow.Define("verify", func(p *flow.Builder) {
		format := p.Step("format", run.Run("gofmt", "-w", "."))
		test := p.Step(
			"test",
			run.Run("go", "test", "./..."),
			flow.Needs(format),
			flow.On("sprite"),
			flow.Outputs("build/results/**"),
			flow.WithCache(flow.CacheReadWrite, "v1"),
		)
		p.Step("package", run.Run("go", "build", "./..."), flow.Needs(test))
	})
	if err != nil {
		t.Fatalf("Define() error = %v", err)
	}

	if got, want := len(pipeline.Steps()), 3; got != want {
		t.Fatalf("len(Steps()) = %d, want %d", got, want)
	}
	testStep, ok := pipeline.Step("test")
	if !ok {
		t.Fatal("test step not found")
	}
	if got, want := testStep.Target, "sprite"; got != want {
		t.Errorf("test target = %q, want %q", got, want)
	}
	if got, want := testStep.Needs[0], flow.StepID("format"); got != want {
		t.Errorf("test dependency = %q, want %q", got, want)
	}
}

func TestDefineRejectsDuplicateStep(t *testing.T) {
	t.Parallel()

	run := command.New()
	_, err := flow.Define("duplicate", func(p *flow.Builder) {
		first := p.Step("first", run.Run("true"))
		second := p.Step("second", run.Run("true"), flow.Needs(first))
		p.Step("first", run.Run("true"), flow.Needs(second))
	})
	if err == nil {
		t.Fatal("Define() error = nil, want duplicate error")
	}
}

func TestDefineRejectsCacheWithoutOutputs(t *testing.T) {
	t.Parallel()

	run := command.New()
	_, err := flow.Define("invalid-cache", func(p *flow.Builder) {
		p.Step("test", run.Run("go", "test"), flow.WithCache(flow.CacheReadWrite, "v1"))
	})
	if err == nil || !strings.Contains(err.Error(), "without outputs") {
		t.Fatalf("Define() error = %v, want cache outputs error", err)
	}
}

func TestDigestChangesWithDefinition(t *testing.T) {
	t.Parallel()

	run := command.New()
	one := flow.MustDefine("verify", func(p *flow.Builder) {
		p.Step("test", run.Run("go", "test", "./..."))
	})
	two := flow.MustDefine("verify", func(p *flow.Builder) {
		p.Step("test", run.Run("go", "test", "-race", "./..."))
	})

	oneDigest, err := one.Digest()
	if err != nil {
		t.Fatalf("one.Digest() error = %v", err)
	}
	twoDigest, err := two.Digest()
	if err != nil {
		t.Fatalf("two.Digest() error = %v", err)
	}
	if oneDigest == twoDigest {
		t.Fatalf("digests are equal: %s", oneDigest)
	}
}
