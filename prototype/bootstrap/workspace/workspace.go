// Package workspace provides deterministic matching, hashing, and tar transfer
// below a workspace root.
package workspace

import (
	"archive/tar"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

func Match(root string, patterns []string) ([]string, error) {
	root, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	matched := make(map[string]struct{})
	err = filepath.WalkDir(root, func(filePath string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if filePath == root {
			return nil
		}
		relative, err := filepath.Rel(root, filePath)
		if err != nil {
			return err
		}
		relative = filepath.ToSlash(relative)
		for _, pattern := range patterns {
			ok, err := match(pattern, relative)
			if err != nil {
				return err
			}
			if ok {
				matched[relative] = struct{}{}
				break
			}
		}
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("match workspace paths: %w", err)
	}
	paths := make([]string, 0, len(matched))
	for value := range matched {
		paths = append(paths, value)
	}
	sort.Strings(paths)
	return paths, nil
}

func Digest(ctx context.Context, root string, patterns []string) (string, error) {
	paths, err := Match(root, patterns)
	if err != nil {
		return "", err
	}
	hash := sha256.New()
	for _, relative := range paths {
		if err := ctx.Err(); err != nil {
			return "", err
		}
		full := filepath.Join(root, filepath.FromSlash(relative))
		info, err := os.Lstat(full)
		if err != nil {
			return "", fmt.Errorf("stat input %s: %w", relative, err)
		}
		writeFragment(hash, []byte(relative))
		writeFragment(hash, []byte(info.Mode().String()))
		if info.Mode()&os.ModeSymlink != 0 {
			target, err := os.Readlink(full)
			if err != nil {
				return "", fmt.Errorf("read input symlink %s: %w", relative, err)
			}
			writeFragment(hash, []byte(target))
			continue
		}
		if !info.Mode().IsRegular() {
			continue
		}
		writeFragment(hash, []byte(fmt.Sprintf("%d", info.Size())))
		file, err := os.Open(full)
		if err != nil {
			return "", fmt.Errorf("open input %s: %w", relative, err)
		}
		if _, err := io.Copy(hash, file); err != nil {
			file.Close()
			return "", fmt.Errorf("hash input %s: %w", relative, err)
		}
		if err := file.Close(); err != nil {
			return "", fmt.Errorf("close input %s: %w", relative, err)
		}
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func Pack(ctx context.Context, root string, patterns []string, destination io.Writer) error {
	paths, err := Match(root, patterns)
	if err != nil {
		return err
	}
	writer := tar.NewWriter(destination)
	for _, relative := range paths {
		if err := ctx.Err(); err != nil {
			writer.Close()
			return err
		}
		full := filepath.Join(root, filepath.FromSlash(relative))
		info, err := os.Lstat(full)
		if err != nil {
			writer.Close()
			return fmt.Errorf("stat output %s: %w", relative, err)
		}
		var link string
		if info.Mode()&os.ModeSymlink != 0 {
			link, err = os.Readlink(full)
			if err != nil {
				writer.Close()
				return fmt.Errorf("read output symlink %s: %w", relative, err)
			}
			if _, err := resolvedLink(relative, link); err != nil {
				writer.Close()
				return err
			}
		}
		header, err := tar.FileInfoHeader(info, link)
		if err != nil {
			writer.Close()
			return fmt.Errorf("create output header %s: %w", relative, err)
		}
		header.Name = relative
		header.Uid, header.Gid = 0, 0
		header.Uname, header.Gname = "", ""
		header.ModTime = time.Unix(0, 0).UTC()
		header.AccessTime = time.Time{}
		header.ChangeTime = time.Time{}
		if err := writer.WriteHeader(header); err != nil {
			writer.Close()
			return fmt.Errorf("write output header %s: %w", relative, err)
		}
		if !info.Mode().IsRegular() {
			continue
		}
		file, err := os.Open(full)
		if err != nil {
			writer.Close()
			return fmt.Errorf("open output %s: %w", relative, err)
		}
		if _, err := io.Copy(writer, file); err != nil {
			file.Close()
			writer.Close()
			return fmt.Errorf("archive output %s: %w", relative, err)
		}
		if err := file.Close(); err != nil {
			writer.Close()
			return fmt.Errorf("close output %s: %w", relative, err)
		}
	}
	if err := writer.Close(); err != nil {
		return fmt.Errorf("close output archive: %w", err)
	}
	return nil
}

func Extract(ctx context.Context, root string, source io.Reader) error {
	if err := os.MkdirAll(root, 0o755); err != nil {
		return fmt.Errorf("create workspace root: %w", err)
	}
	root, err := filepath.EvalSymlinks(root)
	if err != nil {
		return fmt.Errorf("resolve workspace root: %w", err)
	}
	reader := tar.NewReader(source)
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		header, err := reader.Next()
		if errors.Is(err, io.EOF) {
			return nil
		}
		if err != nil {
			return fmt.Errorf("read archive: %w", err)
		}
		relative, err := cleanArchivePath(header.Name)
		if err != nil {
			return err
		}
		full := filepath.Join(root, filepath.FromSlash(relative))
		if !below(root, full) {
			return fmt.Errorf("archive path %q escapes workspace", header.Name)
		}
		if err := ensureSafeParent(root, relative); err != nil {
			return err
		}
		mode := fs.FileMode(header.Mode) & fs.ModePerm
		switch header.Typeflag {
		case tar.TypeDir:
			if info, statErr := os.Lstat(full); statErr == nil && !info.IsDir() {
				if err := os.RemoveAll(full); err != nil {
					return fmt.Errorf("replace archive directory %s: %w", relative, err)
				}
			} else if statErr != nil && !errors.Is(statErr, os.ErrNotExist) {
				return fmt.Errorf("inspect archive directory %s: %w", relative, statErr)
			}
			if err := os.MkdirAll(full, mode); err != nil {
				return fmt.Errorf("create archive directory %s: %w", relative, err)
			}
			if err := os.Chmod(full, mode); err != nil {
				return fmt.Errorf("set archive directory mode %s: %w", relative, err)
			}
		case tar.TypeReg, tar.TypeRegA:
			if err := removeExisting(full); err != nil {
				return fmt.Errorf("replace archive file %s: %w", relative, err)
			}
			file, err := os.OpenFile(full, os.O_CREATE|os.O_EXCL|os.O_WRONLY, mode)
			if err != nil {
				return fmt.Errorf("create archive file %s: %w", relative, err)
			}
			if _, err := io.Copy(file, reader); err != nil {
				file.Close()
				return fmt.Errorf("extract archive file %s: %w", relative, err)
			}
			if err := file.Close(); err != nil {
				return fmt.Errorf("close archive file %s: %w", relative, err)
			}
		case tar.TypeSymlink:
			if _, err := resolvedLink(relative, header.Linkname); err != nil {
				return err
			}
			if err := removeExisting(full); err != nil {
				return fmt.Errorf("replace archive symlink %s: %w", relative, err)
			}
			if err := os.Symlink(header.Linkname, full); err != nil {
				return fmt.Errorf("create archive symlink %s: %w", relative, err)
			}
		case tar.TypeLink:
			link, err := cleanArchivePath(header.Linkname)
			if err != nil {
				return fmt.Errorf("archive hard link %q: %w", header.Name, err)
			}
			if err := ensureSafeParent(root, link); err != nil {
				return err
			}
			sourcePath := filepath.Join(root, filepath.FromSlash(link))
			info, err := os.Lstat(sourcePath)
			if err != nil || !info.Mode().IsRegular() {
				return fmt.Errorf("archive hard link target %q is not a regular extracted file", header.Linkname)
			}
			if err := removeExisting(full); err != nil {
				return fmt.Errorf("replace archive hard link %s: %w", relative, err)
			}
			if err := os.Link(sourcePath, full); err != nil {
				return fmt.Errorf("create archive hard link %s: %w", relative, err)
			}
		default:
			return fmt.Errorf("unsupported archive entry type %d for %s", header.Typeflag, relative)
		}
	}
}

// NormalizeArchive validates an archive, optionally filters it using Taskflow
// workspace patterns, and emits deterministic safe headers.
func NormalizeArchive(
	ctx context.Context,
	source io.Reader,
	patterns []string,
	destination io.Writer,
) error {
	reader := tar.NewReader(source)
	writer := tar.NewWriter(destination)
	symlinks := make(map[string]struct{})
	written := make(map[string]struct{})
	for {
		if err := ctx.Err(); err != nil {
			writer.Close()
			return err
		}
		header, err := reader.Next()
		if errors.Is(err, io.EOF) {
			if err := writer.Close(); err != nil {
				return fmt.Errorf("close normalized archive: %w", err)
			}
			return nil
		}
		if err != nil {
			writer.Close()
			return fmt.Errorf("read transport archive: %w", err)
		}
		relative := path.Clean(strings.ReplaceAll(header.Name, "\\", "/"))
		if relative == "." {
			continue
		}
		relative, err = cleanArchivePath(relative)
		if err != nil {
			writer.Close()
			return err
		}
		if ancestor, ok := symlinkAncestor(relative, symlinks); ok {
			writer.Close()
			return fmt.Errorf("archive path %q traverses symlink %q", relative, ancestor)
		}
		include := len(patterns) == 0
		for _, pattern := range patterns {
			matched, matchErr := match(pattern, relative)
			if matchErr != nil {
				writer.Close()
				return fmt.Errorf("match archive path %s: %w", relative, matchErr)
			}
			if matched {
				include = true
				break
			}
		}
		switch header.Typeflag {
		case tar.TypeDir, tar.TypeReg, tar.TypeRegA:
		case tar.TypeSymlink:
			if _, err := resolvedLink(relative, header.Linkname); err != nil {
				writer.Close()
				return err
			}
			symlinks[relative] = struct{}{}
		case tar.TypeLink:
			if !include {
				continue
			}
			link, err := cleanArchivePath(header.Linkname)
			if err != nil {
				writer.Close()
				return err
			}
			if _, ok := written[link]; !ok {
				writer.Close()
				return fmt.Errorf("archive hard link %q precedes or excludes target %q", relative, link)
			}
			header.Linkname = link
		default:
			if !include {
				continue
			}
			writer.Close()
			return fmt.Errorf("unsupported archive entry type %d for %s", header.Typeflag, relative)
		}
		if !include {
			continue
		}
		copy := *header
		copy.Name = relative
		copy.Mode &= 0o777
		copy.Uid, copy.Gid = 0, 0
		copy.Uname, copy.Gname = "", ""
		copy.ModTime = time.Unix(0, 0).UTC()
		copy.AccessTime = time.Time{}
		copy.ChangeTime = time.Time{}
		copy.PAXRecords = nil
		copy.Xattrs = nil
		if err := writer.WriteHeader(&copy); err != nil {
			writer.Close()
			return fmt.Errorf("write normalized archive header %s: %w", relative, err)
		}
		if header.Typeflag == tar.TypeReg || header.Typeflag == tar.TypeRegA {
			if _, err := io.Copy(writer, reader); err != nil {
				writer.Close()
				return fmt.Errorf("write normalized archive file %s: %w", relative, err)
			}
		}
		written[relative] = struct{}{}
	}
}

func match(pattern, value string) (bool, error) {
	return matchSegments(strings.Split(pattern, "/"), strings.Split(value, "/"))
}

func matchSegments(pattern, value []string) (bool, error) {
	if len(pattern) == 0 {
		return len(value) == 0, nil
	}
	if pattern[0] == "**" {
		for consumed := 0; consumed <= len(value); consumed++ {
			ok, err := matchSegments(pattern[1:], value[consumed:])
			if err != nil || ok {
				return ok, err
			}
		}
		return false, nil
	}
	if len(value) == 0 {
		return false, nil
	}
	ok, err := path.Match(pattern[0], value[0])
	if err != nil || !ok {
		return false, err
	}
	return matchSegments(pattern[1:], value[1:])
}

func writeFragment(writer io.Writer, value []byte) {
	var length [8]byte
	size := uint64(len(value))
	for index := 7; index >= 0; index-- {
		length[index] = byte(size)
		size >>= 8
	}
	_, _ = writer.Write(length[:])
	_, _ = writer.Write(value)
}

func below(root, candidate string) bool {
	relative, err := filepath.Rel(root, candidate)
	return err == nil && relative != ".." && !strings.HasPrefix(relative, ".."+string(filepath.Separator))
}

func cleanArchivePath(value string) (string, error) {
	relative := path.Clean(strings.ReplaceAll(value, "\\", "/"))
	if relative == "." || relative == ".." ||
		strings.HasPrefix(relative, "../") || path.IsAbs(relative) {
		return "", fmt.Errorf("archive path %q escapes workspace", value)
	}
	return relative, nil
}

func resolvedLink(relative, linkname string) (string, error) {
	link := path.Clean(strings.ReplaceAll(linkname, "\\", "/"))
	if path.IsAbs(link) {
		return "", fmt.Errorf("archive symlink %q has absolute target %q", relative, linkname)
	}
	resolved := path.Clean(path.Join(path.Dir(relative), link))
	if resolved == ".." || strings.HasPrefix(resolved, "../") || path.IsAbs(resolved) {
		return "", fmt.Errorf("archive symlink %q escapes workspace through %q", relative, linkname)
	}
	return resolved, nil
}

func ensureSafeParent(root, relative string) error {
	current := root
	parent := path.Dir(relative)
	if parent == "." {
		return nil
	}
	for _, segment := range strings.Split(parent, "/") {
		current = filepath.Join(current, filepath.FromSlash(segment))
		info, err := os.Lstat(current)
		if errors.Is(err, os.ErrNotExist) {
			if err := os.Mkdir(current, 0o755); err != nil && !errors.Is(err, os.ErrExist) {
				return fmt.Errorf("create archive parent %s: %w", parent, err)
			}
			continue
		}
		if err != nil {
			return fmt.Errorf("inspect archive parent %s: %w", parent, err)
		}
		if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
			return fmt.Errorf("archive parent %q is not a safe directory", filepath.ToSlash(current))
		}
	}
	return nil
}

func removeExisting(full string) error {
	_, err := os.Lstat(full)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	return os.RemoveAll(full)
}

func symlinkAncestor(relative string, symlinks map[string]struct{}) (string, bool) {
	current := path.Dir(relative)
	for current != "." && current != "/" {
		if _, ok := symlinks[current]; ok {
			return current, true
		}
		current = path.Dir(current)
	}
	return "", false
}
