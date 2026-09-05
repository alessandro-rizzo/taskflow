package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"time"

	e08 "github.com/alessandro-rizzo/taskflow/experiments/e08-worker-protocol"
)

type availability struct {
	Endpoint struct {
		Host           string `json:"host"`
		Port           int    `json:"port"`
		KnownHostsPath string `json:"known_hosts_path"`
	} `json:"endpoint"`
	Identity struct {
		User string `json:"user"`
	} `json:"identity"`
	Profile struct {
		LinuxProfileDigest string `json:"linux_profile_digest"`
	} `json:"profile"`
}

func main() {
	manifestPath := flag.String("manifest", "ssh-availability.json", "approved availability manifest")
	profilePath := flag.String("profile", "approved/ssh-profile.json", "full SSH profile")
	workerID := flag.String("worker", "taskflow-e08-worker-a", "worker identity")
	socket := flag.String("socket", "/config/taskflow-e08-ssh-linux/worker-a.sock", "worker socket")
	mode := flag.String("mode", "run", "run, cache-hit, try-reserve, cleanup, or query-orphans")
	flag.Parse()
	if err := run(*manifestPath, *profilePath, *workerID, *socket, *mode); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
}

func run(manifestPath, profilePath, workerID, socket, mode string) error {
	key := os.Getenv("TASKFLOW_E08_SSH_KEY")
	if key == "" || !filepath.IsAbs(key) {
		return errors.New("TASKFLOW_E08_SSH_KEY must be an absolute experiment-owned path")
	}
	var manifest availability
	if err := readJSON(manifestPath, &manifest); err != nil {
		return err
	}
	var profile e08.Profile
	if err := readJSON(profilePath, &profile); err != nil {
		return err
	}
	if profile.OS != "linux" || profile.Digest() != manifest.Profile.LinuxProfileDigest {
		return errors.New("profile does not match approved manifest")
	}
	repositoryRoot := filepath.Clean(filepath.Join(filepath.Dir(manifestPath), "..", ".."))
	knownHosts, err := filepath.Abs(filepath.Join(repositoryRoot, manifest.Endpoint.KnownHostsPath))
	if err != nil {
		return err
	}
	remote := fmt.Sprintf("%s@%s", manifest.Identity.User, manifest.Endpoint.Host)
	runner := &e08.OpenSSHRunner{Command: []string{
		"/usr/bin/ssh", "-F", "/dev/null", "-oBatchMode=yes", "-oIdentitiesOnly=yes", "-oIdentityAgent=none",
		"-oStrictHostKeyChecking=yes", "-oUserKnownHostsFile=" + knownHosts, "-oGlobalKnownHostsFile=/dev/null",
		"-oHostKeyAlgorithms=ssh-ed25519", "-oPasswordAuthentication=no", "-oKbdInteractiveAuthentication=no",
		"-oClearAllForwardings=yes", "-oForwardAgent=no", "-oForwardX11=no", "-oPermitLocalCommand=no", "-oRequestTTY=no",
		"-oConnectTimeout=5", "-oServerAliveInterval=2", "-oServerAliveCountMax=2", "-oLogLevel=ERROR",
		"-i", key, "-p", fmt.Sprint(manifest.Endpoint.Port), remote,
		"/config/e08/bin/e08worker", "proxy", "--socket", socket,
	}}
	adapter := e08.NewSSHLinuxAdapter(e08.SSHLinuxConfig{Profile: profile, Runner: runner, WorkerID: workerID, AllowCommand: []string{"e08-w2"}})
	request := e08.Request{RunID: "e08-ssh", NodeID: "build", AttemptID: fmt.Sprintf("taskflow-e08-probe-%x", time.Now().UnixNano()), Profile: profile, Source: []byte("bound-w2-source"), Command: []string{"e08-w2"}, CacheVersion: "v1", CleanupDeadline: 30 * time.Second}
	switch mode {
	case "attest":
		response, err := runner.RoundTrip(context.Background(), e08.SSHRequest{OperationID: "taskflow-e08-probe-attest", Operation: "attest", WorkerID: workerID, ProfileDigest: profile.Digest()})
		if err != nil {
			return fmt.Errorf("attestation round trip: %#v: %w", response, err)
		}
		if response.ProfileDigest != profile.Digest() {
			return fmt.Errorf("attestation digest = %q", response.ProfileDigest)
		}
	case "run", "cleanup":
		result := e08.NewController().Run(context.Background(), adapter, request)
		if result.Status != "succeeded" || len(result.Orphans) != 0 || result.Counters.ReservationReleases != 1 {
			return fmt.Errorf("SSH run failed: %#v", result)
		}
	case "cache-hit":
		controller := e08.NewController()
		if err := controller.PrimeVerifiedResult(request, []byte("prepared")); err != nil {
			return err
		}
		result := controller.Run(context.Background(), adapter, request)
		if result.Status != "cache_hit" || !result.Counters.AllZero() || adapter.Connections() != 0 {
			return errors.New("cache hit touched SSH capacity")
		}
	case "try-reserve":
		start := time.Now()
		reservation, err := adapter.TryReserve(context.Background(), profile.Digest())
		if err != nil || reservation.Disposition != e08.DispositionGranted || time.Since(start) > 100*time.Millisecond {
			return errors.New("TryReserve bound failed")
		}
		if adapter.Connections() != 0 {
			return errors.New("TryReserve opened SSH")
		}
	case "cancel":
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		result := e08.NewController().Run(ctx, adapter, request)
		if result.Status != "cancelled" || result.Reason != e08.ReasonCancelled || adapter.Connections() != 0 {
			return errors.New("pre-placement cancellation invariant failed")
		}
	case "query-orphans":
		response, err := runner.RoundTrip(context.Background(), e08.SSHRequest{OperationID: "taskflow-e08-query-orphans", Operation: "query_orphans", WorkerID: workerID})
		if err != nil || len(response.Orphans) != 0 {
			return fmt.Errorf("orphan query failed: %#v: %w", response, err)
		}
	default:
		return fmt.Errorf("unknown mode %q", mode)
	}
	return nil
}

func readJSON(path string, target any) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	return json.Unmarshal(data, target)
}
