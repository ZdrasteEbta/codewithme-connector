package main

// CodeWithMe IDE: связь настольного приложения (desktop/) с сайтом.
// Приложение обращается к /app на этом же 127.0.0.1. Условия, скрытые тесты и опыт остаются на сайте, поэтому:
//   сайт → программа: сетка тем (/ide/tree), открытая задача (/ide/current), ход проверки (/ide/status);
//   окно → сайт: команды «запусти», «отправь», «открой задачу», которые сайт забирает через /ide/next.

import (
	"context"
	"encoding/json"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"sync"
	"time"
)

const (
	appPollWait  = 6 * time.Second
	sitePollWait = 25 * time.Second
	siteGrace    = 6 * time.Second  // между двумя запросами /ide/next сайт считается на связи
	windowGrace  = 25 * time.Second // окно закрыто, если столько времени нет ни одного запроса
	maxCommands  = 16
)

var hrefRE = regexp.MustCompile(`^/[A-Za-z0-9_/?=&%.,~-]{0,400}$`)

var localeRE = regexp.MustCompile(`^[a-z]{2}$`)

type IDE struct {
	mu          sync.Mutex
	seq         uint64
	changed     chan struct{}
	tree        json.RawMessage
	current     json.RawMessage
	status      json.RawMessage
	treeFile    string
	cmds        []json.RawMessage
	cmdWake     chan struct{}
	siteWaiting int
	siteSeen    time.Time
	appWaiting  int
	appSeen     time.Time
}

func NewIDE(treeFile string) *IDE {
	h := &IDE{changed: make(chan struct{}), cmdWake: make(chan struct{}), treeFile: treeFile}
	// Сетка с прошлого раза: окно не пустое, пока сайт ещё не открыт
	if data, err := os.ReadFile(treeFile); err == nil && json.Valid(data) {
		h.tree = data
	}
	return h
}

func (h *IDE) notifyLocked() {
	h.seq++
	close(h.changed)
	h.changed = make(chan struct{})
}

func (h *IDE) SetTree(data json.RawMessage) {
	h.mu.Lock()
	h.tree = data
	h.notifyLocked()
	h.mu.Unlock()
	_ = writeFileAtomic(h.treeFile, data)
}

func (h *IDE) SetCurrent(data json.RawMessage) {
	h.mu.Lock()
	h.current = data
	h.notifyLocked()
	h.mu.Unlock()
}

func (h *IDE) SetStatus(data json.RawMessage) {
	h.mu.Lock()
	h.status = data
	h.notifyLocked()
	h.mu.Unlock()
}

func (h *IDE) siteOnlineLocked() bool {
	return h.siteWaiting > 0 || (!h.siteSeen.IsZero() && time.Since(h.siteSeen) < siteGrace)
}

func (h *IDE) SiteOnline() bool {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.siteOnlineLocked()
}

// Enqueue ставит команду окна в очередь для сайта
func (h *IDE) Enqueue(cmd json.RawMessage) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if len(h.cmds) >= maxCommands {
		h.cmds = h.cmds[1:]
	}
	h.cmds = append(h.cmds, cmd)
	close(h.cmdWake)
	h.cmdWake = make(chan struct{})
}

// NextCommand ждёт команду окна. Пока запрос висит, сайт считается на связи.
func (h *IDE) NextCommand(ctx context.Context, wait time.Duration) json.RawMessage {
	h.mu.Lock()
	wasOnline := h.siteOnlineLocked()
	h.siteWaiting++
	if !wasOnline {
		h.notifyLocked()
	}
	h.mu.Unlock()
	defer func() {
		h.mu.Lock()
		h.siteWaiting--
		h.siteSeen = time.Now()
		h.mu.Unlock()
	}()
	timer := time.NewTimer(wait)
	defer timer.Stop()
	for {
		h.mu.Lock()
		if len(h.cmds) > 0 {
			cmd := h.cmds[0]
			h.cmds = h.cmds[1:]
			h.mu.Unlock()
			return cmd
		}
		wake := h.cmdWake
		h.mu.Unlock()
		select {
		case <-wake:
		case <-timer.C:
			return nil
		case <-ctx.Done():
			return nil
		}
	}
}

// WaitState ждёт изменения состояния после since. Висящий запрос — признак того, что окно открыто.
func (h *IDE) WaitState(ctx context.Context, since uint64, wait time.Duration) {
	h.mu.Lock()
	h.appWaiting++
	h.appSeen = time.Now()
	h.mu.Unlock()
	defer func() {
		h.mu.Lock()
		h.appWaiting--
		h.appSeen = time.Now()
		h.mu.Unlock()
	}()
	timer := time.NewTimer(wait)
	defer timer.Stop()
	for {
		h.mu.Lock()
		seq, changed := h.seq, h.changed
		h.mu.Unlock()
		if seq != since {
			return
		}
		select {
		case <-changed:
		case <-timer.C:
			return
		case <-ctx.Done():
			return
		}
	}
}

