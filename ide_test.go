package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const ideTestPort = 47999

func ideTestServer(t *testing.T) (*Server, string) {
	t.Helper()
	ws := &Workspace{Root: t.TempDir()}
	if err := ws.Prepare(); err != nil {
		t.Fatal(err)
	}
	p := NewPairing(filepath.Join(ws.Root, "tokens.json"))
	token, reason := p.Pair(p.Code())
	if token == "" {
		t.Fatal(reason)
	}
	return &Server{
		port:     ideTestPort,
		origins:  map[string]bool{site: true},
		ws:       ws,
		pairing:  p,
		runs:     NewRuns(),
		inst:     NewInstaller(ws),
		tasks:    NewTasks(ws),
		ide:      NewIDE(filepath.Join(ws.Root, "tree.json")),
		siteBase: site,
	}, token
}

func ideRequest(s *Server, method, path, body string, headers map[string]string) *httptest.ResponseRecorder {
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	r.Host = "127.0.0.1:" + itoa(ideTestPort)
	for k, v := range headers {
		r.Header.Set(k, v)
	}
	w := httptest.NewRecorder()
	s.ServeHTTP(w, r)
	return w
}

func TestAppRejectsOtherPages(t *testing.T) {
	s, _ := ideTestServer(t)
	cmd := `{"type":"run","key":"k"}`
	if w := ideRequest(s, http.MethodPost, "/app/cmd", cmd, nil); w.Code != 403 {
		t.Fatalf("без Origin: %d", w.Code)
	}
	if w := ideRequest(s, http.MethodPost, "/app/cmd", cmd, map[string]string{"Origin": "https://evil.example"}); w.Code != 403 {
		t.Fatalf("чужой Origin: %d", w.Code)
	}
	if w := ideRequest(s, http.MethodPost, "/app/cmd", cmd, map[string]string{"Origin": site}); w.Code != 403 {
		t.Fatalf("сайт не должен управлять окном: %d", w.Code)
	}
	if w := ideRequest(s, http.MethodGet, "/app/state", "", map[string]string{"Sec-Fetch-Site": "cross-site"}); w.Code != 403 {
		t.Fatalf("чтение с чужой страницы: %d", w.Code)
	}
	r := httptest.NewRequest(http.MethodGet, "/app/", nil)
	r.Host = "evil.example"
	w := httptest.NewRecorder()
	s.ServeHTTP(w, r)
	if w.Code != 403 {
		t.Fatalf("чужой Host: %d", w.Code)
	}
}

func TestSiteEndpointsNeedToken(t *testing.T) {
	s, token := ideTestServer(t)
	origin := map[string]string{"Origin": site}
	if w := ideRequest(s, http.MethodPost, "/ide/tree", `{"rows":[]}`, origin); w.Code != 401 {
		t.Fatalf("без токена: %d", w.Code)
	}
	withToken := map[string]string{"Origin": site, "X-CWM-Token": token}
	if w := ideRequest(s, http.MethodPost, "/ide/tree", `{"rows":[]}`, withToken); w.Code != 200 {
		t.Fatalf("с токеном: %d", w.Code)
	}
}

