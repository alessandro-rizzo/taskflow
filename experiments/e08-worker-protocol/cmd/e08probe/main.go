package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"time"

	e08 "github.com/alessandro-rizzo/taskflow/experiments/e08-worker-protocol"
)

func main() {
	adapterName := flag.String("adapter", "", "in-process or macos-e06-stub")
	mode := flag.String("mode", "", "cache-hit, try-reserve, cancel, or cleanup")
	flag.Parse()
	if err := run(*adapterName, *mode); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
}

func run(adapterName, mode string) error {
	config := e08.AdapterConfig{}
	if mode == "try-reserve" {
		config.AcquireDelay = 5 * time.Second
	}
	var adapter e08.Adapter
	switch adapterName {
	case e08.AdapterInProcess:
		adapter = e08.NewInProcessAdapter(config)
	case e08.AdapterMacOSStub:
		adapter = e08.NewMacOSStubAdapter(config)
	default:
		return fmt.Errorf("unknown adapter %q", adapterName)
	}
	request := requestFor(adapter)
	switch mode {
	case "cache-hit":
		controller := e08.NewController()
		if err := controller.PrimeVerifiedResult(request, []byte("prepared-output")); err != nil {
			return err
		}
		result := controller.Run(context.Background(), adapter, request)
		if result.Status != "cache_hit" || !result.Counters.AllZero() {
			return fmt.Errorf("cache hit invariant failed: %#v", result)
		}
	case "try-reserve":
		started := time.Now()
		reservation, err := adapter.TryReserve(context.Background(), adapter.Profile().Digest())
		if err != nil || reservation.Disposition != e08.DispositionGranted {
			return fmt.Errorf("TryReserve failed: %#v: %w", reservation, err)
		}
		if time.Since(started) > 100*time.Millisecond {
			return fmt.Errorf("TryReserve exceeded frozen bound")
		}
	case "cancel":
		controller := e08.NewController()
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		result := controller.Run(ctx, adapter, request)
		if result.Status != "cancelled" && result.Reason != e08.ReasonCancelled {
			return fmt.Errorf("cancel did not become durable: %#v", result)
		}
	case "cleanup":
		result := e08.NewController().Run(context.Background(), adapter, request)
		if result.Status != "succeeded" || len(result.Orphans) != 0 || result.Counters.ReservationReleases != 1 {
			return fmt.Errorf("cleanup invariant failed: %#v", result)
		}
	default:
		return fmt.Errorf("unknown mode %q", mode)
	}
	return nil
}

func requestFor(adapter e08.Adapter) e08.Request {
	command := []string{"stub-command"}
	useSession := adapter.ID() == e08.AdapterMacOSStub
	if adapter.ID() == e08.AdapterInProcess {
		command = []string{"/bin/sh", "-c", "cat input/source.txt; printf ':built'"}
	}
	return e08.Request{
		RunID: "benchmark", NodeID: "build", AttemptID: "benchmark-attempt",
		Profile: adapter.Profile(), Source: []byte("source-v1"), Command: command,
		UseSession: useSession, CacheVersion: "v1", CleanupDeadline: time.Second,
	}
}
