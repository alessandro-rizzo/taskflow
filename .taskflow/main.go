package main

import (
	"fmt"
	"os"

	"github.com/alessandro-rizzo/taskflow/driver"
	"github.com/alessandro-rizzo/taskflow/engine"
	"github.com/alessandro-rizzo/taskflow/flow"
	"github.com/alessandro-rizzo/taskflow/runner"
	"github.com/alessandro-rizzo/taskflow/runner/taskfile"
	"github.com/alessandro-rizzo/taskflow/target"
	"github.com/alessandro-rizzo/taskflow/target/local"
)

func main() {
	task := taskfile.New()
	check := flow.MustDefine("check", func(p *flow.Builder) {
		p.Step("format", task.Run("fmt:check"))
		p.Step("test", task.Run("test"))
		p.Step("lint", task.Run("lint"))
	})

	runners := runner.NewRegistry()
	must(runners.Register(task))
	targets := target.NewRegistry()
	must(targets.Register(local.New(".")))
	executor := &engine.RuntimeExecutor{
		Runners: runners,
		Targets: targets,
		Stdout:  os.Stdout,
		Stderr:  os.Stderr,
	}
	os.Exit(driver.Main(driver.Config{
		Pipelines:   []*flow.Pipeline{check},
		Executor:    executor,
		MaxParallel: 3,
	}))
}

func must(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
