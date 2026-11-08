package main

// Rust: компилятор ставится при первом запуске кода на Rust (официальные архивы static.rust-lang.org,
// SHA-256 из манифеста стабильного канала). На Windows — сборка x86_64-pc-windows-gnu
// со своим компоновщиком (rust-mingw), чтобы не требовать Visual Studio.
// Программа ученика компилируется один раз; готовый файл лежит в cache/rust по хешу кода,
// поэтому проверка на многих тестах не компилирует заново.

import (
	"bufio"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strings"
	"sync"
	"time"
)

const rustManifest = "https://static.rust-lang.org/dist/channel-rust-stable.toml"

func rustTarget() (string, error) {
	switch runtime.GOOS + "/" + runtime.GOARCH {
	case "windows/amd64":
		return "x86_64-pc-windows-gnu", nil
	case "darwin/arm64":
		return "aarch64-apple-darwin", nil
	case "darwin/amd64":
		return "x86_64-apple-darwin", nil
	case "linux/amd64":
		return "x86_64-unknown-linux-gnu", nil
	case "linux/arm64":
		return "aarch64-unknown-linux-gnu", nil
	}
	return "", fmt.Errorf("Rust на этой системе (%s/%s) пока не поддерживается", runtime.GOOS, runtime.GOARCH)
}

func (w *Workspace) RustcExe() string {
	if runtime.GOOS == "windows" {
		return w.Path("runtimes", "rust", "bin", "rustc.exe")
	}
	return w.Path("runtimes", "rust", "bin", "rustc")
}

var rustVersionRE = regexp.MustCompile(`^version = "([0-9]+\.[0-9]+\.[0-9]+)`)

// rustPackages читает из манифеста ссылки и хеши архивов (.tar.gz) для нужных компонентов
func rustPackages(manifest []byte, target string, names []string) (version string, urls, sums []string, err error) {
	want := map[string]bool{}
	for _, n := range names {
		want[fmt.Sprintf("[pkg.%s.target.%s]", n, target)] = true
	}
	found := map[string][2]string{}
	section, inRustc := "", false
	sc := bufio.NewScanner(bytes.NewReader(manifest))
	sc.Buffer(make([]byte, 1<<20), 1<<20)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if strings.HasPrefix(line, "[") {
			section = line
			inRustc = line == "[pkg.rustc]"
			continue
		}
		if inRustc && version == "" {
			if m := rustVersionRE.FindStringSubmatch(line); m != nil {
				version = m[1]
			}
		}
		if !want[section] {
			continue
		}
		k, v, ok := strings.Cut(line, " = ")
		if !ok {
			continue
		}
		v = strings.Trim(v, `"`)
		cur := found[section]
		switch k {
		case "url":
			cur[0] = v
		case "hash":
			cur[1] = v
		}
		found[section] = cur
	}
	for _, n := range names {
		f := found[fmt.Sprintf("[pkg.%s.target.%s]", n, target)]
		if !strings.HasPrefix(f[0], "https://static.rust-lang.org/") || len(f[1]) != 64 {
			return "", nil, nil, fmt.Errorf("в манифесте Rust нет %s для %s", n, target)
		}
		urls = append(urls, f[0])
		sums = append(sums, f[1])
	}
	if version == "" {
		return "", nil, nil, fmt.Errorf("в манифесте Rust нет версии")
	}
	return version, urls, sums, nil
}

// installRust ставит rustc и стандартную библиотеку в runtimes/rust. Возвращает версию
func (in *Installer) installRust() (string, error) {
	target, err := rustTarget()
	if err != nil {
		return "", err
	}
	manifest, err := httpGet(rustManifest, 8<<20)
	if err != nil {
		return "", err
	}
	names := []string{"rustc", "rust-std"}
	if strings.HasSuffix(target, "windows-gnu") {
		names = append(names, "rust-mingw")
	}
	version, urls, sums, err := rustPackages(manifest, target, names)
	if err != nil {
		return "", err
	}
	dir := in.ws.Path("runtimes", "rust")
	_ = os.RemoveAll(dir)
	strip := rustStrip
	for i, u := range urls {
		in.setStep(fmt.Sprintf("Скачиваю Rust %s (%d из %d)", version, i+1, len(urls)))
		archive, err := download(in.ws, u, sums[i])
		if err != nil {
			return "", err
		}
		err = extract(archive, dir, strip)
		os.Remove(archive)
		if err != nil {
			return "", err
		}
	}
	return version, nil
}