func TestAppInstall(t *testing.T) {
	s, _ := ideTestServer(t)
	self := map[string]string{"Origin": "http://127.0.0.1:" + itoa(ideTestPort)}
	body := `{"language":"python","pip":["numpy"]}`
	if w := ideRequest(s, http.MethodPost, "/app/install", body, map[string]string{"Origin": site}); w.Code != 403 {
		t.Fatalf("сайт не должен ставить библиотеки через окно: %d", w.Code)
	}
	for _, bad := range []string{
		`{"language":"python","pip":["--index-url=http://x"]}`,
		`{"language":"node","npm":["../evil"]}`,
		`{"language":"go"}`,
	} {
		if w := ideRequest(s, http.MethodPost, "/app/install", bad, self); w.Code != 400 {
			t.Fatalf("%s принят: %d", bad, w.Code)
		}
	}
	run := `{"runId":"t1","language":"python","code":"print(1)","stdin":"","timeLimitMs":1000,"outputLimitBytes":1000}`
	if w := ideRequest(s, http.MethodPost, "/app/run", run, map[string]string{"Origin": site}); w.Code != 403 {
		t.Fatalf("сайт не должен запускать код через окно: %d", w.Code)
	}
	for _, bad := range []string{
		`{"runId":"t1","language":"python","code":"","timeLimitMs":999999,"outputLimitBytes":1000}`,
		`{"runId":"../x","language":"python","code":"","timeLimitMs":1000,"outputLimitBytes":1000}`,
		`{"runId":"t1","language":"bash","code":"","timeLimitMs":1000,"outputLimitBytes":1000}`,
	} {
		if w := ideRequest(s, http.MethodPost, "/app/run", bad, self); w.Code != 400 {
			t.Fatalf("%s принят: %d", bad, w.Code)
		}
	}
	// Python не установлен: честный ответ, а не падение
	w := ideRequest(s, http.MethodPost, "/app/run", run, self)
	if w.Code != 200 || !strings.Contains(w.Body.String(), "env-error") {
		t.Fatalf("запуск без Python: %d %s", w.Code, w.Body.String())
	}
	// Запуск любого файла: только из окна, только абсолютный путь и известное расширение
	file := filepath.Join(t.TempDir(), "main.py")
	if err := os.WriteFile(file, []byte("print(1)"), 0o644); err != nil {
		t.Fatal(err)
	}
	quoted, _ := json.Marshal(file)
	runFile := `{"runId":"f1","path":` + string(quoted) + `,"timeLimitMs":1000,"outputLimitBytes":1000}`
	if w := ideRequest(s, http.MethodPost, "/app/run-file", runFile, map[string]string{"Origin": site}); w.Code != 403 {
		t.Fatalf("сайт не должен запускать файлы через окно: %d", w.Code)
	}
	for _, bad := range []string{
		`{"runId":"f1","path":"main.py","timeLimitMs":1000,"outputLimitBytes":1000}`,
		`{"runId":"f1","path":` + strings.Replace(string(quoted), "main.py", "run.bat", 1) + `,"timeLimitMs":1000,"outputLimitBytes":1000}`,
		strings.Replace(runFile, `"timeLimitMs":1000`, `"timeLimitMs":99999999`, 1),
	} {
		if w := ideRequest(s, http.MethodPost, "/app/run-file", bad, self); w.Code != 400 {
			t.Fatalf("%s принят: %d", bad, w.Code)
		}
	}
	if w := ideRequest(s, http.MethodPost, "/app/run-file", runFile, self); w.Code != 200 || !strings.Contains(w.Body.String(), "env-error") {
		t.Fatalf("запуск файла без Python: %d %s", w.Code, w.Body.String())
	}
	w = ideRequest(s, http.MethodGet, "/app/env", "", nil)
	var env struct {
		Python    bool
		PythonExe string
		Tmp       string
	}
	if err := json.Unmarshal(w.Body.Bytes(), &env); err != nil {
		t.Fatal(err)
	}
	if env.Python || env.PythonExe == "" || env.Tmp == "" {
		t.Fatalf("окружение: %s", w.Body.String())
	}
}

func TestCommandReachesSite(t *testing.T) {
	s, token := ideTestServer(t)
	self := map[string]string{"Origin": "http://127.0.0.1:" + itoa(ideTestPort)}
	if w := ideRequest(s, http.MethodPost, "/app/cmd", `{"type":"run","key":"k"}`, self); w.Code != 409 {
		t.Fatalf("сайт не открыт: %d", w.Code)
	}
	s.ide.mu.Lock()
	s.ide.siteWaiting = 1 // сайт ждёт команду
	s.ide.mu.Unlock()
	if w := ideRequest(s, http.MethodPost, "/app/cmd", `{"type":"run","key":"k","stdin":"5"}`, self); w.Code != 200 {
		t.Fatalf("команда: %d", w.Code)
	}
	if w := ideRequest(s, http.MethodPost, "/app/cmd", `{"type":"delete","key":"k"}`, self); w.Code != 400 {
		t.Fatalf("неизвестная команда: %d", w.Code)
	}
	w := ideRequest(s, http.MethodGet, "/ide/next", "", map[string]string{"Origin": site, "X-CWM-Token": token})
	var res struct {
		Cmd struct {
			Type, Key, Stdin string
		} `json:"cmd"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &res); err != nil {
		t.Fatal(err)
	}
	if res.Cmd.Type != "run" || res.Cmd.Key != "k" || res.Cmd.Stdin != "5" {
		t.Fatalf("сайт получил: %+v", res.Cmd)
	}
}
