// Package driver implements the project-side half of Taskflow's versioned
// compiled-driver protocol.
package driver

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"sort"
	"strconv"
	"strings"
	"syscall"

	"github.com/arr/taskflow/engine"
	"github.com/arr/taskflow/event"
	"github.com/arr/taskflow/flow"
	"github.com/arr/taskflow/state"
	statefile "github.com/arr/taskflow/state/file"
	"github.com/arr/taskflow/terminal"
)

const ProtocolVersion = 1

const HandshakeCommand = "__taskflow_handshake"

type Handshake struct {
	Protocol int `json:"protocol"`
}

// Config is compiled into a project's .taskflow executable. Extensions remain
// ordinary Go dependencies; the generic CLI talks only to this stable surface.
type Config struct {
	Pipelines   []*flow.Pipeline
	Executor    engine.Executor
	State       state.Store
	Events      event.Sink
	MaxParallel int
}

// Main runs a compiled project driver using process arguments and streams.
func Main(config Config) int {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	return Run(ctx, config, os.Args[1:], os.Stdout, os.Stderr)
}

// Run exposes the protocol separately from os.Exit for tests and embedding.
func Run(
	ctx context.Context,
	config Config,
	args []string,
	stdout io.Writer,
	stderr io.Writer,
) int {
	if len(args) == 1 && args[0] == HandshakeCommand {
		if err := json.NewEncoder(stdout).Encode(Handshake{Protocol: ProtocolVersion}); err != nil {
			fmt.Fprintf(stderr, "taskflow: write handshake: %v\n", err)
			return 1
		}
		return 0
	}
	pipelines, err := pipelineIndex(config.Pipelines)
	if err != nil {
		fmt.Fprintf(stderr, "taskflow: invalid driver: %v\n", err)
		return 1
	}
	if len(args) == 0 {
		printUsage(stderr)
		return 2
	}
	switch args[0] {
	case "list":
		names := make([]string, 0, len(pipelines))
		for name := range pipelines {
			names = append(names, name)
		}
		sort.Strings(names)
		for _, name := range names {
			fmt.Fprintln(stdout, name)
		}
		return 0
	case "graph":
		if len(args) != 2 {
			fmt.Fprintln(stderr, "usage: taskflow graph PIPELINE")
			return 2
		}
		pipeline, ok := pipelines[args[1]]
		if !ok {
			fmt.Fprintf(stderr, "taskflow: pipeline %q is not defined\n", args[1])
			return 2
		}
		writeDOT(stdout, pipeline)
		return 0
	case "run":
		return runPipeline(ctx, config, pipelines, args[1:], false, stdout, stderr)
	case "resume":
		return runPipeline(ctx, config, pipelines, args[1:], true, stdout, stderr)
	default:
		fmt.Fprintf(stderr, "taskflow: unknown command %q\n", args[0])
		printUsage(stderr)
		return 2
	}
}

func runPipeline(
	ctx context.Context,
	config Config,
	pipelines map[string]*flow.Pipeline,
	args []string,
	resume bool,
	stdout io.Writer,
	stderr io.Writer,
) int {
	flags := flag.NewFlagSet("taskflow", flag.ContinueOnError)
	flags.SetOutput(stderr)
	runID := flags.String("run-id", "", "stable run identifier")
	maxParallel := flags.Int("max-parallel", config.MaxParallel, "maximum concurrent steps")
	failFast := flags.Bool("fail-fast", false, "cancel remaining work after a failure")
	if err := flags.Parse(args); err != nil {
		return 2
	}
	positionals := flags.Args()
	var pipelineName string
	if resume {
		if *runID == "" {
			if len(positionals) != 2 {
				fmt.Fprintln(stderr, "usage: taskflow resume [flags] RUN_ID PIPELINE")
				return 2
			}
			*runID, pipelineName = positionals[0], positionals[1]
		} else if len(positionals) == 1 {
			pipelineName = positionals[0]
		} else {
			fmt.Fprintln(stderr, "usage: taskflow resume [flags] RUN_ID PIPELINE")
			return 2
		}
	} else {
		if len(positionals) != 1 {
			fmt.Fprintln(stderr, "usage: taskflow run [flags] PIPELINE")
			return 2
		}
		pipelineName = positionals[0]
	}
	pipeline, ok := pipelines[pipelineName]
	if !ok {
		fmt.Fprintf(stderr, "taskflow: pipeline %q is not defined\n", pipelineName)
		return 2
	}
	if config.Executor == nil {
		fmt.Fprintln(stderr, "taskflow: project driver has no executor")
		return 1
	}
	store := config.State
	if store == nil {
		store = statefile.New(".taskflow/runs")
	}
	sink := config.Events
	if sink == nil {
		sink = terminal.New(stderr, terminal.Normal)
	}
	if *maxParallel <= 0 {
		*maxParallel = 1
	}
	scheduler := engine.Scheduler{
		Executor: config.Executor,
		State:    store,
		Events:   sink,
	}
	_, err := scheduler.Run(ctx, pipeline, engine.Options{
		RunID:       *runID,
		Resume:      resume,
		MaxParallel: *maxParallel,
		FailFast:    *failFast,
	})
	if err != nil {
		var runErr *engine.RunError
		if !errors.As(err, &runErr) {
			fmt.Fprintf(stderr, "taskflow: %v\n", err)
		}
		return 1
	}
	return 0
}

func pipelineIndex(pipelines []*flow.Pipeline) (map[string]*flow.Pipeline, error) {
	index := make(map[string]*flow.Pipeline, len(pipelines))
	for _, pipeline := range pipelines {
		if pipeline == nil {
			return nil, errors.New("nil pipeline")
		}
		if _, exists := index[pipeline.Name()]; exists {
			return nil, fmt.Errorf("duplicate pipeline %q", pipeline.Name())
		}
		index[pipeline.Name()] = pipeline
	}
	return index, nil
}

func writeDOT(output io.Writer, pipeline *flow.Pipeline) {
	fmt.Fprintf(output, "digraph %s {\n", strconv.Quote(pipeline.Name()))
	for _, step := range pipeline.Steps() {
		fmt.Fprintf(
			output,
			"  %s [label=%s];\n",
			strconv.Quote(string(step.ID)),
			strconv.Quote(string(step.ID)+"\\n["+step.Target+"]"),
		)
		for _, dependency := range step.Needs {
			fmt.Fprintf(
				output,
				"  %s -> %s;\n",
				strconv.Quote(string(dependency)),
				strconv.Quote(string(step.ID)),
			)
		}
	}
	fmt.Fprintln(output, "}")
}

func printUsage(output io.Writer) {
	fmt.Fprintln(output, strings.TrimSpace(`
Usage:
  taskflow list
  taskflow graph PIPELINE
  taskflow run [flags] PIPELINE
  taskflow resume [flags] RUN_ID PIPELINE`))
}