// rustStrip: в архиве rustc-1.x.y-<target>/<компонент>/{bin,lib,…} — убираем две верхние папки
func rustStrip(name string) (string, bool) {
	parts := strings.SplitN(filepath.ToSlash(name), "/", 3)
	if len(parts) < 3 || parts[2] == "" {
		return "", false
	}
	return parts[2], true
}

// rustBuilds — компиляции, которые идут прямо сейчас: одинаковый код компилируется один раз
var rustBuilds sync.Map

// buildRust компилирует программу (или берёт готовую из кеша). Возвращает путь к файлу
// или текст ошибок компиляции
func (ws *Workspace) buildRust(code string) (exe string, compileErr string, err error) {
	sum := sha256.Sum256([]byte("rust-v2\n" + code))
	id := hex.EncodeToString(sum[:])[:24]
	dir := ws.Path("cache", "rust")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", "", err
	}
	exe = filepath.Join(dir, id)
	if runtime.GOOS == "windows" {
		exe += ".exe"
	}
	lock, _ := rustBuilds.LoadOrStore(id, &sync.Mutex{})
	mu := lock.(*sync.Mutex)
	mu.Lock()
	defer mu.Unlock()
	if _, err := os.Stat(exe); err == nil {
		now := time.Now()
		_ = os.Chtimes(exe, now, now)
		return exe, "", nil
	}
	src, err := os.MkdirTemp(ws.Path("cache", "tmp"), "rs-")
	if err != nil {
		return "", "", err
	}
	defer os.RemoveAll(src)
	main := filepath.Join(src, "main.rs")
	if err := os.WriteFile(main, []byte(code), 0o644); err != nil {
		return "", "", err
	}
	out := filepath.Join(src, "main.bin")
	cmd := exec.Command(ws.RustcExe(), "--edition", "2021", "-C", "opt-level=2", "-C", "debuginfo=0", "-C", "strip=symbols",
		"--color", "never", "--crate-name", "main", "--remap-path-prefix", src+"=src", "-o", out, main)
	cmd.Dir = src
	cmd.Env = ws.Env(nil)
	hideWindow(cmd)
	var msg bytes.Buffer
	cmd.Stdout = &msg
	cmd.Stderr = &msg
	if err := cmd.Start(); err != nil {
		return "", "", err
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case err = <-done:
	case <-time.After(90 * time.Second):
		_ = cmd.Process.Kill()
		<-done
		return "", "Компиляция заняла больше 90 секунд", nil
	}
	if err != nil {
		// Пути временной папки ученику не нужны
		text := strings.ReplaceAll(msg.String(), main, "main.rs")
		text = strings.ReplaceAll(text, filepath.ToSlash(main), "main.rs")
		text = strings.ReplaceAll(text, filepath.Join("src", "main.rs"), "main.rs")
		if text == "" {
			text = err.Error()
		}
		return "", text, nil
	}
	// Файл, на котором компоновщик Windows мог оставить .pdb, переносим целиком в кеш
	if err := os.Rename(out, exe); err != nil {
		return "", "", err
	}
	pruneRustCache(dir, 40)
	return exe, "", nil
}

// pruneRustCache оставляет только последние keep скомпилированных программ
func pruneRustCache(dir string, keep int) {
	entries, err := os.ReadDir(dir)
	if err != nil || len(entries) <= keep {
		return
	}
	type item struct {
		path string
		t    time.Time
	}
	var items []item
	for _, e := range entries {
		if info, err := e.Info(); err == nil && !e.IsDir() {
			items = append(items, item{filepath.Join(dir, e.Name()), info.ModTime()})
		}
	}
	sort.Slice(items, func(i, j int) bool { return items[i].t.After(items[j].t) })
	for _, it := range items[min(keep, len(items)):] {
		_ = os.Remove(it.path)
	}
}

