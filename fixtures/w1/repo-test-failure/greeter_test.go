package greeter

import "testing"

func TestGreet(t *testing.T) {
	if got := Greet("Ada"); got != "Hi, Ada!" {
		t.Fatalf("Greet(%q) = %q, want %q", "Ada", got, "Hi, Ada!")
	}
	if got := Greet(""); got != "Hello, stranger!" {
		t.Fatalf("Greet(%q) = %q, want %q", "", got, "Hello, stranger!")
	}
}
