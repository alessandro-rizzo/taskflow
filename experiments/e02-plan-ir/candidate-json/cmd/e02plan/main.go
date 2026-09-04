package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	candidate "e02/candidatejson"
)

func main() { os.Exit(run(os.Args[1:])) }

func run(args []string) int {
	if len(args) == 0 {
		return usage("command required")
	}
	switch args[0] {
	case "generate":
		return generate(args[1:])
	case "canonicalize":
		return canonicalize(args[1:])
	case "validate":
		return validate(args[1:])
	case "diff":
		return diff(args[1:])
	default:
		return usage("unknown command " + args[0])
	}
}

func usage(message string) int {
	fmt.Fprintln(os.Stderr, "e02plan:", message)
	fmt.Fprintln(os.Stderr, "commands: generate, canonicalize, validate, diff")
	return 2
}

func generate(args []string) int {
	flags := flag.NewFlagSet("generate", flag.ContinueOnError)
	fixture := flags.String("fixture", "", "w1, w2, w3, synthetic, large, or shape")
	platform := flags.String("platform", "", "shape platform")
	nodes := flags.Int("nodes", 10000, "large graph node count")
	canonical := flags.Bool("canonical", false, "emit canonical JSON")
	if flags.Parse(args) != nil {
		return 2
	}
	var plan candidate.Plan
	var err error
	switch *fixture {
	case "w1":
		plan, err = candidate.W1()
	case "w2":
		plan = candidate.W2()
	case "w3":
		plan = candidate.W3()
	case "synthetic":
		plan = candidate.Synthetic()
	case "large":
		plan = candidate.Large(*nodes)
	case "shape":
		plan, err = candidate.Shape(*platform)
	default:
		return usage("invalid --fixture")
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "e02plan:", err)
		return 1
	}
	raw, err := candidate.MarshalPlan(plan)
	if err == nil {
		err = candidate.Validate(raw)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "e02plan:", err)
		return 1
	}
	if *canonical {
		raw, err = candidate.Canonicalize(raw)
		if err != nil {
			fmt.Fprintln(os.Stderr, "e02plan:", err)
			return 1
		}
	}
	os.Stdout.Write(raw)
	if !*canonical {
		fmt.Println()
	}
	return 0
}

func read(path string) ([]byte, error) {
	if path == "-" {
		return os.ReadFile("/dev/stdin")
	}
	return os.ReadFile(path)
}

func canonicalize(args []string) int {
	flags := flag.NewFlagSet("canonicalize", flag.ContinueOnError)
	input := flags.String("input", "-", "input file")
	digest := flags.Bool("digest", false, "print digest only")
	if flags.Parse(args) != nil {
		return 2
	}
	raw, err := read(*input)
	if err == nil {
		err = candidate.Validate(raw)
	}
	var canonical []byte
	if err == nil {
		canonical, err = candidate.Canonicalize(raw)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "e02plan:", err)
		return 1
	}
	if *digest {
		fmt.Println(candidate.Digest(canonical))
	} else {
		os.Stdout.Write(canonical)
	}
	return 0
}
func validate(args []string) int {
	flags := flag.NewFlagSet("validate", flag.ContinueOnError)
	input := flags.String("input", "-", "input file")
	if flags.Parse(args) != nil {
		return 2
	}
	raw, err := read(*input)
	if err == nil {
		err = candidate.Validate(raw)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "e02plan:", err)
		return 1
	}
	fmt.Println("valid")
	return 0
}
func diff(args []string) int {
	flags := flag.NewFlagSet("diff", flag.ContinueOnError)
	before := flags.String("before", "", "before plan")
	after := flags.String("after", "", "after plan")
	if flags.Parse(args) != nil || *before == "" || *after == "" {
		return usage("diff requires --before and --after")
	}
	a, err := read(*before)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	b, err := read(*after)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	report, err := candidate.ResumeDiff(a, b)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	encoded, _ := json.MarshalIndent(report, "", "  ")
	fmt.Println(string(encoded))
	return 0
}
