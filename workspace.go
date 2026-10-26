package main

// Папка ученика: всё, что коннектор скачивает и создаёт, лежит только в ней.
// Чтобы удалить с компьютера всё, что поставил коннектор, достаточно удалить эту папку.

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
)

const readme = `Папка CodeWithMe (https://codewithme.app)

Здесь лежит всё, что коннектор CodeWithMe поставил и создал на этом компьютере:

  courses/    ваш код, условия задач, примеры тестов и история отправок
  runtimes/   Python и Node.js — ставятся при первом запуске кода на этом языке
  envs/       библиотеки Python, которые вы учите (numpy, pygame и т. д.)
  tools/      uv — программа, которая ставит Python и библиотеки
  cache/      скачанные файлы и временные файлы программ
  .cwm/       настройки коннектора

Коннектор ничего не пишет за пределами этой папки: не меняет PATH, реестр и
системные настройки. Чтобы удалить всё — закройте коннектор и удалите эту папку.

Исходный код коннектора: https://github.com/ZdrasteEbta/codewithme-connector

---

CodeWithMe folder. Everything the CodeWithMe connector installed or created on
this computer lives here. To remove it all, close the connector and delete this folder.
`

type Workspace struct {
	Root string
	mu   sync.Mutex
}

func (w *Workspace) Path(parts ...string) string {
	return filepath.Join(append([]string{w.Root}, parts...)...)
}

// Prepare создаёт базовую структуру папки
func (w *Workspace) Prepare() error {
	for _, d := range []string{".cwm", "courses", "cache/tmp"} {
		if err := os.MkdirAll(w.Path(filepath.FromSlash(d)), 0o755); err != nil {
			return err
		}
	}
	readmePath := w.Path("README.txt")
	if _, err := os.Stat(readmePath); errors.Is(err, os.ErrNotExist) {
		return os.WriteFile(readmePath, []byte(readme), 0o644)
	}
	return nil
}

// Env — окружение для программ, которые запускает коннектор:
// кэши, временные файлы и установки библиотек направлены внутрь папки.
func (w *Workspace) Env(extra map[string]string) []string {
	cache := w.Path("cache")
	tmp := w.Path("cache", "tmp")
	vars := map[string]string{
		"UV_CACHE_DIR":                filepath.Join(cache, "uv"),
		"UV_PYTHON_INSTALL_DIR":       w.Path("runtimes", "python"),
		"UV_PYTHON_BIN_DIR":           w.Path("tools", "bin"),
		"UV_TOOL_DIR":                 w.Path("tools", "uv-tools"),
		"UV_PYTHON_PREFERENCE":        "only-managed",
		"UV_PYTHON_INSTALL_REGISTRY":  "0",
		"UV_NO_CONFIG":                "1",
		"UV_NO_MODIFY_PATH":           "1",
		"PIP_CACHE_DIR":               filepath.Join(cache, "pip"),
		"npm_config_cache":            filepath.Join(cache, "npm"),
		"MPLCONFIGDIR":                filepath.Join(cache, "matplotlib"),
		"HF_HOME":                     filepath.Join(cache, "huggingface"),
		"TORCH_HOME":                  filepath.Join(cache, "torch"),
		"XDG_CACHE_HOME":              cache,
		"TEMP":                        tmp,
		"TMP":                         tmp,
		"TMPDIR":                      tmp,
		"PYTHONIOENCODING":            "utf-8",
		"PYGAME_HIDE_SUPPORT_PROMPT":  "1",
	}
	for k, v := range extra {
		vars[k] = v
	}
	var env []string
	for _, kv := range os.Environ() {
		k, _, _ := strings.Cut(kv, "=")
		up := strings.ToUpper(k)
		if strings.HasPrefix(up, "PYTHON") || strings.HasPrefix(up, "VIRTUAL_ENV") || strings.HasPrefix(up, "NODE_") {
			continue // настройки чужого Python/Node не должны влиять на запуск
		}
		if _, ok := vars[k]; ok {
			continue
		}
		if runtime.GOOS == "windows" {
			if _, ok := vars[up]; ok {
				continue
			}
		}
		env = append(env, kv)
	}
	for k, v := range vars {
		env = append(env, k+"="+v)
	}
	return env
}

// state.json — что уже поставлено (чтобы не спрашивать uv при каждом запуске)
type State struct {
	Python   bool            `json:"python"`
	Node     string          `json:"node,omitempty"`
	Packages map[string]bool `json:"packages"`
}

func (w *Workspace) LoadState() State {
	s := State{Packages: map[string]bool{}}
	data, err := os.ReadFile(w.Path(".cwm", "state.json"))
	if err == nil {
		_ = json.Unmarshal(data, &s)
	}
	if s.Packages == nil {
		s.Packages = map[string]bool{}
	}
	// Папку могли почистить вручную — доверяем только тому, что есть на диске
	if s.Python {
		if _, err := os.Stat(w.PythonExe()); err != nil {
			s.Python = false
			s.Packages = map[string]bool{}
		}
	}
	if s.Node != "" {
		if _, err := os.Stat(w.NodeExe()); err != nil {
			s.Node = ""
		}
	}
	return s
}

func (w *Workspace) SaveState(s State) error {
	data, _ := json.MarshalIndent(s, "", "  ")
	return writeFileAtomic(w.Path(".cwm", "state.json"), data)
}

func (w *Workspace) PythonExe() string {
	if runtime.GOOS == "windows" {
		return w.Path("envs", "python", "Scripts", "python.exe")
	}
	return w.Path("envs", "python", "bin", "python")
}

func (w *Workspace) NodeExe() string {
	if runtime.GOOS == "windows" {
		return w.Path("runtimes", "node", "node.exe")
	}
	return w.Path("runtimes", "node", "bin", "node")
}

func (w *Workspace) UvExe() string {
	if runtime.GOOS == "windows" {
		return w.Path("tools", "uv", "uv.exe")
	}
	return w.Path("tools", "uv", "uv")
}

func writeFileAtomic(path string, data []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}
