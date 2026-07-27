package driver_test

import (
	"bytes"
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/alessandro-rizzo/taskflow/driver"
	"github.com/alessandro-rizzo/taskflow/flow"
	"github.com/alessandro-rizzo/taskflow/runner/command"
)

func TestHandshakeListAndGraph(t *testing.T) {
	t.Parallel()

	run := command.New()
	pipeline := flow.MustDefine("verify", func(p *flow.Builder) {
		first := p.Step("first", run.Run("true"))
		p.Step("second", run.Run("true"), flow.Needs(first), flow.On("remote"))
	})
	config := driver.Config{Pipelines: []*flow.Pipeline{pipeline}}

	var stdout, stderr bytes.Buffer
	if code := driver.Run(
		context.Background(),
		config,
		[]string{driver.HandshakeCommand},
		&stdout,
		&stderr,
	); code != 0 {
		t.Fatalf("handshake exit = %d, stderr = %s", code, stderr.String())
	}
	var handshake driver.Handshake
	if err := json.Unmarshal(stdout.Bytes(), &handshake); err != nil {
		t.Fatal(err)
	}
	if handshake.Protocol != driver.ProtocolVersion {
		t.Fatalf("protocol = %d, want %d", handshake.Protocol, driver.ProtocolVersion)
	}

	stdout.Reset()
	if code := driver.Run(context.Background(), config, []string{"list"}, &stdout, &stderr); code != 0 {
		t.Fatalf("list exit = %d, stderr = %s", code, stderr.String())
	}
	if stdout.String() != "verify\n" {
		t.Fatalf("list output = %q", stdout.String())
	}

	stdout.Reset()
	if code := driver.Run(
		context.Background(),
		config,
		[]string{"graph", "verify"},
		&stdout,
		&stderr,
	); code != 0 {
		t.Fatalf("graph exit = %d, stderr = %s", code, stderr.String())
	}
	if !strings.Contains(stdout.String(), `"first" -> "second"`) ||
		!strings.Contains(stdout.String(), `[remote]`) {
		t.Fatalf("graph output = %q", stdout.String())
	}
}
