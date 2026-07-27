package main

import (
	"context"
	"fmt"
	"os"

	"github.com/alessandro-rizzo/taskflow/engine"
	"github.com/alessandro-rizzo/taskflow/flow"
	"github.com/alessandro-rizzo/taskflow/runner"
	"github.com/alessandro-rizzo/taskflow/runner/command"
	"github.com/alessandro-rizzo/taskflow/state"
	"github.com/alessandro-rizzo/taskflow/target"
	"github.com/alessandro-rizzo/taskflow/target/local"
	"github.com/alessandro-rizzo/taskflow/terminal"
)

func main() {
	ctx := context.Background()
	direct := command.New()
	pipeline := flow.MustDefine("basic", func(p *flow.Builder) {
		prepare := p.Step("prepare", direct.Run("sh", "-c", "printf 'workspace ready\\n'"))
		unit := p.Step(
			"unit",
			direct.Run("sh", "-c", "printf 'unit tests passed\\n'"),
			flow.Needs(prepare),
		)
		lint := p.Step(
			"lint",
			direct.Run("sh", "-c", "printf 'lint passed\\n'"),
			flow.Needs(prepare),
		)
		p.Step(
			"package",
			direct.Run("sh", "-c", "printf 'package built\\n'"),
			flow.Needs(unit, lint),
		)
	})

	runners := runner.NewRegistry()
	must(runners.Register(direct))
	targets := target.NewRegistry()
	must(targets.Register(local.New(".")))

	renderer := terminal.New(os.Stdout, terminal.Normal)
	executor := engine.RuntimeExecutor{
		Runners: runners,
		Targets: targets,
		Stdout:  os.Stdout,
		Stderr:  os.Stderr,
	}
	scheduler := engine.Scheduler{
		Executor: &executor,
		State:    state.NewMemory(),
		Events:   renderer,
	}

	_, err := scheduler.Run(ctx, pipeline, engine.Options{
		MaxParallel: 2,
		FailFast:    true,
	})
	must(err)
}

func must(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
