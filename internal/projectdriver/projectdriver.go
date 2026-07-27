// Package projectdriver locates, fingerprints, builds, and invokes a
// project-local .taskflow package.
package projectdriver

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"time"

	"github.com/alessandro-rizzo/taskflow/driver"
)

type Loader struct {
	Version string
	// CacheDir overrides the platform cache directory, primarily for hermetic
	// embedding and tests.
	CacheDir string
	Stdin    io.Reader
	Stdout   io.Writer
	Stderr   io.Writer
}

func FindRoot(start string) (string, error) {
	current, err := filepath.Abs(start)
	if err != nil {
		return "", err
	}
	for {
		info, err := os.Stat(filepath.Join(current, ".taskflow"))
		if err == nil && info.IsDir() {
			return current, nil
		}
		if err != nil && !errors.Is(err, os.ErrNotExist) {
			return "", err
		}
		parent := filepath.Dir(current)
		if parent == current {
			return "", errors.New("no .taskflow package found in this directory or its parents")
		}
		current = parent
	}
}

func (l Loader) Build(ctx context.Context, root string) (string, error) {
	digest, err := l.sourceDigest(ctx, root)
	if err != nil {
		return "", err
	}
	cacheRoot := l.CacheDir
	if cacheRoot == "" {
		cacheRoot, err = os.UserCacheDir()
		if err != nil {
			return "", fmt.Errorf("locate user cache: %w", err)
		}
	}
	directory := filepath.Join(cacheRoot, "taskflow", "drivers", digest)
	binary := filepath.Join(directory, "taskflow-driver")
	if runtime.GOOS == "windows" {
		binary += ".exe"
	}
	if info, err := os.Stat(binary); err == nil && info.Mode().IsRegular() {
		return binary, nil
	}
	if err := os.MkdirAll(directory, 0o700); err != nil {
		return "", fmt.Errorf("create driver cache: %w", err)
	}
	temporary, err := os.CreateTemp(directory, ".driver-*")
	if err != nil {
		return "", fmt.Errorf("create driver target: %w", err)
	}
	temporaryPath := temporary.Name()
	if err := temporary.Close(); err != nil {
		os.Remove(temporaryPath)
		return "", err
	}
	defer os.Remove(temporaryPath)
	command := exec.CommandContext(ctx, "go", "build", "-o", temporaryPath, "./.taskflow")
	command.Dir = root
	command.Stdout = l.Stdout
	command.Stderr = l.Stderr
	if err := command.Run(); err != nil {
		return "", fmt.Errorf("compile .taskflow driver: %w", err)
	}
	if err := os.Chmod(temporaryPath, 0o700); err != nil {
		return "", fmt.Errorf("make driver executable: %w", err)
	}
	if err := os.Rename(temporaryPath, binary); err != nil {
		return "", fmt.Errorf("publish compiled driver: %w", err)
	}
	return binary, nil
}

func (l Loader) SourceDigest(root string) (string, error) {
	return l.sourceDigest(context.Background(), root)
}

