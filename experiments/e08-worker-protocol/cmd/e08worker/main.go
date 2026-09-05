package main

import (
	"bufio"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"regexp"
	"sync"
	"syscall"

	e08 "github.com/alessandro-rizzo/taskflow/experiments/e08-worker-protocol"
)

var ownedID = regexp.MustCompile(`^taskflow-e08-[a-z0-9-]+$`)

type operationRecord struct {
	PayloadDigest string          `json:"payload_digest"`
	Response      e08.SSHResponse `json:"response"`
}

type daemon struct {
	mu       sync.Mutex
	root     string
	workerID string
	profile  string
	revision uint64
	ops      map[string]operationRecord
}

type durableState struct {
	Revision uint64                     `json:"revision"`
	Ops      map[string]operationRecord `json:"operations"`
}

func main() {
	if len(os.Args) < 2 {
		fatal(errors.New("expected daemon or proxy"))
	}
	switch os.Args[1] {
	case "daemon":
		fatal(runDaemon(os.Args[2:]))
	case "proxy":
		fatal(runProxy(os.Args[2:]))
	default:
		fatal(fmt.Errorf("unknown mode %q", os.Args[1]))
	}
}

func fatal(err error) {
	if err == nil {
		return
	}
	fmt.Fprintln(os.Stderr, err)
	os.Exit(2)
}

func runDaemon(args []string) error {
	flags := flag.NewFlagSet("daemon", flag.ContinueOnError)
	socket := flags.String("socket", "", "owned Unix socket")
	root := flags.String("root", "", "owned state root")
	workerID := flags.String("worker-id", "", "worker identity")
	profile := flags.String("profile-digest", "", "profile digest")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if !filepath.IsAbs(*root) || !ownedID.MatchString(filepath.Base(*root)) || !ownedID.MatchString(*workerID) {
		return errors.New("unowned daemon identity")
	}
	if filepath.Dir(*socket) != *root || filepath.Ext(*socket) != ".sock" {
		return errors.New("socket outside owned root")
	}
	if err := os.MkdirAll(filepath.Join(*root, "sandboxes"), 0o700); err != nil {
		return err
	}
	_ = os.Remove(*socket)
	listener, err := net.Listen("unix", *socket)
	if err != nil {
		return err
	}
	defer listener.Close()
	d := &daemon{root: *root, workerID: *workerID, profile: *profile, ops: make(map[string]operationRecord)}
	if err := d.load(); err != nil {
		return err
	}
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGINT, syscall.SIGTERM)
	go func() { <-signals; _ = listener.Close() }()
	for {
		conn, err := listener.Accept()
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return nil
			}
			return err
		}
		go d.serve(conn)
	}
}

func runProxy(args []string) error {
	flags := flag.NewFlagSet("proxy", flag.ContinueOnError)
	socket := flags.String("socket", "", "worker Unix socket")
	if err := flags.Parse(args); err != nil {
		return err
	}
	scanner := bufio.NewScanner(io.LimitReader(os.Stdin, 64<<20))
	scanner.Buffer(make([]byte, 64<<10), 8<<20)
	writer := bufio.NewWriter(os.Stdout)
	for scanner.Scan() {
		conn, err := net.Dial("unix", *socket)
		if err != nil {
			return err
		}
		line := append(append([]byte(nil), scanner.Bytes()...), '\n')
		if _, err := conn.Write(line); err != nil {
			_ = conn.Close()
			return err
		}
		if unix, ok := conn.(*net.UnixConn); ok {
			_ = unix.CloseWrite()
		}
		response, err := io.ReadAll(io.LimitReader(conn, 8<<20))
		_ = conn.Close()
		if err != nil {
			return err
		}
		if _, err := writer.Write(response); err != nil {
			return err
		}
		if err := writer.Flush(); err != nil {
			return err
		}
	}
	return scanner.Err()
}

func (d *daemon) serve(conn net.Conn) {
	defer conn.Close()
	decoder := json.NewDecoder(io.LimitReader(conn, 8<<20))
	decoder.DisallowUnknownFields()
	var request e08.SSHRequest
	if err := decoder.Decode(&request); err != nil {
		_ = json.NewEncoder(conn).Encode(e08.SSHResponse{Version: e08.SSHEnvelopeVersion, Status: "failed", Reason: e08.ReasonTransportDisconnected, Details: err.Error()})
		return
	}
	_ = json.NewEncoder(conn).Encode(d.apply(request))
}

