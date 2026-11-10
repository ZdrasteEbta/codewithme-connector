package main

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

// RunFileRequest — запуск любого файла из IDE прямо в его папке, как в обычном редакторе:
// соседние модули импортируются, файлы с данными находятся по относительным путям
type RunFileRequest struct {
	RunID            string `json:"runId"`
	Path             string `json:"path"`
	Stdin            string `json:"stdin"`
	TimeLimitMs      int    `json:"timeLimitMs"`
	OutputLimitBytes int    `json:"outputLimitBytes"`
	// Interactive — ввод не закрывается сразу: IDE досылает строки через /app/run-io,
	// пока программа работает, а вывод забирает по кусочкам, как в терминале
	Interactive bool `json:"interactive"`
}

// liveRun — запущенная интерактивно программа: её вывод на лету и открытый ввод
type liveRun struct {
	mu       *sync.Mutex
	stdout   *limitedBuffer
	stderr   *limitedBuffer
	stdin    io.WriteCloser
	inMu     sync.Mutex
	finished bool
}

// RunIORequest — ввод для программы и места, с которых IDE ещё не видела вывод
type RunIORequest struct {
	RunID   string `json:"runId"`
	Input   string `json:"input"`
	EOF     bool   `json:"eof"`
	OutFrom int    `json:"outFrom"`
	ErrFrom int    `json:"errFrom"`
}

type RunIOReply struct {
	Known  bool   `json:"known"`
	Done   bool   `json:"done"`
	Out    string `json:"out"`
	Err    string `json:"err"`
	OutPos int    `json:"outPos"`
	ErrPos int    `json:"errPos"`
}

// tail — вывод после from, без последней недописанной буквы (UTF-8 приходит кусками)
func tail(buf []byte, from int) (string, int) {
	if from < 0 || from > len(buf) {
		from = len(buf)
	}
	end := len(buf)
	for k := 0; k < 3 && end > from && !utf8.Valid(buf[from:end]); k++ {
		end--
	}
	if !utf8.Valid(buf[from:end]) {
		end = len(buf)
	}
	return strings.ToValidUTF8(string(buf[from:end]), "�"), end
}

// IO — отдаёт новый вывод и передаёт ввод интерактивной программе
func (r *Runs) IO(req RunIORequest) RunIOReply {
	r.mu.Lock()
	live := r.live[req.RunID]
	r.mu.Unlock()
	if live == nil {
		return RunIOReply{}
	}
	if (req.Input != "" || req.EOF) && live.stdin != nil {
		go func() {
			live.inMu.Lock()
			defer live.inMu.Unlock()
			if req.Input != "" {
				_, _ = io.WriteString(live.stdin, req.Input)
			}
			if req.EOF {
				_ = live.stdin.Close()
			}
		}()
	}
	live.mu.Lock()
	out, outPos := tail(live.stdout.buf, req.OutFrom)
	errOut, errPos := tail(live.stderr.buf, req.ErrFrom)
	done := live.finished && outPos == len(live.stdout.buf) && errPos == len(live.stderr.buf)
	live.mu.Unlock()
	if done {
		r.mu.Lock()
		delete(r.live, req.RunID)
		r.mu.Unlock()
	}
	return RunIOReply{Known: true, Done: done, Out: out, Err: errOut, OutPos: outPos, ErrPos: errPos}
}

const maxFileRunMs = 10 * 60 * 1000

// fileLanguage — язык по расширению файла; пустая строка — такой файл запускать не умеем
func fileLanguage(path string) string {
	switch strings.ToLower(filepath.Ext(path)) {
	case ".py", ".pyw":
		return "python"
	case ".js", ".mjs", ".cjs":
		return "node"
	case ".rs":
		return "rust"
	}
	return ""
}

