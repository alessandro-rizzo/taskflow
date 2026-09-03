// Package integrityfaults is a toy, isolated reference implementation used
// to demonstrate (not define) the source-mutation, cache-corruption, and
// resume-integrity properties T1's E04 input requires (TF-002.07, roadmap
// section 9 E04). See README.md for what this is and, importantly, what it
// is not: a candidate design for the future production cache key or
// immutable-source mechanism.
package integrityfaults

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
)

// Snapshot is a content-addressed, point-in-time record of a directory
// tree. Every field is computed once inside Take and stored by value;
// Snapshot retains no live handle to the source directory, so a later
// mutation of that directory cannot retroactively change an
// already-returned Snapshot's Digest or Files (this is what demonstrates
// AC #2 - "a source mutation after snapshot cannot alter the declared run
// source" - structurally, not just by assertion: there is no code path in
// this package that re-reads Root after Take returns).
type Snapshot struct {
	// Root is the directory Take was pointed at, kept only for diagnostics
	// - it is never read again after Take returns.
	Root string

	// Files maps each relative file path to the sha256 hex digest of that
	// file's content at snapshot time.
	Files map[string]string

	// Digest is the snapshot's own identity: sha256 over the sorted
	// "path:digest\n" lines of Files, so two snapshots of identical
	// content produce the same Digest regardless of filesystem walk order.
	Digest string
}

// Take reads every regular file under root and returns an immutable
// Snapshot. All bytes needed to compute Files and Digest are read before
// Take returns; nothing in the returned Snapshot depends on root's
// filesystem state afterward.
func Take(root string) (Snapshot, error) {
	files := map[string]string{}
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if d.IsDir() {
			return nil
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		sum := sha256.Sum256(data)
		files[filepath.ToSlash(rel)] = hex.EncodeToString(sum[:])
		return nil
	})
	if err != nil {
		return Snapshot{}, err
	}

	paths := make([]string, 0, len(files))
	for p := range files {
		paths = append(paths, p)
	}
	sort.Strings(paths)

	h := sha256.New()
	for _, p := range paths {
		fmt.Fprintf(h, "%s:%s\n", p, files[p])
	}

	return Snapshot{
		Root:   root,
		Files:  files,
		Digest: hex.EncodeToString(h.Sum(nil)),
	}, nil
}
