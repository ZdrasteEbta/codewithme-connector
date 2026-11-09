package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
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