// TouchWindow отмечает, что окно только что открылось
func (h *IDE) TouchWindow() {
	h.mu.Lock()
	h.appSeen = time.Now()
	h.mu.Unlock()
}

// WindowClosed — окно уже открывалось, а теперь давно не спрашивает состояние
func (h *IDE) WindowClosed() bool {
	h.mu.Lock()
	defer h.mu.Unlock()
	return !h.appSeen.IsZero() && h.appWaiting == 0 && time.Since(h.appSeen) > windowGrace
}

func (h *IDE) snapshot() (seq uint64, tree, current, status json.RawMessage, online bool) {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.seq, h.tree, h.current, h.status, h.siteOnlineLocked()
}

// serveApp — запросы настольного приложения. Сайту и другим страницам сюда нельзя.
func (s *Server) serveApp(w http.ResponseWriter, r *http.Request) {
	self := map[string]bool{
		"http://127.0.0.1:" + itoa(s.port): true,
		"http://localhost:" + itoa(s.port): true,
	}
	if !self["http://"+r.Host] {
		writeJSON(w, 403, map[string]any{"error": "forbidden"}, "")
		return
	}
	if fetchSite := r.Header.Get("Sec-Fetch-Site"); fetchSite != "" && fetchSite != "same-origin" && fetchSite != "none" {
		writeJSON(w, 403, map[string]any{"error": "forbidden"}, "")
		return
	}
	if r.Method != http.MethodGet && !self[r.Header.Get("Origin")] {
		writeJSON(w, 403, map[string]any{"error": "forbidden"}, "")
		return
	}
	reply := func(code int, data any) { writeJSON(w, code, data, "") }

	switch {
	case r.Method == http.MethodGet && r.URL.Path == "/app/state":
		if raw := r.URL.Query().Get("since"); raw != "" {
			since, _ := strconv.ParseUint(raw, 10, 64)
			s.ide.WaitState(r.Context(), since, appPollWait)
		} else {
			s.ide.TouchWindow()
		}
		seq, tree, current, status, online := s.ide.snapshot()
		reply(200, map[string]any{
			"seq":        seq,
			"version":    version,
			"folder":     s.ws.Root,
			"code":       s.pairing.Code(),
			"siteOnline": online,
			"tree":       tree,
			"current":    current,
			"status":     status,
		})

	case r.Method == http.MethodGet && r.URL.Path == "/app/file":
		st, err := s.tasks.Read(r.URL.Query().Get("key"))
		if err != nil {
			reply(404, map[string]any{"error": "unknown-task"})
			return
		}
		reply(200, st)

	case r.Method == http.MethodPost && r.URL.Path == "/app/file":
		var req struct {
			Key     string `json:"key"`
			Content string `json:"content"`
			Base    string `json:"base"`
		}
		if !readJSON(r, &req) {
			reply(400, map[string]any{"error": "bad-request"})
			return
		}
		st, err := s.tasks.Write(req.Key, req.Content, req.Base)
		if err != nil {
			reply(404, map[string]any{"error": err.Error()})
			return
		}
		reply(200, st)

	case r.Method == http.MethodPost && r.URL.Path == "/app/cmd":
		var req struct {
			Type   string `json:"type"`
			Key    string `json:"key"`
			Stdin  string `json:"stdin"`
			Href   string `json:"href"`
			Locale string `json:"locale"`
		}
		if !readJSON(r, &req) {
			reply(400, map[string]any{"error": "bad-request"})
			return
		}
		switch req.Type {
		case "open":
			if !hrefRE.MatchString(req.Href) || !localeRE.MatchString(req.Locale) {
				reply(400, map[string]any{"error": "bad-request"})
				return
			}
			if !s.ide.SiteOnline() { // сайта нет — открываем нужную страницу в браузере ученика
				openBrowser(s.siteBase + "/" + req.Locale + req.Href)
				reply(200, map[string]any{"opened": true})
				return
			}
		case "run", "submit", "stop", "next":
			if !s.ide.SiteOnline() {
				reply(409, map[string]any{"error": "site-offline"})
				return
			}
		default:
			reply(400, map[string]any{"error": "bad-request"})
			return
		}
		data, _ := json.Marshal(req)
		s.ide.Enqueue(data)
		reply(200, map[string]any{"ok": true})

	case r.Method == http.MethodGet && r.URL.Path == "/app/env":
		st := s.ws.LoadState()
		reply(200, map[string]any{
			"python":      st.Python,
			"pythonExe":   s.ws.PythonExe(),
			"node":        st.Node != "",
			"nodeExe":     s.ws.NodeExe(),
			"nodeModules": filepath.Join(s.ws.NodePackagesDir(), "node_modules"),
			"rust":        st.Rust != "",
			"rustcExe":    s.ws.RustcExe(),
			"tmp":         s.ws.Path("cache", "tmp"),
		})

	case r.Method == http.MethodPost && r.URL.Path == "/app/install":
		var req struct {
			Language string   `json:"language"`
			Pip      []string `json:"pip"`
			Npm      []string `json:"npm"`
			Fresh    bool     `json:"fresh"` // первое нажатие кнопки: окно видит, что на диске пакетов нет
		}
		if !readJSON(r, &req) || (req.Language != "python" && req.Language != "node" && req.Language != "rust") ||
			!validPackages(req.Pip) || !validNpmPackages(req.Npm) {
			reply(400, map[string]any{"error": "bad-request"})
			return
		}
		pkgs := req.Pip
		if req.Language == "node" {
			pkgs = req.Npm
		}
		if req.Fresh {
			s.inst.Forget(req.Language, pkgs)
		}
		reply(200, s.inst.Ensure(req.Language, pkgs))

	case r.Method == http.MethodPost && r.URL.Path == "/app/run":
		// Тесты справа от редактора: программа ученика с его вводом, без окна игры и без проверочного кода
		var req RunRequest
		ok := readJSON(r, &req) && runIDRE.MatchString(req.RunID) && req.TimeLimitMs >= 1 && req.TimeLimitMs <= 60*1000 &&
			req.OutputLimitBytes >= 1 && req.OutputLimitBytes <= maxOutput &&
			(req.Language == "python" || req.Language == "rust" || req.Language == "javascript" || req.Language == "node")
		if !ok {
			reply(400, map[string]any{"error": "bad-request"})
			return
		}
		req.Window, req.Images, req.Check, req.Tests, req.Crates = false, false, nil, nil, nil
		req.Label = "тест в IDE"
		res := s.ws.Run(req, s.runs)
		reply(200, res)

	case r.Method == http.MethodPost && r.URL.Path == "/app/run-file":
		// Любой открытый в IDE файл: запускается в своей папке, вывод уходит в журнал Debug.
		// Сайт сюда попасть не может: запросы принимаются только с адреса самого окна (Origin)
		var req RunFileRequest
		ok := readJSON(r, &req) && runIDRE.MatchString(req.RunID) && filepath.IsAbs(req.Path) &&
			fileLanguage(req.Path) != "" && req.TimeLimitMs >= 1 && req.TimeLimitMs <= maxFileRunMs &&
			req.OutputLimitBytes >= 1 && req.OutputLimitBytes <= maxOutput
		if !ok {
			reply(400, map[string]any{"error": "bad-request"})
			return
		}
		reply(200, s.ws.RunFile(req, s.runs))

	case r.Method == http.MethodPost && r.URL.Path == "/app/run-io":
		// Интерактивный запуск файла: ввод строк, пока программа ждёт input(), и вывод на лету
		var req RunIORequest
		if !readJSON(r, &req) || !runIDRE.MatchString(req.RunID) || len(req.Input) > maxOutput {
			reply(400, map[string]any{"error": "bad-request"})
			return
		}
		reply(200, s.runs.IO(req))

	case r.Method == http.MethodPost && r.URL.Path == "/app/cancel":
		var req struct {
			RunID string `json:"runId"`
		}
		if !readJSON(r, &req) || !runIDRE.MatchString(req.RunID) {
			reply(400, map[string]any{"error": "bad-request"})
			return
		}
		reply(200, map[string]any{"cancelled": s.runs.Cancel(req.RunID)})

	case r.Method == http.MethodPost && r.URL.Path == "/app/open-site":
		openBrowser(s.siteBase)
		reply(200, map[string]any{"ok": true})

	default:
		reply(404, map[string]any{"error": "not-found"})
	}
}

// openBrowser открывает адрес в обычном браузере ученика
func openBrowser(url string) {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	case "darwin":
		cmd = exec.Command("open", url)
	default:
		cmd = exec.Command("xdg-open", url)
	}
	if err := cmd.Start(); err != nil {
		logf("Не удалось открыть браузер: %v", err)
		return
	}
	go func() { _ = cmd.Wait() }()
}

// watchWindow завершает программу, когда приложение закрылось или упало
func (s *Server) watchWindow() {
	for {
		time.Sleep(5 * time.Second)
		if s.ide.WindowClosed() {
			logf("Окно закрыто.")
			os.Exit(0)
		}
	}
}