func (l Loader) sourceDigest(ctx context.Context, root string) (string, error) {
	files, err := mainModuleDependencyFiles(ctx, root)
	if err != nil {
		return "", err
	}
	for _, name := range []string{"go.mod", "go.sum", "go.work", "go.work.sum"} {
		path := filepath.Join(root, name)
		if _, err := os.Stat(path); err == nil {
			files = append(files, path)
		} else if !errors.Is(err, os.ErrNotExist) {
			return "", err
		}
	}
	sort.Strings(files)
	hash := sha256.New()
	for _, fragment := range []string{
		"taskflow-driver-cache-v1",
		l.Version,
		fmt.Sprintf("protocol=%d", driver.ProtocolVersion),
		runtime.GOOS,
		runtime.GOARCH,
		runtime.Version(),
	} {
		writeFragment(hash, []byte(fragment))
	}
	for _, path := range files {
		relative, err := filepath.Rel(root, path)
		if err != nil {
			return "", err
		}
		contents, err := os.ReadFile(path)
		if err != nil {
			return "", fmt.Errorf("read driver input %s: %w", relative, err)
		}
		writeFragment(hash, []byte(filepath.ToSlash(relative)))
		writeFragment(hash, contents)
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

type listedPackage struct {
	Dir      string
	Standard bool
	Module   *struct {
		Main bool
	}
	GoFiles      []string
	CgoFiles     []string
	CFiles       []string
	CXXFiles     []string
	MFiles       []string
	HFiles       []string
	FFiles       []string
	SFiles       []string
	SwigFiles    []string
	SwigCXXFiles []string
	SysoFiles    []string
	EmbedFiles   []string
}

func mainModuleDependencyFiles(ctx context.Context, root string) ([]string, error) {
	command := exec.CommandContext(ctx, "go", "list", "-deps", "-json", "./.taskflow")
	command.Dir = root
	var output, stderr bytes.Buffer
	command.Stdout = &output
	command.Stderr = &stderr
	if err := command.Run(); err != nil {
		return nil, fmt.Errorf("inspect .taskflow dependencies: %w: %s", err, stderr.String())
	}
	files := make(map[string]struct{})
	decoder := json.NewDecoder(&output)
	for {
		var pkg listedPackage
		err := decoder.Decode(&pkg)
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return nil, fmt.Errorf("decode .taskflow dependency: %w", err)
		}
		if pkg.Standard || pkg.Module == nil || !pkg.Module.Main {
			continue
		}
		for _, names := range [][]string{
			pkg.GoFiles,
			pkg.CgoFiles,
			pkg.CFiles,
			pkg.CXXFiles,
			pkg.MFiles,
			pkg.HFiles,
			pkg.FFiles,
			pkg.SFiles,
			pkg.SwigFiles,
			pkg.SwigCXXFiles,
			pkg.SysoFiles,
			pkg.EmbedFiles,
		} {
			for _, name := range names {
				files[filepath.Join(pkg.Dir, name)] = struct{}{}
			}
		}
	}
	result := make([]string, 0, len(files))
	for file := range files {
		result = append(result, file)
	}
	sort.Strings(result)
	return result, nil
}

func (l Loader) Run(ctx context.Context, root, binary string, args []string) error {
	handshake := exec.CommandContext(ctx, binary, driver.HandshakeCommand)
	handshake.Dir = root
	handshake.Stderr = l.Stderr
	output, err := handshake.StdoutPipe()
	if err != nil {
		return err
	}
	if err := handshake.Start(); err != nil {
		return fmt.Errorf("start driver handshake: %w", err)
	}
	var response driver.Handshake
	decodeErr := json.NewDecoder(bufio.NewReader(output)).Decode(&response)
	waitErr := handshake.Wait()
	if err := errors.Join(decodeErr, waitErr); err != nil {
		return fmt.Errorf("driver handshake failed: %w", err)
	}
	if response.Protocol != driver.ProtocolVersion {
		return fmt.Errorf(
			"driver protocol %d is incompatible with CLI protocol %d; align the project Taskflow SDK and CLI versions",
			response.Protocol,
			driver.ProtocolVersion,
		)
	}
	command := exec.Command(binary, args...)
	command.Dir = root
	command.Stdin = l.Stdin
	command.Stdout = l.Stdout
	command.Stderr = l.Stderr
	if err := command.Start(); err != nil {
		return fmt.Errorf("start project driver: %w", err)
	}
	waited := make(chan error, 1)
	go func() {
		waited <- command.Wait()
	}()
	var runErr error
	select {
	case runErr = <-waited:
	case <-ctx.Done():
		_ = command.Process.Signal(os.Interrupt)
		timer := time.NewTimer(45 * time.Second)
		select {
		case runErr = <-waited:
			if !timer.Stop() {
				<-timer.C
			}
		case <-timer.C:
			_ = command.Process.Kill()
			runErr = <-waited
		}
	}
	if runErr != nil {
		var exitError *exec.ExitError
		if errors.As(runErr, &exitError) {
			return &ExitError{Code: exitError.ExitCode()}
		}
		return fmt.Errorf("run project driver: %w", runErr)
	}
	return nil
}

type ExitError struct {
	Code int
}

func (e *ExitError) Error() string {
	return fmt.Sprintf("project driver exited with status %d", e.Code)
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
