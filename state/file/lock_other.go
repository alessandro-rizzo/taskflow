//go:build !darwin && !linux && !freebsd

package file

import (
	"errors"
	"os"

	"github.com/arr/taskflow/state"
)

type fileLock interface {
	Close() error
}

type exclusiveFileLock struct {
	file *os.File
	path string
}

func acquireFileLock(path string) (fileLock, error) {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_RDWR, 0o600)
	if errors.Is(err, os.ErrExist) {
		return nil, state.ErrLocked
	}
	if err != nil {
		return nil, err
	}
	return &exclusiveFileLock{file: file, path: path}, nil
}

func (l *exclusiveFileLock) Close() error {
	return errors.Join(l.file.Close(), os.Remove(l.path))
}
