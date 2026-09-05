package main

import (
	"encoding/json"
	"fmt"
	"os"

	e08 "github.com/alessandro-rizzo/taskflow/experiments/e08-worker-protocol"
)

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: e08profile profile.json")
		os.Exit(2)
	}
	data, err := os.ReadFile(os.Args[1])
	if err != nil {
		fail(err)
	}
	var profile e08.Profile
	if err := json.Unmarshal(data, &profile); err != nil {
		fail(err)
	}
	fmt.Println(profile.Digest())
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(2)
}
