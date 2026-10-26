package main

// Запуск программ ученика. Правила те же, что у проверки на сайте:
// лимит времени, лимит вывода, отмена, check после кода для «Почини код».

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

const (
	maxOutput    = 16 << 20
	maxTimeMs    = 10 * 60 * 1000 // «Запустить у себя» с окном игры — до 10 минут
	startupGrace = 3 * time.Second // запуск интерпретатора и импорт библиотек не входят во время программы
	maxParallel  = 2
)

// Выполняется в отдельном процессе Python: sys.exit(0) — нормальное завершение,
// ненулевой код и исключения — ошибка выполнения, трейсбек — только по строкам ученика.
const pythonDriver = `
import json, sys, time, traceback
src_path, check_path, result_path, name, want_images = sys.argv[1:6]
sys.stdout.reconfigure(newline="\n")
sys.stderr.reconfigure(newline="\n")
src = open(src_path, encoding="utf-8").read()
check = open(check_path, encoding="utf-8").read() if check_path != "-" else None
g = {"__name__": name, "__builtins__": __builtins__}
status, error = "ok", None
started = time.perf_counter()
try:
    exec(compile(src, "main.py", "exec"), g)
    if check:
        try:
            exec(compile(check, "<check>", "exec"), g)
        except Exception as e:
            status, error = "re", "Проверка задачи не смогла прочитать результат: %s: %s" % (type(e).__name__, e)
except SystemExit as e:
    if e.code not in (None, 0):
        status, error = "re", "Программа завершилась с кодом %s (sys.exit)" % (e.code,)
except MemoryError:
    status, error = "re", "MemoryError: программе не хватило памяти"
except SyntaxError as e:
    status, error = "re", "".join(traceback.format_exception_only(type(e), e)).rstrip()
except BaseException as e:
    frames = [f for f in traceback.extract_tb(e.__traceback__) if f.filename == "main.py"]
    text = "Traceback (most recent call last):\n" + "".join(traceback.format_list(frames))
    status, error = "re", (text + "".join(traceback.format_exception_only(type(e), e))).rstrip()
elapsed = time.perf_counter() - started
images = []
plt = sys.modules.get("matplotlib.pyplot")
if want_images == "1" and plt is not None:
    # Картинки построенных графиков (PNG в base64) — сайт показывает их после «Запустить»
    try:
        import io, base64
        for num in plt.get_fignums()[:3]:
            buf = io.BytesIO()
            plt.figure(num).savefig(buf, format="png", dpi=80, bbox_inches="tight")
            images.append(base64.b64encode(buf.getvalue()).decode())
    except Exception:
        pass
try:
    sys.stdout.flush()
    sys.stderr.flush()
except BaseException:
    pass
with open(result_path, "w", encoding="utf-8") as f:
    json.dump({"status": status, "error": error, "timeMs": round(elapsed * 1000), "images": images}, f)
`

// Повторяет public/runner/js-worker.js сайта: код ученика и тесты в одной области видимости
const nodeDriver = `
const fs = require("fs");
const [codePath, testsPath, resultPath] = process.argv.slice(2);
const code = fs.readFileSync(codePath, "utf8");
const tests = testsPath === "-" ? "" : fs.readFileSync(testsPath, "utf8");
class AssertionError extends Error {}
function format(value) {
  if (typeof value === "string") return value;
  if (value === undefined) return "undefined";
  if (typeof value === "function") return value.toString();
  try { return JSON.stringify(value); } catch { return String(value); }
}
const lines = [];
const log = (...args) => lines.push(args.map(format).join(" "));
const fakeConsole = { log, info: log, warn: log, error: log, debug: log };
const assert = (condition, message) => { if (!condition) throw new AssertionError(message || "assert failed"); };
const output = () => lines.join("\n");
const check = (call, got, expected) => {
  if (JSON.stringify(got) !== JSON.stringify(expected)) {
    throw new AssertionError("__check__" + JSON.stringify({ call: String(call), got: format(got), expected: format(expected) }));
  }
};
const done = (r) => fs.writeFileSync(resultPath, JSON.stringify({ output: output(), ...r }));
const source = code + "\n;\n__runTests();\n" + (tests || "");
let testsStarted = false;
const started = performance.now();
try {
  const fn = new Function("console", "assert", "check", "output", "__runTests", "require", "process", source);
  fn(fakeConsole, assert, check, output, () => (testsStarted = true), undefined, undefined);
  if (tests && !testsStarted) {
    done({ error: "Проверка не запустилась: программа завершилась раньше тестов. Уберите return вне функций." });
  } else done({});
} catch (err) {
  const text = err instanceof Error ? err.name + ": " + err.message : String(err);
  if (testsStarted && err instanceof AssertionError) done({ testError: err.message });
  else done({ error: text });
}
`

type RunRequest struct {
	RunID            string  `json:"runId"`
	Language         string  `json:"language"`
	Code             string  `json:"code"`
	Stdin            string  `json:"stdin"`
	Check            *string `json:"check"`
	Tests            *string `json:"tests"`
	TimeLimitMs      int     `json:"timeLimitMs"`
	OutputLimitBytes int     `json:"outputLimitBytes"`
	Window           bool    `json:"window"`
	Images           bool    `json:"images"`
	Label            string  `json:"label"`
}

type RunResult struct {
	Status    string `json:"status"`
	Stdout    string `json:"stdout"`
	Stderr    string `json:"stderr"`
	TimeMs    int    `json:"timeMs"`
	Error     string `json:"error,omitempty"`
	Output    string `json:"output,omitempty"`
	TestError string   `json:"testError,omitempty"`
	Images    []string `json:"images,omitempty"`
}

type Runs struct {
	mu        sync.Mutex
	procs     map[string]*exec.Cmd
	cancelled map[string]bool
	slots     chan struct{}
}

