package main

// HTTP-сервер коннектора на 127.0.0.1. Защита та же, что у моста bridge/cwm_bridge.py:
//   * слушаем только 127.0.0.1 — с других компьютеров не подключиться;
//   * принимаем запросы только со страниц https://codewithme.app (Origin браузер подделать не даёт)
//     и только с Host 127.0.0.1/localhost (защита от DNS rebinding);
//   * всё, кроме /status и /pair, — только с токеном, полученным при сопряжении кодом из 6 цифр.

import (
	"encoding/json"
	"io"
	"net/http"
	"regexp"
	"runtime"
	"strings"
)

const (
	protocol = 2
	maxBody  = 20 << 20 // программа + входные данные (большие тесты — до 9 МБ)
)

var runIDRE = regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`)

type Server struct {
	port    int
	origins map[string]bool
	ws      *Workspace
	pairing *Pairing
	runs    *Runs
	inst    *Installer
	tasks   *Tasks
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	origin := r.Header.Get("Origin")
	host := r.Host
	if !s.origins[origin] || (host != "127.0.0.1:"+itoa(s.port) && host != "localhost:"+itoa(s.port)) {
		writeJSON(w, 403, map[string]any{"error": "forbidden"}, "")
		return
	}
	if r.Method == http.MethodOptions {
		h := w.Header()
		h.Set("Access-Control-Allow-Origin", origin)
		h.Set("Access-Control-Allow-Methods", "GET, POST")
		h.Set("Access-Control-Allow-Headers", "Content-Type, X-CWM-Token")
		h.Set("Access-Control-Allow-Private-Network", "true")
		h.Set("Access-Control-Max-Age", "600")
		h.Set("Vary", "Origin")
		w.WriteHeader(204)
		return
	}
	token := r.Header.Get("X-CWM-Token")
	reply := func(code int, data any) { writeJSON(w, code, data, origin) }

	switch {
	case r.Method == http.MethodGet && r.URL.Path == "/status":
		st := s.ws.LoadState()
		python := ""
		if st.Python {
			python = pythonVersion
		}
		reply(200, map[string]any{
			"bridge":    protocol,
			"connector": true,
			"version":   version,
			"python":    python,
			"os":        osName(),
			"paired":    s.pairing.Valid(token),
			"modules":   map[string]bool{},
			"node":      st.Node,
			"packages":  sortedPackages(st.Packages),
		})
		return
	case r.Method == http.MethodPost && r.URL.Path == "/pair":
		var req struct {
			Code string `json:"code"`
		}
		if !readJSON(r, &req) || len(req.Code) > 20 {
			reply(400, map[string]any{"error": "bad-request"})
			return
		}
		tok, reason := s.pairing.Pair(req.Code)
		if tok == "" {
			reply(403, map[string]any{"error": reason})
			return
		}
		reply(200, map[string]any{"token": tok})
		return
	}

	if !s.pairing.Valid(token) {
		reply(401, map[string]any{"error": "not-paired"})
		return
	}

	switch {
	case r.Method == http.MethodPost && r.URL.Path == "/ensure":
		var req struct {
			Language string   `json:"language"`
			Pip      []string `json:"pip"`
		}
		if !readJSON(r, &req) || (req.Language != "python" && req.Language != "javascript") || !validPackages(req.Pip) {
			reply(400, map[string]any{"error": "bad-request"})
			return
		}
		reply(200, s.inst.Ensure(req.Language, req.Pip))

	case r.Method == http.MethodPost && r.URL.Path == "/run":
		var req RunRequest
		ok := readJSON(r, &req) && runIDRE.MatchString(req.RunID) &&
			req.TimeLimitMs >= 1 && req.TimeLimitMs <= maxTimeMs &&
			req.OutputLimitBytes >= 1 && req.OutputLimitBytes <= maxOutput
		if req.Language == "" {
			req.Language = "python"
		}
		if !ok || (req.Language != "python" && req.Language != "javascript") {
			reply(400, map[string]any{"error": "bad-request"})
			return
		}
		label := req.Label
		if len([]rune(label)) > 80 {
			label = string([]rune(label)[:80])
		}
		if label == "" {
			label = "программа"
		}
		mode := "проверка"
		if req.Window {
			mode = "окно"
		}
		logf("Запуск: %s (%s)", label, mode)
		res := s.ws.Run(req, s.runs)
		logf("  → %s, %d мс", strings.ToUpper(res.Status), res.TimeMs)
		reply(200, res)

	case r.Method == http.MethodPost && r.URL.Path == "/cancel":
		var req struct {
			RunID string `json:"runId"`
		}
		if !readJSON(r, &req) || !runIDRE.MatchString(req.RunID) {
			reply(400, map[string]any{"error": "bad-request"})
			return
		}
		reply(200, map[string]any{"cancelled": s.runs.Cancel(req.RunID)})

	case r.Method == http.MethodPost && r.URL.Path == "/task":
		var req TaskRequest
		if !readJSON(r, &req) {
			reply(400, map[string]any{"error": "bad-request"})
			return
		}
		st, err := s.tasks.Open(req)
		if err != nil {
			reply(400, map[string]any{"error": err.Error()})
			return
		}
		reply(200, st)

	case r.Method == http.MethodGet && r.URL.Path == "/file":
		st, err := s.tasks.Read(r.URL.Query().Get("key"))
		if err != nil {
			reply(404, map[string]any{"error": "unknown-task"})
			return
		}
		reply(200, st)

	case r.Method == http.MethodPost && r.URL.Path == "/file":
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

	case r.Method == http.MethodPost && r.URL.Path == "/submission":
		var req struct {
			Key     string `json:"key"`
			Code    string `json:"code"`
			Verdict string `json:"verdict"`
			Report  string `json:"report"`
		}
		if !readJSON(r, &req) {
			reply(400, map[string]any{"error": "bad-request"})
			return
		}
		name, err := s.tasks.Submission(req.Key, req.Code, req.Verdict, req.Report)
		if err != nil {
			reply(404, map[string]any{"error": err.Error()})
			return
		}
		reply(200, map[string]any{"name": name})

	default:
		reply(404, map[string]any{"error": "not-found"})
	}
}

func readJSON(r *http.Request, v any) bool {
	body, err := io.ReadAll(io.LimitReader(r.Body, maxBody+1))
	if err != nil || len(body) == 0 || len(body) > maxBody {
		return false
	}
	return json.Unmarshal(body, v) == nil
}

func writeJSON(w http.ResponseWriter, code int, data any, origin string) {
	body, _ := json.Marshal(data)
	h := w.Header()
	h.Set("Content-Type", "application/json; charset=utf-8")
	h.Set("Cache-Control", "no-store")
	if origin != "" {
		h.Set("Access-Control-Allow-Origin", origin)
		h.Set("Vary", "Origin")
	}
	w.WriteHeader(code)
	_, _ = w.Write(body)
}

func osName() string {
	switch runtime.GOOS {
	case "windows":
		return "Windows"
	case "darwin":
		return "Darwin"
	case "linux":
		return "Linux"
	}
	return runtime.GOOS
}
