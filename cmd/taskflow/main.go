package main

import (
	"fmt"
	"os"
)

var version = "dev"

func main() {
	if len(os.Args) == 2 && os.Args[1] == "version" {
		fmt.Println(version)
		return
	}
	fmt.Print(`Taskflow

Code-first pipelines for local and remote task runners.

This architecture bootstrap currently exposes the Go SDK and scheduler.

Usage:
  taskflow version

Try:
  go run ./examples/basic
`)
}