func NewRuns() *Runs {
	return &Runs{procs: map[string]*exec.Cmd{}, cancelled: map[string]bool{}, slots: make(chan struct{}, maxParallel)}
}

func (r *Runs) Cancel(id string) bool {
	r.mu.Lock()
	cmd := r.procs[id]
	if cmd != nil {
		r.cancelled[id] = true
	}
	r.mu.Unlock()
	if cmd == nil {
		return false
	}
	if cmd.Process != nil {
		_ = cmd.Process.Kill()
	}
	return true
}

// limitedBuffer собирает вывод; при превышении общего лимита убивает процесс (OLE)
type limitedBuffer struct {
	mu    *sync.Mutex
	total *int
	limit int
	over  *bool
	kill  func()
	buf   []byte
}

func (b *limitedBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	*b.total += len(p)
	if *b.total > b.limit {
		if !*b.over {
			*b.over = true
			b.kill()
		}
		return len(p), nil
	}
	b.buf = append(b.buf, p...)
	return len(p), nil
}

func (ws *Workspace) Run(req RunRequest, runs *Runs) RunResult {
	// Папку временных файлов могли удалить (чистка диска) — создаём заново
	if err := os.MkdirAll(ws.Path("cache", "tmp"), 0o755); err != nil {
		return RunResult{Status: "env-error", Error: err.Error()}
	}
	tmp, err := os.MkdirTemp(ws.Path("cache", "tmp"), "run-")
	if err != nil {
		return RunResult{Status: "env-error", Error: err.Error()}
	}
	defer os.RemoveAll(tmp)
	write := func(name, text string) string {
		p := filepath.Join(tmp, name)
		if err == nil {
			err = os.WriteFile(p, []byte(text), 0o644)
		}
		return p
	}
	resultPath := filepath.Join(tmp, "_cwm_result.json")
	var exe string
	var args []string
	extra := map[string]string{}
	switch req.Language {
	case "javascript":
		exe = ws.NodeExe()
		testsPath := "-"
		if req.Tests != nil && *req.Tests != "" {
			testsPath = write("_cwm_tests.js", *req.Tests)
		}
		args = []string{write("_cwm_driver.js", nodeDriver), write("main.js", req.Code), testsPath, resultPath}
	default:
		exe = ws.PythonExe()
		checkPath := "-"
		if req.Check != nil && *req.Check != "" {
			checkPath = write("_cwm_check.py", *req.Check)
		}
		// При проверке с check игровой цикл под if __name__ == "__main__" не запускается
		name := "__main__"
		if checkPath != "-" {
			name = "__cwm_check__"
		}
		images := "0"
		if req.Images {
			images = "1"
		}
		args = []string{"-E", "-X", "utf8", "-X", "pycache_prefix=" + ws.Path("cache", "pycache"),
			write("_cwm_driver.py", pythonDriver), write("main.py", req.Code), checkPath, resultPath, name, images}
		if !req.Window {
			// Проверка без окон и звука
			extra["SDL_VIDEODRIVER"] = "dummy"
			extra["SDL_AUDIODRIVER"] = "dummy"
			extra["MPLBACKEND"] = "Agg"
		}
	}
	if err != nil {
		return RunResult{Status: "env-error", Error: err.Error()}
	}
	if _, err := os.Stat(exe); err != nil {
		return RunResult{Status: "env-error", Error: "not-installed"}
	}

	runs.slots <- struct{}{}
	defer func() { <-runs.slots }()

	cmd := exec.Command(exe, args...)
	cmd.Dir = tmp
	cmd.Env = ws.Env(extra)
	if !req.Window {
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
	if err := cmd.Start(); err != nil {
		return RunResult{Status: "env-error", Error: err.Error()}
	}
	runs.mu.Lock()
	runs.procs[req.RunID] = cmd
	runs.mu.Unlock()
	// Ввод пишем отдельно: если программа его не читает, запись блокируется, а лимит времени должен действовать
	go func() {
		_, _ = io.WriteString(stdinPipe, req.Stdin)
		_ = stdinPipe.Close()
	}()
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	timedOut := false
	select {
	case <-done:
	case <-time.After(time.Duration(req.TimeLimitMs)*time.Millisecond + startupGrace):
		timedOut = true
		kill()
		<-done
	}
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
	}
	data, rerr := os.ReadFile(resultPath)
	if rerr != nil {
		code := -1
		if cmd.ProcessState != nil {
			code = cmd.ProcessState.ExitCode()
		}
		return RunResult{Status: "re", Stdout: out, Stderr: errOut, Error: fmt.Sprintf("Программа аварийно завершилась (код %d)", code)}
	}
	if req.Language == "javascript" {
		var r struct {
			Output    string `json:"output"`
			Error     string `json:"error"`
			TestError string `json:"testError"`
		}
		if json.Unmarshal(data, &r) != nil {
			return RunResult{Status: "re", Error: "Не удалось прочитать результат"}
		}
		return RunResult{Status: "ok", Stdout: out, Stderr: errOut, Output: r.Output, Error: r.Error, TestError: r.TestError}
	}
	var r struct {
		Status string   `json:"status"`
		Error  *string  `json:"error"`
		TimeMs int      `json:"timeMs"`
		Images []string `json:"images"`
	}
	if json.Unmarshal(data, &r) != nil {
		return RunResult{Status: "re", Stdout: out, Stderr: errOut, Error: "Не удалось прочитать результат"}
	}
	status := r.Status
	if r.TimeMs > req.TimeLimitMs {
		status = "tle"
	}
	res := RunResult{Status: status, Stdout: out, Stderr: errOut, TimeMs: r.TimeMs, Images: r.Images}
	if r.Error != nil {
		res.Error = *r.Error
	}
	return res
}
