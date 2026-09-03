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
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
)

// ErrSnapshotSymlink reports that Take encountered a symbolic link. This
// fixture deliberately rejects every symlink rather than defining whether a
// future production snapshot should preserve the link or follow an in-root
// target.
var ErrSnapshotSymlink = errors.New("symbolic links are not supported in snapshots")

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

// Take reads every non-directory, non-symlink entry under root and returns an
// immutable Snapshot. The supplied root itself and every descendant symlink
// are rejected, whether their targets are in-root, out-of-root, or dangling.
// All bytes needed to compute Files and Digest are read before Take returns;
// nothing in the returned Snapshot depends on root's filesystem state
// afterward.
//
// This toy fixture does not provide an atomic filesystem snapshot. The rooted
// operations prevent a descendant path from escaping root while it is read,
// but concurrent in-root mutation can still make one Take observe entries at
// different points in time.
func Take(root string) (Snapshot, error) {
	rootInfo, err := os.Lstat(root)
	if err != nil {
		return Snapshot{}, fmt.Errorf("snapshot root: %w", err)
	}
	if rootInfo.Mode()&fs.ModeSymlink != 0 {
		return Snapshot{}, snapshotSymlinkError(".")
	}
	if !rootInfo.IsDir() {
		return Snapshot{}, fmt.Errorf("snapshot root %q is not a directory", root)
	}

	rooted, err := os.OpenRoot(root)
	if err != nil {
		return Snapshot{}, fmt.Errorf("open snapshot root: %w", err)
	}
	defer rooted.Close()
	openedRootInfo, err := rooted.Stat(".")
	if err != nil {
		return Snapshot{}, fmt.Errorf("inspect opened snapshot root: %w", err)
	}
	if !os.SameFile(rootInfo, openedRootInfo) {
		return Snapshot{}, errors.New("snapshot root changed while it was being opened")
	}

	files := map[string]string{}
	err = fs.WalkDir(rooted.FS(), ".", func(path string, _ fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		rel := filepath.ToSlash(path)
		info, err := rooted.Lstat(path)
		if err != nil {
			return fmt.Errorf("inspect snapshot path %q: %w", rel, err)
		}
		if info.Mode()&fs.ModeSymlink != 0 {
			return snapshotSymlinkError(rel)
		}
		if info.IsDir() {
			return nil
		}
		data, err := rooted.ReadFile(path)
		if err != nil {
			return fmt.Errorf("read snapshot path %q: %w", rel, err)
		}
		sum := sha256.Sum256(data)
		files[rel] = hex.EncodeToString(sum[:])
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

func snapshotSymlinkError(rel string) error {
	return fmt.Errorf("snapshot path %q: %w", rel, ErrSnapshotSymlink)
}
