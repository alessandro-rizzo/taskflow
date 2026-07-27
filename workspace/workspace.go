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
	root, err := filepath.Abs(root)
	if err != nil {
		return err
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
		relative := path.Clean(strings.ReplaceAll(header.Name, "\\", "/"))
		if relative == "." || strings.HasPrefix(relative, "../") || path.IsAbs(relative) {
			return fmt.Errorf("archive path %q escapes workspace", header.Name)
		}
		full := filepath.Join(root, filepath.FromSlash(relative))
		if !below(root, full) {
			return fmt.Errorf("archive path %q escapes workspace", header.Name)
		}
		switch header.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(full, fs.FileMode(header.Mode)); err != nil {
				return fmt.Errorf("create archive directory %s: %w", relative, err)
			}
		case tar.TypeReg, tar.TypeRegA:
			if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
				return err
			}
			file, err := os.OpenFile(full, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, fs.FileMode(header.Mode))
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
			target := path.Clean(strings.ReplaceAll(header.Linkname, "\\", "/"))
			if path.IsAbs(target) || strings.HasPrefix(target, "../") {
				return fmt.Errorf("archive symlink %q escapes workspace", header.Name)
			}
			if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
				return err
			}
			if err := os.Symlink(header.Linkname, full); err != nil {
				return fmt.Errorf("create archive symlink %s: %w", relative, err)
			}
		default:
			return fmt.Errorf("unsupported archive entry type %d for %s", header.Typeflag, relative)
		}
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
