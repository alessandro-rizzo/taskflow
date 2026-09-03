package main

import (
	"encoding/json"
	"fmt"
	"os"

	a "e01/candidatea"
)

func main() {
	if len(os.Args) < 2 {
		fatal("usage: e01a discover SCOPE | trace | validate SCOPE JSON")
	}
	switch os.Args[1] {
	case "discover":
		if len(os.Args) != 3 {
			fatal("discover requires scope")
		}
		value, err := a.Discover(os.Args[2])
		if err != nil {
			fatal(err.Error())
		}
		emit(value)
	case "trace":
		emit(a.ComposeW1())
	case "validate":
		if len(os.Args) != 4 {
			fatal("validate requires scope and JSON")
		}
		var values map[string]any
		if err := json.Unmarshal([]byte(os.Args[3]), &values); err != nil {
			fatal(err.Error())
		}
		if diagnostic := a.Validate(os.Args[2], values); diagnostic != nil {
			encoded, _ := json.Marshal(diagnostic)
			fmt.Fprintln(os.Stderr, string(encoded))
			fmt.Fprintln(os.Stderr, diagnostic.Human)
			os.Exit(2)
		}
		emit(map[string]bool{"valid": true})
	default:
		fatal("unknown command")
	}
}

func emit(value any) {
	encoded, err := a.Encode(value)
	if err != nil {
		fatal(err.Error())
	}
	fmt.Println(string(encoded))
}
func fatal(message string) { fmt.Fprintln(os.Stderr, message); os.Exit(2) }
