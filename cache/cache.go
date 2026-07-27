// Package cache defines Taskflow's content-addressed storage boundary.
package cache

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"io"
)

// Key is a content-addressed cache identity.
type Key string

// NewKey hashes ordered identity fragments.
func NewKey(parts ...[]byte) Key {
	hash := sha256.New()
	for _, part := range parts {
		var length [8]byte
		value := uint64(len(part))
		for index := 7; index >= 0; index-- {
			length[index] = byte(value)
			value >>= 8
		}
		hash.Write(length[:])
		hash.Write(part)
	}
	return Key(hex.EncodeToString(hash.Sum(nil)))
}

// Store persists opaque archives by content key.
//
// Packing declared outputs and materializing them into an acquired target are
// engine responsibilities rather than provider-specific behavior.
type Store interface {
	Get(context.Context, Key) (io.ReadCloser, bool, error)
	Put(context.Context, Key, io.Reader) error
}