// runRust компилирует и запускает программу на Rust с вводом stdin.
// С набором крейтов (crates: ["macroquad"]) программа собирается cargo; window — игра открывает окно.
// Время компиляции в лимит не входит; паника или ненулевой код выхода — ошибка выполнения
func (ws *Workspace) runRust(req RunRequest, runs *Runs) RunResult {
	if _, err := os.Stat(ws.RustcExe()); err != nil {
		return RunResult{Status: "env-error", Error: "not-installed"}
	}
	if err := os.MkdirAll(ws.Path("cache", "tmp"), 0o755); err != nil {
		return RunResult{Status: "env-error", Error: err.Error()}
	}
	var exe, compileErr string
	var err error
	if len(req.Crates) > 0 {
		if !ws.kitReady(req.Crates[0], ws.LoadState().Rust) {
			return RunResult{Status: "env-error", Error: "not-installed"}
		}
		exe, compileErr, err = ws.buildGame(req.Crates[0], req.Code)
	} else {
		exe, compileErr, err = ws.buildRust(req.Code)
	}
	if err != nil {
		return RunResult{Status: "env-error", Error: err.Error()}
	}
	if compileErr != "" {
		return RunResult{Status: "ce", Stderr: compileErr, Error: "Ошибка компиляции"}
	}
	tmp, err := os.MkdirTemp(ws.Path("cache", "tmp"), "run-")
	if err != nil {
		return RunResult{Status: "env-error", Error: err.Error()}
	}
	defer os.RemoveAll(tmp)

	runs.slots <- struct{}{}
	defer func() { <-runs.slots }()

	cmd := exec.Command(exe)
	cmd.Dir = tmp
	cmd.Env = ws.Env(map[string]string{"RUST_BACKTRACE": "0"})
	if !req.Window {
		// Окно игры прятать нельзя; без окна — не показываем и консоль
		hideWindow(cmd)
	}
	var mu sync.Mutex
	total, over := 0, false
	kill := func() {
		if cmd.Process != nil {
			_ = cmd.Process.Kill()
		}
	}
	stdout := &limitedBuffer{mu: &mu, total: &total, limit: req.OutputLimitBytes, over: &over, kill: kill}
	stderr := &limitedBuffer{mu: &mu, total: &total, limit: req.OutputLimitBytes, over: &over, kill: kill}
	cmd.Stdout = stdout
	cmd.Stderr = stderr
	stdinPipe, err := cmd.StdinPipe()
	if err != nil {
		return RunResult{Status: "env-error", Error: err.Error()}
	}
	start := time.Now()
	if err := cmd.Start(); err != nil {
		return RunResult{Status: "env-error", Error: err.Error()}
	}
	runs.mu.Lock()
	runs.procs[req.RunID] = cmd
	runs.mu.Unlock()
	go func() {
		_, _ = io.WriteString(stdinPipe, req.Stdin)
		_ = stdinPipe.Close()
	}()
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	timedOut := false
	var waitErr error
	select {
	case waitErr = <-done:
	case <-time.After(time.Duration(req.TimeLimitMs) * time.Millisecond):
		timedOut = true
		kill()
		<-done
	}
	elapsed := int(time.Since(start) / time.Millisecond)
	runs.mu.Lock()
	delete(runs.procs, req.RunID)
	cancelled := runs.cancelled[req.RunID]
	delete(runs.cancelled, req.RunID)
	runs.mu.Unlock()

	mu.Lock()
	out, errOut, isOver := string(stdout.buf), string(stderr.buf), over
	mu.Unlock()
	out = strings.ToValidUTF8(out, "�")
	errOut = strings.ToValidUTF8(errOut, "�")
	switch {
	case cancelled:
		return RunResult{Status: "cancelled"}
	case isOver:
		return RunResult{Status: "ole"}
	case timedOut:
		return RunResult{Status: "tle", Stdout: out, Stderr: errOut, TimeMs: req.TimeLimitMs}
	case waitErr != nil:
		code := -1
		if cmd.ProcessState != nil {
			code = cmd.ProcessState.ExitCode()
		}
		msg := fmt.Sprintf("Программа аварийно завершилась (код %d)", code)
		if code == 101 {
			msg = "Программа завершилась с паникой (panic)"
		}
		return RunResult{Status: "re", Stdout: out, Stderr: errOut, TimeMs: elapsed, Error: msg}
	}
	return RunResult{Status: "ok", Stdout: out, Stderr: errOut, TimeMs: elapsed}
}
