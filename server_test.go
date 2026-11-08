package main

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func newTestServer(t *testing.T) (*Server, string) {
	t.Helper()
	ws := &Workspace{Root: t.TempDir()}
	if err := ws.Prepare(); err != nil {
		t.Fatal(err)
	}
	s := &Server{
		port:    47615,
		origins: map[string]bool{site: true},
		ws:      ws,
		pairing: NewPairing(ws.Path(".cwm", "tokens.json")),
		runs:    NewRuns(),
		inst:    NewInstaller(ws),
		tasks:   NewTasks(ws),
	}
	tok, reason := s.pairing.Pair(s.pairing.code)
	if tok == "" {
		t.Fatal(reason)
	}
	return s, tok
}

func do(s *Server, method, path, origin, host, token, body string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	req.Host = host
	if origin != "" {
		req.Header.Set("Origin", origin)
	}
	if token != "" {
		req.Header.Set("X-CWM-Token", token)
	}
	rec := httptest.NewRecorder()
	s.ServeHTTP(rec, req)
	return rec
}

func TestOriginAndHostChecks(t *testing.T) {
	s, tok := newTestServer(t)
	cases := []struct {
		origin, host string
		want         int
	}{
		{site, "127.0.0.1:47615", 200},
		{site, "localhost:47615", 200},
		{"", "127.0.0.1:47615", 403},
		{"https://evil.example", "127.0.0.1:47615", 403},
		{"http://localhost:3000", "127.0.0.1:47615", 403}, // без --dev
		{site, "evil.example:47615", 403},                 // DNS rebinding
	}
	for _, c := range cases {
		if got := do(s, "GET", "/status", c.origin, c.host, tok, "").Code; got != c.want {
			t.Errorf("origin %q host %q: got %d, want %d", c.origin, c.host, got, c.want)
		}
	}
}

func TestTokenRequired(t *testing.T) {
	s, tok := newTestServer(t)
	for _, path := range []string{"/run", "/ensure", "/task", "/file", "/submission", "/cancel"} {
		if got := do(s, "POST", path, site, "127.0.0.1:47615", "", "{}").Code; got != 401 {
			t.Errorf("%s without token: got %d", path, got)
		}
		if got := do(s, "POST", path, site, "127.0.0.1:47615", "wrong", "{}").Code; got != 401 {
			t.Errorf("%s with wrong token: got %d", path, got)
		}
	}
	if got := do(s, "POST", "/ensure", site, "127.0.0.1:47615", tok, `{"language":"python","pip":["--index-url=http://x"]}`).Code; got != 400 {
		t.Errorf("option-like package name accepted: %d", got)
	}
	for _, pkg := range []string{"--registry=http://x", "@evil/pkg", "git+https://x/y.git", "../x", "express@latest; rm"} {
		body := `{"language":"node","npm":["` + pkg + `"]}`
		if got := do(s, "POST", "/ensure", site, "127.0.0.1:47615", tok, body).Code; got != 400 {
			t.Errorf("npm package %q accepted: %d", pkg, got)
		}
	}
	if !validNpmPackages([]string{"express", "express@5", "express@5.1.0"}) {
		t.Error("plain npm package names rejected")
	}
}

func TestPairingLocksAfterWrongCodes(t *testing.T) {
	p := NewPairing(filepath.Join(t.TempDir(), "tokens.json"))
	for i := 0; i < pairAttempts; i++ {
		p.Pair("000000x")
	}
	if tok, reason := p.Pair(p.code); tok != "" || reason != "locked" {
		t.Fatalf("expected locked, got %q %q", tok, reason)
	}
}

func TestTaskPathsStayInsideFolder(t *testing.T) {
	s, tok := newTestServer(t)
	bad := []string{"../x", "a/../../x", "/abs", `a\..\..\x`, "..", "a//b", ".hidden", "a/./b", "C:/x"}
	for _, p := range bad {
		body, _ := json.Marshal(map[string]any{"key": "k", "path": p, "ext": "py", "title": "t", "statement": "", "starter": ""})
		if got := do(s, "POST", "/task", site, "127.0.0.1:47615", tok, string(body)).Code; got != 400 {
			t.Errorf("path %q accepted (%d)", p, got)
		}
	}
	body, _ := json.Marshal(map[string]any{
		"key": "python/v2/loops/b", "path": "python/loops/b", "ext": "py", "title": "B", "statement": "text", "starter": "print(1)\n",
		"examples": []map[string]string{{"in": "1\n", "out": "2\n"}},
	})
	rec := do(s, "POST", "/task", site, "127.0.0.1:47615", tok, string(body))
	if rec.Code != 200 {
		t.Fatalf("task: %d %s", rec.Code, rec.Body)
	}
	dir := s.ws.Path("courses", "python", "loops", "b")
	for _, f := range []string{"main.py", "README.md", "tests/01.in", "tests/01.out"} {
		if _, err := os.Stat(filepath.Join(dir, filepath.FromSlash(f))); err != nil {
			t.Errorf("missing %s", f)
		}
	}
}

