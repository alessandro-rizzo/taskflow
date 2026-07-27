//go:build darwin || linux || freebsd

package file

import (
	"errors"
	"fmt"
	"os"
	"syscall"

	"github.com/alessandro-rizzo/taskflow/state"
)

type fileLock interface {
	Close() error
}

type unixLock struct {
	file *os.File
}

func acquireFileLock(path string) (fileLock, error) {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, fmt.Errorf("open run lock: %w", err)
	}
	if err := syscall.Flock(int(file.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		file.Close()
		if errors.Is(err, syscall.EWOULDBLOCK) {
			return nil, state.ErrLocked
		}
		return nil, fmt.Errorf("lock run: %w", err)
	}
	return &unixLock{file: file}, nil
}

func (l *unixLock) Close() error {
	unlockErr := syscall.Flock(int(l.file.Fd()), syscall.LOCK_UN)
	closeErr := l.file.Close()
	return errors.Join(unlockErr, closeErr)
}
