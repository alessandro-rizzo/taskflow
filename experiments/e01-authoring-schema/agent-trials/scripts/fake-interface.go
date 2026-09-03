package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

type output struct {
	ID       string `json:"id"`
	Type     string `json:"type"`
	Optional bool   `json:"optional"`
}

type operation struct {
	ID                   string   `json:"id"`
	Outputs              []output `json:"outputs"`
	RequiredCapabilities []string `json:"required_capabilities"`
}

type document struct {
	Operations []operation `json:"operations"`
}

func main() {
	if len(os.Args) != 3 {
		fatal("usage: taskflow-e01 api SCOPE | validate W1 @FILE | invoke W1 @FILE")
	}
	command, scope := os.Args[1], os.Args[2]
	if command == "api" {
		logCommand(os.Args[1:])
		data, err := os.ReadFile(schemaPath(scope))
		check(err)
		fmt.Print(string(data))
		return
	}
	fatal("validate and invoke require an @FILE argument")
}

func init() {
	if len(os.Args) != 4 || (os.Args[1] != "validate" && os.Args[1] != "invoke") {
		return
	}
	command, scope, reference := os.Args[1], os.Args[2], os.Args[3]
	if scope != "W1" || !strings.HasPrefix(reference, "@") {
		fatal("validate/invoke require W1 and @FILE")
	}
	argumentsRaw, err := os.ReadFile(strings.TrimPrefix(reference, "@"))
	check(err)
	var arguments map[string]any
	check(json.Unmarshal(argumentsRaw, &arguments))
	if problems := validate(arguments); len(problems) > 0 {
		for _, problem := range problems {
			fmt.Fprintln(os.Stderr, problem)
		}
		os.Exit(2)
	}
	logCommand(os.Args[1:])
	if command == "validate" {
		emit(map[string]any{"valid": true, "operation": "check"})
		os.Exit(0)
	}
	var schema document
	data, err := os.ReadFile(schemaPath(scope))
	check(err)
	check(json.Unmarshal(data, &schema))
	emit(map[string]any{
		"status":    "fake-success",
		"operation": schema.Operations[0].ID,
		"outputs":   schema.Operations[0].Outputs,
	})
	os.Exit(0)
}

func validate(arguments map[string]any) []string {
	var problems []string
	for name := range arguments {
		if name != "verbosity" && name != "changed-only" {
			problems = append(problems, fmt.Sprintf("operation check argument %s expected known argument", name))
		}
	}
	if value, ok := arguments["verbosity"]; ok {
		text, valid := value.(string)
		if !valid || (text != "quiet" && text != "normal" && text != "verbose") {
			problems = append(problems, "operation check argument verbosity expected one of [quiet normal verbose]")
		}
	}
	if value, ok := arguments["changed-only"]; ok {
		if _, valid := value.(bool); !valid {
			problems = append(problems, "operation check argument changed-only expected boolean")
		}
	}
	sort.Strings(problems)
	return problems
}

func schemaPath(scope string) string {
	paths := map[string]string{
		"W1":     "schemas/w1.schema.json",
		"W2":     "schemas/w2.schema.json",
		"W3":     "schemas/w3.schema.json",
		"effect": "schemas/effect.schema.json",
	}
	path, ok := paths[scope]
	if !ok {
		fatal("unknown scope")
	}
	return path
}

func logCommand(arguments []string) {
	path := ".interface-audit.jsonl"
	file, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	check(err)
	defer file.Close()
	encoded, err := json.Marshal(map[string]any{"arguments": arguments, "cwd": filepath.Base(must(os.Getwd()))})
	check(err)
	_, err = file.Write(append(encoded, '\n'))
	check(err)
}

func emit(value any) {
	encoded, err := json.MarshalIndent(value, "", "  ")
	check(err)
	fmt.Println(string(encoded))
}

func must(value string, err error) string {
	check(err)
	return value
}

func check(err error) {
	if err != nil {
		fatal(err.Error())
	}
}

func fatal(message string) {
	fmt.Fprintln(os.Stderr, message)
	os.Exit(2)
}
