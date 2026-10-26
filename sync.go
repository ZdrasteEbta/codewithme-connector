package main

// Задачи в папке courses/: решение (main.py / main.js), условие, примеры тестов и история отправок.
// Файл решения — общий для сайта и редактора ученика: правка в одном месте видна в другом.

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

var (
	segmentRE = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$`)
	verdictRE = regexp.MustCompile(`^[A-Za-z-]{1,20}$`)
	extRE     = regexp.MustCompile(`^(py|js|html)$`)
)

type taskInfo struct {
	Path string `json:"path"` // относительно courses/, через /
	Ext  string `json:"ext"`
}

type Tasks struct {
	ws    *Workspace
	mu    sync.Mutex
	known map[string]taskInfo
}

func NewTasks(ws *Workspace) *Tasks {
	t := &Tasks{ws: ws, known: map[string]taskInfo{}}
	if data, err := os.ReadFile(ws.Path(".cwm", "tasks.json")); err == nil {
		_ = json.Unmarshal(data, &t.known)
	}
	return t
}

func validTaskPath(p string) bool {
	parts := strings.Split(p, "/")
	if len(parts) == 0 || len(parts) > 6 {
		return false
	}
	for _, s := range parts {
		if !segmentRE.MatchString(s) || strings.Trim(s, ".") == "" {
			return false
		}
	}
	return true
}

func (t *Tasks) dir(info taskInfo) string {
	return t.ws.Path(append([]string{"courses"}, strings.Split(info.Path, "/")...)...)
}

func (t *Tasks) mainFile(info taskInfo) string {
	return filepath.Join(t.dir(info), "main."+info.Ext)
}

type TaskRequest struct {
	Key       string `json:"key"`
	Path      string `json:"path"`
	Ext       string `json:"ext"`
	Title     string `json:"title"`
	Statement string `json:"statement"`
	Starter   string `json:"starter"`
	Examples  []struct {
		In  string `json:"in"`
		Out string `json:"out"`
	} `json:"examples"`
}

type FileState struct {
	Folder  string `json:"folder"`
	File    string `json:"file"`
	Content string `json:"content"`
	Version string `json:"version"`
}

func fileVersion(path string) string {
	st, err := os.Stat(path)
	if err != nil {
		return "0"
	}
	return strconv.FormatInt(st.ModTime().UnixNano(), 36) + "-" + strconv.FormatInt(st.Size(), 36)
}

// Open создаёт папку задачи (если её нет) и возвращает текущее решение.
// Уже существующий файл решения не перезаписывается — это работа ученика.
func (t *Tasks) Open(req TaskRequest) (FileState, error) {
	if req.Key == "" || len(req.Key) > 200 || !validTaskPath(req.Path) || !extRE.MatchString(req.Ext) {
		return FileState{}, errors.New("bad-request")
	}
	info := taskInfo{Path: req.Path, Ext: req.Ext}
	t.mu.Lock()
	t.known[req.Key] = info
	data, _ := json.MarshalIndent(t.known, "", "  ")
	t.mu.Unlock()
	if err := writeFileAtomic(t.ws.Path(".cwm", "tasks.json"), data); err != nil {
		return FileState{}, err
	}
	dir := t.dir(info)
	if err := os.MkdirAll(filepath.Join(dir, "submissions"), 0o755); err != nil {
		return FileState{}, err
	}
	main := t.mainFile(info)
	if _, err := os.Stat(main); errors.Is(err, os.ErrNotExist) {
		if err := os.WriteFile(main, []byte(req.Starter), 0o644); err != nil {
			return FileState{}, err
		}
	}
	// Условие и примеры обновляем всегда: они с сайта, ученик их не редактирует
	readme := "# " + req.Title + "\n\n" + req.Statement + "\n"
	_ = os.WriteFile(filepath.Join(dir, "README.md"), []byte(readme), 0o644)
	if len(req.Examples) > 0 {
		tests := filepath.Join(dir, "tests")
		_ = os.MkdirAll(tests, 0o755)
		for i, ex := range req.Examples {
			if i >= 20 {
				break
			}
			n := fmt.Sprintf("%02d", i+1)
			_ = os.WriteFile(filepath.Join(tests, n+".in"), []byte(ex.In), 0o644)
			_ = os.WriteFile(filepath.Join(tests, n+".out"), []byte(ex.Out), 0o644)
		}
	}
	return t.Read(req.Key)
}

func (t *Tasks) info(key string) (taskInfo, bool) {
	t.mu.Lock()
	defer t.mu.Unlock()
	info, ok := t.known[key]
	return info, ok
}

func (t *Tasks) Read(key string) (FileState, error) {
	info, ok := t.info(key)
	if !ok {
		return FileState{}, errors.New("unknown-task")
	}
	main := t.mainFile(info)
	data, err := os.ReadFile(main)
	if err != nil {
		return FileState{}, err
	}
	return FileState{Folder: t.dir(info), File: main, Content: string(data), Version: fileVersion(main)}, nil
}

// Write сохраняет код с сайта. Если файл успели изменить в редакторе после того,
// как сайт его видел (base устарел), прежний текст сохраняется в submissions/ — ничего не теряется.
func (t *Tasks) Write(key, content, base string) (FileState, error) {
	info, ok := t.info(key)
	if !ok {
		return FileState{}, errors.New("unknown-task")
	}
	t.ws.mu.Lock()
	defer t.ws.mu.Unlock()
	main := t.mainFile(info)
	old, err := os.ReadFile(main)
	if err == nil && string(old) != content && base != fileVersion(main) {
		name := time.Now().Format("2006-01-02_15-04-05") + "_autosave." + info.Ext
		_ = os.WriteFile(filepath.Join(t.dir(info), "submissions", name), old, 0o644)
		logf("Файл %s изменился и на сайте, и в редакторе — прежняя версия сохранена в submissions/%s", info.Path, name)
	}
	if err != nil || string(old) != content {
		if err := os.MkdirAll(t.dir(info), 0o755); err != nil {
			return FileState{}, err
		}
		if err := os.WriteFile(main, []byte(content), 0o644); err != nil {
			return FileState{}, err
		}
	}
	return FileState{Folder: t.dir(info), File: main, Content: content, Version: fileVersion(main)}, nil
}

// Submission сохраняет отправку: код и отчёт с вердиктами по тестам
func (t *Tasks) Submission(key, code, verdict, report string) (string, error) {
	info, ok := t.info(key)
	if !ok {
		return "", errors.New("unknown-task")
	}
	if !verdictRE.MatchString(verdict) {
		verdict = "result"
	}
	dir := filepath.Join(t.dir(info), "submissions")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	name := time.Now().Format("2006-01-02_15-04-05") + "_" + verdict
	if err := os.WriteFile(filepath.Join(dir, name+"."+info.Ext), []byte(code), 0o644); err != nil {
		return "", err
	}
	if report != "" {
		_ = os.WriteFile(filepath.Join(dir, name+".txt"), []byte(report), 0o644)
	}
	return name, nil
}
