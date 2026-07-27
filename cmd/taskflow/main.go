package main

import (
	"context"
	"errors"
	"fmt"
	"os"

	"github.com/alessandro-rizzo/taskflow/internal/projectdriver"
)

var version = "dev"

func main() {
	if len(os.Args) == 2 && os.Args[1] == "version" {
		fmt.Println(version)
		return
	}
	workingDirectory, err := os.Getwd()
	if err != nil {
		exitError(err)
	}
	root, err := projectdriver.FindRoot(workingDirectory)
	if err != nil {
		exitError(err)
	}
	loader := projectdriver.Loader{
		Version:  version,
		CacheDir: os.Getenv("TASKFLOW_DRIVER_CACHE"),
		Stdin:    os.Stdin,
		Stdout:   os.Stdout,
		Stderr:   os.Stderr,
	}
	binary, err := loader.Build(context.Background(), root)
	if err != nil {
		exitError(err)
	}
	if err := loader.Run(context.Background(), root, binary, os.Args[1:]); err != nil {
		var driverExit *projectdriver.ExitError
		if errors.As(err, &driverExit) {
			os.Exit(driverExit.Code)
		}
		exitError(err)
	}
}

func exitError(err error) {
	fmt.Fprintf(os.Stderr, "taskflow: %v\n", err)
	os.Exit(1)
}
