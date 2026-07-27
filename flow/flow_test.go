package flow_test

import (
	"strings"
	"testing"
	"time"

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

func TestReferenceCannotCrossPipelines(t *testing.T) {
	t.Parallel()

	run := command.New()
	var foreign flow.Ref
	flow.MustDefine("one", func(p *flow.Builder) {
		foreign = p.Step("same-id", run.Run("true"))
	})
	_, err := flow.Define("two", func(p *flow.Builder) {
		p.Step("dependent", run.Run("true"), flow.Needs(foreign))
	})
	if err == nil || !strings.Contains(err.Error(), "belongs to another pipeline") {
		t.Fatalf("Define() error = %v, want cross-pipeline reference error", err)
	}
}

func TestWorkspacePatternsCannotEscape(t *testing.T) {
	t.Parallel()

	run := command.New()
	for _, pattern := range []string{"/tmp/result", "../secret", "build/../../secret"} {
		pattern := pattern
		t.Run(pattern, func(t *testing.T) {
			_, err := flow.Define("escape", func(p *flow.Builder) {
				p.Step("test", run.Run("true"), flow.Inputs(pattern))
			})
			if err == nil {
				t.Fatalf("Inputs(%q) accepted a workspace escape", pattern)
			}
		})
	}
}

func TestDefineRejectsDotOnlyRemotePathComponents(t *testing.T) {
	t.Parallel()
	run := command.New()
	for _, test := range []struct {
		name   string
		define func(*flow.Builder)
	}{
		{
			name: "step ID",
			define: func(p *flow.Builder) {
				p.Step("..", run.Run("true"))
			},
		},
		{
			name: "execution group",
			define: func(p *flow.Builder) {
				p.Step("step", run.Run("true"), flow.InExecutionGroup("."))
			},
		},
	} {
		test := test
		t.Run(test.name, func(t *testing.T) {
			if _, err := flow.Define("invalid", test.define); err == nil {
				t.Fatal("Define() error = nil")
			}
		})
	}
}

func TestStructuralDigestIgnoresCosmeticsTuningAndOrder(t *testing.T) {
	t.Parallel()

	run := command.New()
	one := flow.MustDefine("verify", func(p *flow.Builder) {
		p.Step("first", run.Run("true"), flow.Describe("before"))
		p.Step("second", run.Run("true"))
	})
	two := flow.MustDefine("verify", func(p *flow.Builder) {
		p.Step("second", run.Run("true"))
		p.Step(
			"first",
			run.Run("true"),
			flow.Describe("after"),
			flow.Retry(4, time.Millisecond, time.Second, 2),
		)
	})
	oneStructural, err := one.StructuralDigest()
	if err != nil {
		t.Fatal(err)
	}
	twoStructural, err := two.StructuralDigest()
	if err != nil {
		t.Fatal(err)
	}
	if oneStructural != twoStructural {
		t.Fatalf("structural digests differ: %s != %s", oneStructural, twoStructural)
	}
	oneFull, _ := one.DefinitionDigest()
	twoFull, _ := two.DefinitionDigest()
	if oneFull == twoFull {
		t.Fatal("full definition digests are equal")
	}
}

func TestStructuralDigestGolden(t *testing.T) {
	t.Parallel()

	run := command.New()
	pipeline := flow.MustDefine("golden", func(p *flow.Builder) {
		p.Step(
			"test",
			run.Run("go", "test", "./..."),
			flow.Inputs("go.mod", "**/*.go"),
			flow.EnvironmentKeys("GOFLAGS"),
			flow.Toolchain("go", "go", "version"),
		)
	})
	digest, err := pipeline.StructuralDigest()
	if err != nil {
		t.Fatal(err)
	}
	const want = "323d6ac994677154a6f8c7457d8524b73f0c3e2fec13e6b81e22708b2eefd37e"
	if digest != want {
		t.Fatalf("StructuralDigest() = %q, want %q", digest, want)
	}
}
