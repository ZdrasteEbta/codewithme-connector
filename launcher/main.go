// Запускалка CodeWithMe IDE для Windows: одним файлом, но быстрая.
// Приложение лежит внутри архивом и распаковывается только при первом запуске версии в
// %USERPROFILE%\.codewithme\ide\<версия>. Дальше каждый запуск — сразу готовая папка,
// без распаковки 50 МБ во временную папку, как было у PyInstaller «одним файлом».
package main

import (
	"archive/zip"
	"bytes"
	_ "embed"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"
)

//go:embed app.zip
var app []byte

var version = "dev" // при сборке: -ldflags "-X main.version=…"

const exeName = "CodeWithMe-IDE.exe"
const doneMark = ".unpacked"

func main() {
	base := os.Getenv("CWM_HOME") // для проверок; обычно папка пользователя
	if base == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			fail("Не найдена папка пользователя: " + err.Error())
			return
		}
		base = filepath.Join(home, ".codewithme")
	}
	root := filepath.Join(base, "ide")
	dir := filepath.Join(root, version)
	if !ready(dir) {
		if err := unpack(root, dir); err != nil {
			fail("Не удалось подготовить CodeWithMe IDE:\n" + err.Error())
			return
		}
		cleanOld(root, version)
	}
	cmd := exec.Command(filepath.Join(dir, exeName), os.Args[1:]...)
	cmd.Dir = dir
	if err := cmd.Start(); err != nil {
		fail("Не удалось запустить CodeWithMe IDE:\n" + err.Error())
	}
}

func ready(dir string) bool {
	for _, name := range []string{doneMark, exeName} {
		if _, err := os.Stat(filepath.Join(dir, name)); err != nil {
			return false
		}
	}
	return true
}

// unpack распаковывает во временную папку рядом и только потом переименовывает:
// оборванная распаковка не оставит «готовую» папку без файлов
func unpack(root, dir string) error {
	if err := os.MkdirAll(root, 0o755); err != nil {
		return err
	}
	tmp, err := os.MkdirTemp(root, ".unpack-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(tmp)
	zr, err := zip.NewReader(bytes.NewReader(app), int64(len(app)))
	if err != nil {
		return err
	}
	// Сначала папки, потом файлы в несколько потоков: так распаковка в разы быстрее
	var files []*zip.File
	for _, f := range zr.File {
		target := filepath.Join(tmp, filepath.FromSlash(f.Name))
		if !strings.HasPrefix(target, tmp+string(os.PathSeparator)) {
			continue // путь вне папки в архиве не принимаем
		}
		dir := target
		if !f.FileInfo().IsDir() {
			dir = filepath.Dir(target)
			files = append(files, f)
		}
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return err
		}
	}
	jobs := make(chan *zip.File)
	errs := make(chan error, len(files))
	var wg sync.WaitGroup
	for w := 0; w < max(2, runtime.NumCPU()); w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for f := range jobs {
				errs <- extract(f, filepath.Join(tmp, filepath.FromSlash(f.Name)))
			}
		}()
	}
	for _, f := range files {
		jobs <- f
	}
	close(jobs)
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			return err
		}
	}
	if err := os.WriteFile(filepath.Join(tmp, doneMark), []byte(version), 0o644); err != nil {
		return err
	}
	_ = os.RemoveAll(dir) // недоделанная папка от прошлой попытки
	if err := os.Rename(tmp, dir); err != nil {
		if ready(dir) { // параллельный запуск успел раньше
			return nil
		}
		return err
	}
	return nil
}

func extract(f *zip.File, target string) error {
	src, err := f.Open()
	if err != nil {
		return err
	}
	defer src.Close()
	dst, err := os.Create(target)
	if err != nil {
		return err
	}
	if _, err := io.Copy(dst, src); err != nil {
		dst.Close()
		return err
	}
	return dst.Close()
}

// cleanOld удаляет папки старых версий. Папку открытого окна Windows не даст
// переименовать (её библиотеки заняты) — такую не трогаем, уберём в следующий раз
func cleanOld(root, keep string) {
	entries, err := os.ReadDir(root)
	if err != nil {
		return
	}
	for _, e := range entries {
		if !e.IsDir() || e.Name() == keep {
			continue
		}
		old := filepath.Join(root, e.Name())
		if strings.HasPrefix(e.Name(), ".unpack-") || strings.HasPrefix(e.Name(), ".old-") {
			// свежую .unpack- может прямо сейчас заполнять второй запуск
			if info, err := e.Info(); err == nil && time.Since(info.ModTime()) > 10*time.Minute {
				_ = os.RemoveAll(old)
			}
			continue
		}
		gone := filepath.Join(root, ".old-"+e.Name())
		if os.Rename(old, gone) == nil {
			_ = os.RemoveAll(gone)
		}
	}
}

func fail(text string) {
	user32 := syscall.NewLazyDLL("user32.dll")
	box := user32.NewProc("MessageBoxW")
	title, _ := syscall.UTF16PtrFromString("CodeWithMe IDE")
	body, _ := syscall.UTF16PtrFromString(text)
	_, _, _ = box.Call(0, uintptr(unsafe.Pointer(body)), uintptr(unsafe.Pointer(title)), 0x10)
}
