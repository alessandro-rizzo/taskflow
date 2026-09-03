package candidatea

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDiscoveryAndValidationDoNotEvaluateBodies(t *testing.T) {
	path := filepath.Join(t.TempDir(), "sentinel")
	t.Setenv("E01_BODY_SENTINEL", path)
	for _, scope := range []string{"W1", "W2", "W3", "effect"} {
		if _, err := Discover(scope); err != nil {
			t.Fatal(err)
		}
	}
	if got := Validate("W1", map[string]any{"verbosity": 3.0}); got == nil {
		t.Fatal("expected diagnostic")
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("body sentinel exists: %v", err)
	}
}

func TestPositiveTypedComposition(t *testing.T) {
	AcceptIOS(Artifact[IOSApp]{})
	ConnectOther(Endpoint[OtherAPI]{})
	if got := ComposeW1(); len(got.TypedHandleRelations) != 6 {
		t.Fatalf("relations: %d", len(got.TypedHandleRelations))
	}
}