func (d *daemon) apply(request e08.SSHRequest) e08.SSHResponse {
	d.mu.Lock()
	defer d.mu.Unlock()
	base := e08.SSHResponse{Version: e08.SSHEnvelopeVersion, OperationID: request.OperationID, WorkerID: d.workerID}
	if request.Version != e08.SSHEnvelopeVersion || request.WorkerID != d.workerID || request.OperationID == "" {
		base.Status, base.Reason, base.Details = "failed", e08.ReasonRevisionConflict, "invalid envelope identity"
		return base
	}
	payload, _ := json.Marshal(request)
	digest := e08.Digest(payload)
	if prior, ok := d.ops[request.OperationID]; ok {
		if prior.PayloadDigest != digest {
			base.Status, base.Reason, base.Details = "failed", e08.ReasonRevisionConflict, "conflicting duplicate"
			return base
		}
		return prior.Response
	}
	d.revision++
	base.Revision = d.revision
	response := d.execute(request, base)
	d.ops[request.OperationID] = operationRecord{PayloadDigest: digest, Response: response}
	if err := d.persist(); err != nil {
		response.Status, response.Reason, response.Details = "failed", e08.ReasonPublicationIO, err.Error()
		return response
	}
	return response
}

func (d *daemon) execute(request e08.SSHRequest, response e08.SSHResponse) e08.SSHResponse {
	response.Status, response.Reason = "ok", e08.ReasonCompleted
	sandbox := filepath.Join(d.root, "sandboxes", request.SandboxID)
	if request.SandboxID != "" && (!ownedID.MatchString(request.SandboxID) || filepath.Dir(sandbox) != filepath.Join(d.root, "sandboxes")) {
		response.Status, response.Reason, response.Details = "failed", e08.ReasonOutputPathEscape, "unowned sandbox"
		return response
	}
	switch request.Operation {
	case "attest":
		response.ProfileDigest = d.profile
		if request.ProfileDigest != d.profile {
			response.Status, response.Reason = "failed", e08.ReasonProfileMismatch
		}
	case "create_sandbox":
		if err := os.MkdirAll(sandbox, 0o700); err != nil {
			return failed(response, e08.ReasonProviderUnavailable, err)
		}
		response.SandboxID = request.SandboxID
	case "materialize":
		if e08.Digest(request.Data) != request.ObjectDigest {
			return failed(response, e08.ReasonObjectDigestMismatch, errors.New("digest mismatch"))
		}
		if err := os.MkdirAll(filepath.Join(sandbox, "input"), 0o700); err != nil {
			return failed(response, e08.ReasonProviderUnavailable, err)
		}
		tmp := filepath.Join(sandbox, "input", ".source.tmp")
		if err := os.WriteFile(tmp, request.Data, 0o600); err != nil {
			return failed(response, e08.ReasonProviderUnavailable, err)
		}
		if err := os.Rename(tmp, filepath.Join(sandbox, "input", "source.txt")); err != nil {
			return failed(response, e08.ReasonProviderUnavailable, err)
		}
	case "exec":
		if len(request.Command) != 1 || request.Command[0] != "e08-w2" {
			return failed(response, e08.ReasonCommandExitNonzero, errors.New("command not allowlisted"))
		}
		data, err := os.ReadFile(filepath.Join(sandbox, "input", "source.txt"))
		if err != nil {
			return failed(response, e08.ReasonMissingBlob, err)
		}
		response.Output = append([]byte("ssh-linux:"), data...)
		response.Logs = []e08.LogChunk{{Cursor: 1, Stream: "stdout", Digest: e08.Digest(response.Output)}}
	case "cleanup":
		if err := os.RemoveAll(sandbox); err != nil {
			return failed(response, e08.ReasonCleanupTimeout, err)
		}
	case "query_orphans":
		response.Orphans = []e08.Orphan{}
	default:
		return failed(response, e08.ReasonRevisionConflict, errors.New("unknown operation"))
	}
	return response
}

func failed(response e08.SSHResponse, reason e08.ReasonCode, err error) e08.SSHResponse {
	response.Status, response.Reason, response.Details = "failed", reason, err.Error()
	return response
}

func (d *daemon) load() error {
	data, err := os.ReadFile(filepath.Join(d.root, "state.json"))
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	var state durableState
	if err := json.Unmarshal(data, &state); err != nil {
		return err
	}
	d.revision, d.ops = state.Revision, state.Ops
	if d.ops == nil {
		d.ops = make(map[string]operationRecord)
	}
	return nil
}

func (d *daemon) persist() error {
	data, err := json.MarshalIndent(durableState{Revision: d.revision, Ops: d.ops}, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	tmp := filepath.Join(d.root, ".state.tmp")
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, filepath.Join(d.root, "state.json"))
}
