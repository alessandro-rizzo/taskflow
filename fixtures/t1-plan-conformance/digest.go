package conformance

import (
	"crypto/sha256"
	"encoding/hex"
)

// Digest returns the SHA-256 hex digest of canonical JSON bytes (from
// Canonicalize). Two candidates that canonicalize to the same bytes have
// the same digest regardless of original declaration order (E02: "repeated
// generation across processes produces the same canonical digest").
func Digest(canonical []byte) string {
	sum := sha256.Sum256(canonical)
	return hex.EncodeToString(sum[:])
}
