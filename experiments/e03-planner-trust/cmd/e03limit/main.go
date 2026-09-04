// e03limit applies frozen hard limits before replacing itself with hostile code.
package main

import (
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"syscall"
)

func set(resource int, value uint64) error {
	return syscall.Setrlimit(resource, &syscall.Rlimit{Cur: value, Max: value})
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: e03limit PROGRAM [ARG...]")
		os.Exit(2)
	}
	if err := set(syscall.RLIMIT_CPU, 1); err != nil {
		fmt.Fprintln(os.Stderr, "rlimit cpu:", err)
		os.Exit(125)
	}
	if runtime.GOOS != "darwin" {
		if err := set(syscall.RLIMIT_AS, 256*1024*1024); err != nil {
			fmt.Fprintln(os.Stderr, "rlimit as:", err)
			os.Exit(125)
		}
	} else {
		fmt.Fprintln(os.Stderr, "E03-LIMIT-AS-UNSUPPORTED: darwin")
	}
	if err := set(syscall.RLIMIT_NOFILE, 64); err != nil {
		fmt.Fprintln(os.Stderr, "rlimit nofile:", err)
		os.Exit(125)
	}
	program, err := exec.LookPath(os.Args[1])
	if err != nil {
		fmt.Fprintln(os.Stderr, "lookup:", err)
		os.Exit(126)
	}
	if err := syscall.Exec(program, os.Args[1:], os.Environ()); err != nil {
		fmt.Fprintln(os.Stderr, "exec:", err)
		os.Exit(126)
	}
}
