package candidateb

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestPositiveTypingAndBodyIsolation(t *testing.T) {
	AcceptIOS(Artifact[IOSApp]{})
	ConnectOther(Endpoint[OtherAPI]{})
	if len(ComposeW1().TypedHandleRelations) != 6 {
		t.Fatal("incomplete W1 trace")
	}
	path := filepath.Join(t.TempDir(), "sentinel")
	t.Setenv("E01_BODY_SENTINEL", path)
	for _, scope := range []string{"W1", "W2", "W3", "effect"} {
		if _, err := Discover(scope); err != nil {
			t.Fatal(err)
		}
	}
	if Validate("W1", map[string]any{"verbosity": 3.0}) == nil {
		t.Fatal("expected diagnostic")
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("body evaluated: %v", err)
	}
}

func TestGeneratorDiagnosticMapsToDeclaration(t *testing.T) {
	broken := strings.Replace(authoredSource, `e01:"output,id=test-report"`, `e01:"mystery,id=test-report"`, 1)
	_, err := GenerateFrom("authored-project.go", broken)
	if err == nil || !strings.Contains(err.Error(), "authored-project.go:") || !strings.Contains(err.Error(), "mystery") {
		t.Fatalf("diagnostic: %v", err)
	}
}