func (ws *Workspace) RunFile(req RunFileRequest, runs *Runs) RunResult {
	info, err := os.Stat(req.Path)
	if err != nil || info.IsDir() {
		return RunResult{Status: "env-error", Error: "no-file"}
	}
	dir := filepath.Dir(req.Path)
	var exe string
	var args []string
	extra := map[string]string{}
	switch fileLanguage(req.Path) {
	case "python":
		exe = ws.PythonExe()
		args = []string{"-X", "utf8", "-u", req.Path}
		extra["PYTHONIOENCODING"] = "utf-8"
		extra["PYTHONDONTWRITEBYTECODE"] = "1" // без папок __pycache__ в проекте ученика
	case "node":
		exe = ws.NodeExe()
		args = []string{req.Path}
	case "rust":
		if _, err := os.Stat(ws.RustcExe()); err != nil {
			return RunResult{Status: "env-error", Error: "not-installed"}
		}
		if err := os.MkdirAll(ws.Path("cache", "tmp"), 0o755); err != nil {
			return RunResult{Status: "env-error", Error: err.Error()}
		}
		code, err := os.ReadFile(req.Path)
		if err != nil {
			return RunResult{Status: "env-error", Error: err.Error()}
		}
		built, compileErr, err := ws.buildRust(string(code))
		if err != nil {
			return RunResult{Status: "env-error", Error: err.Error()}
		}
		if compileErr != "" {
			return RunResult{Status: "ce", Stderr: compileErr}
		}
		exe = built
	default:
		return RunResult{Status: "env-error", Error: "unknown-language"}
	}
	if _, err := os.Stat(exe); err != nil {
		return RunResult{Status: "env-error", Error: "not-installed"}
	}

	runs.slots <- struct{}{}
	defer func() { <-runs.slots }()

	cmd := exec.Command(exe, args...)
	cmd.Dir = dir
	cmd.Env = ws.Env(extra)
	hideWindow(cmd) // прячет только консоль: окна tkinter, pygame и других программ видны
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
	started := time.Now()
	if err := cmd.Start(); err != nil {
		return RunResult{Status: "env-error", Error: err.Error()}
	}
	var live *liveRun
	runs.mu.Lock()
	runs.procs[req.RunID] = cmd
	if req.Interactive {
		live = &liveRun{mu: &mu, stdout: stdout, stderr: stderr, stdin: stdinPipe}
		runs.live[req.RunID] = live
	}
	runs.mu.Unlock()
	if live != nil {
		// Ввод остаётся открытым: строки придут через /app/run-io
		go func() {
			live.inMu.Lock()
			defer live.inMu.Unlock()
			if req.Stdin != "" {
				_, _ = io.WriteString(stdinPipe, req.Stdin)
			}
		}()
		defer func() {
			mu.Lock()
			live.finished = true
			mu.Unlock()
			_ = stdinPipe.Close()
			// IDE заберёт остаток вывода; если не заберёт — запись всё равно уберём
			time.AfterFunc(time.Minute, func() {
				runs.mu.Lock()
				if runs.live[req.RunID] == live {
					delete(runs.live, req.RunID)
				}
				runs.mu.Unlock()
			})
		}()
	} else {
		go func() {
			_, _ = io.WriteString(stdinPipe, req.Stdin)
			_ = stdinPipe.Close()
		}()
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	timedOut := false
	select {
	case <-done:
	case <-time.After(time.Duration(req.TimeLimitMs) * time.Millisecond):
		timedOut = true
		kill()
		<-done
	}
	elapsed := int(time.Since(started).Milliseconds())
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
		return RunResult{Status: "cancelled", Stdout: out, Stderr: errOut, TimeMs: elapsed}
	case isOver:
		return RunResult{Status: "ole", Stdout: out, Stderr: errOut}
	case timedOut:
		return RunResult{Status: "tle", Stdout: out, Stderr: errOut, TimeMs: elapsed}
	}
	if code := cmd.ProcessState.ExitCode(); code != 0 {
		return RunResult{Status: "re", Stdout: out, Stderr: errOut, TimeMs: elapsed,
			Error: fmt.Sprintf("Программа завершилась с кодом %d", code)}
	}
	return RunResult{Status: "ok", Stdout: out, Stderr: errOut, TimeMs: elapsed}
}