func TestFileSyncKeepsEditorChanges(t *testing.T) {
	s, _ := newTestServer(t)
	st, err := s.tasks.Open(TaskRequest{Key: "k", Path: "py/t", Ext: "py", Starter: "a = 1\n"})
	if err != nil {
		t.Fatal(err)
	}
	// Ученик правит файл в редакторе, а сайт ещё не видел правку и присылает свою версию
	if err := os.WriteFile(st.File, []byte("edited in vscode\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := s.tasks.Write("k", "from site\n", "stale"); err != nil {
		t.Fatal(err)
	}
	entries, _ := os.ReadDir(filepath.Join(st.Folder, "submissions"))
	found := false
	for _, e := range entries {
		data, _ := os.ReadFile(filepath.Join(st.Folder, "submissions", e.Name()))
		if strings.HasSuffix(e.Name(), "_autosave.py") && string(data) == "edited in vscode\n" {
			found = true
		}
	}
	if !found {
		t.Fatal("editor version was not backed up")
	}
	// Повторное открытие не перезаписывает решение
	st2, _ := s.tasks.Open(TaskRequest{Key: "k", Path: "py/t", Ext: "py", Starter: "starter\n"})
	if st2.Content != "from site\n" {
		t.Fatalf("solution overwritten: %q", st2.Content)
	}
}

func TestRustCratesOnlyFromBuiltInKits(t *testing.T) {
	s, tok := newTestServer(t)
	bad := []string{
		`{"language":"rust","crates":["evil"]}`,
		`{"language":"rust","crates":["macroquad","macroquad"]}`,
		`{"language":"rust","crates":["macroquad = { git = \"https://x\" }"]}`,
		`{"language":"python","crates":["macroquad"]}`,
	}
	for _, body := range bad {
		if got := do(s, "POST", "/ensure", site, "127.0.0.1:47615", tok, body).Code; got != 400 {
			t.Errorf("ensure %s accepted: %d", body, got)
		}
	}
	run := `{"runId":"r1","language":"rust","code":"fn main(){}","timeLimitMs":1000,"outputLimitBytes":1000,"crates":["serde"]}`
	if got := do(s, "POST", "/run", site, "127.0.0.1:47615", tok, run).Code; got != 400 {
		t.Errorf("run with unknown crate accepted: %d", got)
	}
	if !validCrates("rust", []string{"macroquad"}) || !validCrates("rust", nil) || !validCrates("python", nil) {
		t.Error("built-in kit rejected")
	}
	// Без Rust и cargo набор не готов, и запуск игры честно говорит «не установлено»
	res := s.ws.Run(RunRequest{RunID: "r2", Language: "rust", Code: "fn main(){}", TimeLimitMs: 1000, OutputLimitBytes: 1000, Crates: []string{"macroquad"}}, s.runs)
	if res.Status != "env-error" || res.Error != "not-installed" {
		t.Errorf("game without kit: %+v", res)
	}
}

func TestKitsArePinned(t *testing.T) {
	for name, k := range rustKits {
		if !strings.Contains(k.toml, `"=`) {
			t.Errorf("%s: версии в Cargo.toml должны быть точными (=x.y.z)", name)
		}
		if !strings.Contains(k.lock, "\nname = \""+name+"\"\n") || !strings.Contains(k.lock, "checksum = ") {
			t.Errorf("%s: в Cargo.lock нет крейта или контрольных сумм", name)
		}
		if strings.Contains(k.lock, "git+") || strings.Contains(k.toml, "git =") || strings.Contains(k.toml, "path =") {
			t.Errorf("%s: крейты только из crates.io", name)
		}
		if strings.Contains(k.toml+k.lock+k.warm, "\r") {
			t.Errorf("%s: концы строк не приведены к \\n", name)
		}
	}
	if _, ok := rustKits["macroquad"]; !ok {
		t.Fatal("набор macroquad не встроен")
	}
}

func TestCleanCargoMessages(t *testing.T) {
	dir := filepath.Join("C:", "Users", "x", "CodeWithMe", "envs", "rust", "macroquad")
	in := "error[E0308]: mismatched types\n --> " + filepath.Join("src", "main.rs") + ":4:18\n  |\n\n" +
		"error: could not compile `game` (bin \"game\") due to 1 previous error\n" + dir + string(filepath.Separator) + "Cargo.toml\n"
	got := cleanCargo(in, dir)
	if strings.Contains(got, "could not compile") || strings.Contains(got, "src") || strings.Contains(got, "CodeWithMe") {
		t.Fatalf("not cleaned: %q", got)
	}
	if !strings.Contains(got, "--> main.rs:4:18") {
		t.Fatalf("lost location: %q", got)
	}
}

func TestCargoEnvInsideFolder(t *testing.T) {
	ws := &Workspace{Root: t.TempDir()}
	env := map[string]string{}
	for _, kv := range ws.cargoEnv(ws.kitDir("macroquad")) {
		k, v, _ := strings.Cut(kv, "=")
		env[strings.ToUpper(k)] = v
	}
	for _, k := range []string{"CARGO_HOME", "CARGO_TARGET_DIR", "RUSTC"} {
		if !strings.HasPrefix(env[k], ws.Root) {
			t.Errorf("%s=%q is outside the folder", k, env[k])
		}
	}
	if env["RUSTFLAGS"] != "" || env["RUSTC_WRAPPER"] != "" {
		t.Error("чужие настройки сборки не сброшены")
	}
}

func TestEnvRedirectsCaches(t *testing.T) {
	ws := &Workspace{Root: t.TempDir()}
	env := map[string]string{}
	for _, kv := range ws.Env(nil) {
		k, v, _ := strings.Cut(kv, "=")
		env[k] = v
	}
	for _, k := range []string{"UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR", "UV_PYTHON_BIN_DIR", "PIP_CACHE_DIR", "npm_config_cache", "MPLCONFIGDIR", "TEMP", "TMP", "TMPDIR"} {
		if !strings.HasPrefix(env[k], ws.Root) {
			t.Errorf("%s=%q is outside the folder", k, env[k])
		}
	}
}
