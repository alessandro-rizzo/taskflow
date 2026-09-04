// e03attack is deliberately hostile, but targets only paths/listeners supplied by E03.
package main

import (
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
)

const outputProbeMarker = "E03-SYNTHETIC-OUTPUT-PROBE-7fc86c"

func die(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func mutatePlan(source, mode string) {
	raw, err := os.ReadFile(filepath.Join(source, "w1.json"))
	die(err)
	var doc map[string]any
	die(json.Unmarshal(raw, &doc))
	switch mode {
	case "exact-synthetic-marker":
		doc["planner_approval"] = outputProbeMarker
	case "hex-synthetic-marker":
		doc["planner_approval"] = hex.EncodeToString([]byte(outputProbeMarker))
	case "base64-synthetic-marker":
		doc["planner_approval"] = base64.StdEncoding.EncodeToString([]byte(outputProbeMarker))
	case "absolute-path-field":
		doc["nodes"].([]any)[2].(map[string]any)["planning_condition"].(map[string]any)["patterns"] = []any{"/private/e03-owned"}
	case "parent-traversal-path-field":
		doc["nodes"].([]any)[2].(map[string]any)["planning_condition"].(map[string]any)["patterns"] = []any{"../e03-owned"}
	}
	out, err := json.Marshal(doc)
	die(err)
	_, err = os.Stdout.Write(out)
	die(err)
}

func recordPID(target string) {
	if target == "" || target == "-" {
		return
	}
	die(os.WriteFile(target+".pid", []byte(strconv.Itoa(os.Getpid())), 0600))
}

func main() {
	if len(os.Args) < 3 {
		fmt.Fprintln(os.Stderr, "usage: e03attack CASE TARGET [SOURCE]")
		os.Exit(2)
	}
	caseID, target := os.Args[1], os.Args[2]
	switch caseID {
	case "benign-probe":
		return
	case "emit-plan":
		if len(os.Args) < 4 {
			os.Exit(2)
		}
		raw, err := os.ReadFile(filepath.Join(os.Args[3], "w1.json"))
		die(err)
		_, err = os.Stdout.Write(raw)
		die(err)
	case "relative-parent-read", "absolute-sibling-read", "symlink-escape-read":
		_, err := os.ReadFile(target)
		die(err)
	case "relative-parent-write", "absolute-sibling-write", "symlink-escape-write":
		die(os.WriteFile(target, []byte("E03-WRITE"), 0600))
	case "synthetic-daemon-token":
		if os.Getenv("TASKFLOW_E03_SYNTHETIC_DAEMON_TOKEN") == "" {
			os.Exit(1)
		}
	case "synthetic-provider-token":
		if os.Getenv("TASKFLOW_E03_SYNTHETIC_PROVIDER_TOKEN") == "" {
			os.Exit(1)
		}
	case "synthetic-secret-store-value":
		if os.Getenv("TASKFLOW_E03_SYNTHETIC_SECRET_VALUE") == "" {
			os.Exit(1)
		}
	case "home-and-config-roots-absent":
		if os.Getenv("HOME") == "" && os.Getenv("XDG_CONFIG_HOME") == "" {
			os.Exit(1)
		}
	case "runtime-sockets-absent":
		if os.Getenv("DOCKER_HOST") == "" && os.Getenv("SSH_AUTH_SOCK") == "" {
			os.Exit(1)
		}
	case "tcp-loopback-owned-listener":
		conn, err := net.DialTimeout("tcp", target, 300*time.Millisecond)
		die(err)
		die(conn.Close())
	case "unix-socket-owned-listener":
		conn, err := net.DialTimeout("unix", target, 300*time.Millisecond)
		die(err)
		die(conn.Close())
	case "single-descendant-ignores-parent-exit", "post-exit-marker-write":
		cmd := exec.Command(os.Args[0], "descendant", target)
		cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
		die(cmd.Start())
		die(os.WriteFile(target+".pid", []byte(strconv.Itoa(cmd.Process.Pid)), 0600))
	case "descendant":
		time.Sleep(500 * time.Millisecond)
		die(os.WriteFile(target, []byte("E03-DESCENDANT"), 0600))
	case "cleanup":
		raw, err := os.ReadFile(target)
		die(err)
		pid, err := strconv.Atoi(strings.TrimSpace(string(raw)))
		die(err)
		if err := syscall.Kill(pid, syscall.SIGKILL); err != nil && err != syscall.ESRCH {
			die(err)
		}
	case "probe":
		if _, err := os.Stat(target); err != nil {
			os.Exit(1)
		}
	case "cpu-limit":
		recordPID(target)
		for {
		}
	case "address-space-limit":
		recordPID(target)
		var held [][]byte
		for {
			block := make([]byte, 8*1024*1024)
			block[0] = 1
			held = append(held, block)
		}
	case "file-descriptor-limit":
		recordPID(target)
		var files []*os.File
		for {
			f, err := os.Open("/dev/null")
			if err != nil {
				os.Exit(1)
			}
			files = append(files, f)
		}
	case "stdout-stderr-limit":
		recordPID(target)
		block := strings.Repeat("x", 8192)
		for range 256 {
			_, _ = io.WriteString(os.Stdout, block)
			_, _ = io.WriteString(os.Stderr, block)
		}
	case "wall-time-limit":
		recordPID(target)
		time.Sleep(10 * time.Second)
	case "exact-synthetic-marker", "hex-synthetic-marker", "base64-synthetic-marker", "absolute-path-field", "parent-traversal-path-field":
		if len(os.Args) < 4 {
			os.Exit(2)
		}
		mutatePlan(os.Args[3], caseID)
	default:
		fmt.Fprintln(os.Stderr, "unknown case", caseID)
		os.Exit(2)
	}
}
