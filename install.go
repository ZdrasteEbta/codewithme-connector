package main

// Ленивая установка: Python, Node.js и библиотеки ставятся в папку только тогда,
// когда ученик впервые запускает код на этом языке или в курсе с этой библиотекой.

import (
	"archive/tar"
	"archive/zip"
	"bufio"
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
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

const pythonVersion = "3.12"

var packageRE = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}(==[0-9][0-9A-Za-z.+-]{0,31})?$`)

type InstallStatus struct {
	State string `json:"state"` // ready | installing | error
	Step  string `json:"step,omitempty"`
	Error string `json:"error,omitempty"`
}

type Installer struct {
	ws      *Workspace
	mu      sync.Mutex
	running bool
	step    string
	lastErr string
	errKey  string
}

func NewInstaller(ws *Workspace) *Installer { return &Installer{ws: ws} }

func normPkg(p string) string {
	name, _, _ := strings.Cut(p, "==")
	return strings.ToLower(strings.ReplaceAll(name, "_", "-"))
}

// missing возвращает, чего не хватает для языка и списка библиотек
func (in *Installer) missing(lang string, pkgs []string) (needRuntime bool, needPkgs []string) {
	s := in.ws.LoadState()
	switch lang {
	case "python":
		needRuntime = !s.Python
		for _, p := range pkgs {
			if !s.Packages[normPkg(p)] {
				needPkgs = append(needPkgs, p)
			}
		}
	case "javascript":
		needRuntime = s.Node == ""
	}
	return
}

// Ensure проверяет, всё ли готово, и при необходимости запускает установку в фоне.
// Сайт повторяет запрос раз в секунду и показывает ученику шаг установки.
func (in *Installer) Ensure(lang string, pkgs []string) InstallStatus {
	in.mu.Lock()
	defer in.mu.Unlock()
	if in.running {
		return InstallStatus{State: "installing", Step: in.step}
	}
	needRuntime, needPkgs := in.missing(lang, pkgs)
	if !needRuntime && len(needPkgs) == 0 {
		return InstallStatus{State: "ready"}
	}
	key := lang + ":" + strings.Join(pkgs, ",")
	if in.lastErr != "" && in.errKey == key {
		// Ошибку показываем один раз; следующий запрос пробует установить заново
		err := in.lastErr
		in.lastErr, in.errKey = "", ""
		return InstallStatus{State: "error", Error: err}
	}
	in.running = true
	in.step = "Готовлю установку"
	go func() {
		err := in.install(lang, needRuntime, needPkgs)
		in.mu.Lock()
		in.running = false
		in.step = ""
		if err != nil {
			in.lastErr, in.errKey = err.Error(), key
			logf("Ошибка установки: %v", err)
		}
		in.mu.Unlock()
	}()
	return InstallStatus{State: "installing", Step: in.step}
}

func (in *Installer) setStep(step string) {
	in.mu.Lock()
	in.step = step
	in.mu.Unlock()
	logf("%s…", step)
}

func (in *Installer) install(lang string, needRuntime bool, pkgs []string) error {
	ws := in.ws
	switch lang {
	case "python":
		if needRuntime {
			if err := in.ensureUv(); err != nil {
				return err
			}
			in.setStep("Скачиваю Python " + pythonVersion)
			if err := in.uv("venv", ws.Path("envs", "python"), "--python", pythonVersion, "--allow-existing"); err != nil {
				return fmt.Errorf("не удалось поставить Python: %w", err)
			}
			s := ws.LoadState()
			s.Python = true
			if err := ws.SaveState(s); err != nil {
				return err
			}
			logf("Python готов.")
		}
		if len(pkgs) > 0 {
			if err := in.ensureUv(); err != nil {
				return err
			}
			names := make([]string, len(pkgs))
			for i, p := range pkgs {
				names[i], _, _ = strings.Cut(p, "==")
			}
			in.setStep("Ставлю " + strings.Join(names, ", "))
			args := append([]string{"pip", "install", "--python", ws.PythonExe()}, pkgs...)
			if err := in.uv(args...); err != nil {
				return fmt.Errorf("не удалось поставить %s: %w", strings.Join(names, ", "), err)
			}
			s := ws.LoadState()
			for _, p := range pkgs {
				s.Packages[normPkg(p)] = true
			}
			if err := ws.SaveState(s); err != nil {
				return err
			}
			logf("Библиотеки готовы: %s", strings.Join(names, ", "))
		}
	case "javascript":
		if needRuntime {
			in.setStep("Скачиваю Node.js")
			version, err := in.installNode()
			if err != nil {
				return fmt.Errorf("не удалось поставить Node.js: %w", err)
			}
			s := ws.LoadState()
			s.Node = version
			if err := ws.SaveState(s); err != nil {
				return err
			}
			logf("Node.js %s готов.", version)
		}
	default:
		return fmt.Errorf("неизвестный язык %q", lang)
	}
	return nil
}

// uv запускает менеджер Python с окружением, направленным в папку
func (in *Installer) uv(args ...string) error {
	_ = os.MkdirAll(in.ws.Path("cache", "tmp"), 0o755)
	cmd := exec.Command(in.ws.UvExe(), args...)
	cmd.Dir = in.ws.Root
	cmd.Env = in.ws.Env(nil)
	hideWindow(cmd)
	var out bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &out
	if err := cmd.Run(); err != nil {
		text := strings.TrimSpace(out.String())
		if len(text) > 1500 {
			text = "…" + text[len(text)-1500:]
		}
		return fmt.Errorf("%v\n%s", err, text)
	}
	return nil
}

func uvAsset() (string, error) {
	switch runtime.GOOS + "/" + runtime.GOARCH {
	case "windows/amd64":
		return "uv-x86_64-pc-windows-msvc.zip", nil
	case "windows/arm64":
		return "uv-aarch64-pc-windows-msvc.zip", nil
	case "darwin/arm64":
		return "uv-aarch64-apple-darwin.tar.gz", nil
	case "darwin/amd64":
		return "uv-x86_64-apple-darwin.tar.gz", nil
	case "linux/amd64":
		return "uv-x86_64-unknown-linux-gnu.tar.gz", nil
	case "linux/arm64":
		return "uv-aarch64-unknown-linux-gnu.tar.gz", nil
	}
	return "", fmt.Errorf("эта система (%s/%s) пока не поддерживается", runtime.GOOS, runtime.GOARCH)
}

func (in *Installer) ensureUv() error {
	if _, err := os.Stat(in.ws.UvExe()); err == nil {
		return nil
	}
	in.setStep("Скачиваю установщик Python (uv)")
	asset, err := uvAsset()
	if err != nil {
		return err
	}
	base := "https://github.com/astral-sh/uv/releases/latest/download/" + asset
	sumText, err := httpGet(base+".sha256", 1<<16)
	if err != nil {
		return fmt.Errorf("не удалось скачать uv: %w", err)
	}
	want := strings.Fields(string(sumText))
	if len(want) == 0 {
		return fmt.Errorf("не удалось прочитать контрольную сумму uv")
	}
	archive, err := download(in.ws, base, want[0])
	if err != nil {
		return fmt.Errorf("не удалось скачать uv: %w", err)
	}
	defer os.Remove(archive)
	dir := in.ws.Path("tools", "uv")
	exe := filepath.Base(in.ws.UvExe())
	keep := func(name string) (string, bool) {
		b := filepath.Base(name)
		if b == exe {
			return b, true
		}
		return "", false
	}
	return extract(archive, dir, keep)
}

func nodeAsset() (string, error) {
	switch runtime.GOOS + "/" + runtime.GOARCH {
	case "windows/amd64":
		return "win-x64.zip", nil
	case "windows/arm64":
		return "win-arm64.zip", nil
	case "darwin/arm64":
		return "darwin-arm64.tar.gz", nil
	case "darwin/amd64":
		return "darwin-x64.tar.gz", nil
	case "linux/amd64":
		return "linux-x64.tar.gz", nil
	case "linux/arm64":
		return "linux-arm64.tar.gz", nil
	}
	return "", fmt.Errorf("эта система (%s/%s) пока не поддерживается", runtime.GOOS, runtime.GOARCH)
}

// installNode скачивает последнюю версию Node.js 22 (LTS) с nodejs.org и сверяет SHA-256
func (in *Installer) installNode() (string, error) {
	suffix, err := nodeAsset()
	if err != nil {
		return "", err
	}
	const dist = "https://nodejs.org/dist/latest-v22.x/"
	sums, err := httpGet(dist+"SHASUMS256.txt", 1<<20)
	if err != nil {
		return "", err
	}
	var file, sum string
	sc := bufio.NewScanner(bytes.NewReader(sums))
	for sc.Scan() {
		f := strings.Fields(sc.Text())
		if len(f) == 2 && strings.HasPrefix(f[1], "node-v") && strings.HasSuffix(f[1], "-"+suffix) {
			sum, file = f[0], f[1]
		}
	}
	if file == "" {
		return "", fmt.Errorf("не найден архив Node.js для этой системы")
	}
	archive, err := download(in.ws, dist+file, sum)
	if err != nil {
		return "", err
	}
	defer os.Remove(archive)
	dir := in.ws.Path("runtimes", "node")
	_ = os.RemoveAll(dir)
	// Архив содержит одну папку node-v22.x.y-…: убираем её из путей
	strip := func(name string) (string, bool) {
		_, rest, ok := strings.Cut(filepath.ToSlash(name), "/")
		return rest, ok && rest != ""
	}
	if err := extract(archive, dir, strip); err != nil {
		return "", err
	}
	version := strings.TrimPrefix(strings.SplitN(file, "-", 3)[1], "v")
	return version, nil
}

var client = &http.Client{Timeout: 30 * time.Minute}

func httpGet(url string, limit int64) ([]byte, error) {
	resp, err := client.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("%s: HTTP %d", url, resp.StatusCode)
	}
	return io.ReadAll(io.LimitReader(resp.Body, limit))
}

// download скачивает файл в cache/downloads и проверяет SHA-256
func download(ws *Workspace, url, wantSum string) (string, error) {
	dir := ws.Path("cache", "downloads")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	path := filepath.Join(dir, filepath.Base(url))
	var lastErr error
	for attempt := 0; attempt < 3; attempt++ {
		lastErr = func() error {
			resp, err := client.Get(url)
			if err != nil {
				return err
			}
			defer resp.Body.Close()
			if resp.StatusCode != 200 {
				return fmt.Errorf("HTTP %d", resp.StatusCode)
			}
			f, err := os.Create(path)
			if err != nil {
				return err
			}
			h := sha256.New()
			_, err = io.Copy(io.MultiWriter(f, h), resp.Body)
			f.Close()
			if err != nil {
				return err
			}
			if got := hex.EncodeToString(h.Sum(nil)); !strings.EqualFold(got, wantSum) {
				return fmt.Errorf("контрольная сумма не совпала: файл повреждён или подменён")
			}
			return nil
		}()
		if lastErr == nil {
			return path, nil
		}
		os.Remove(path)
	}
	return "", lastErr
}

// extract распаковывает zip или tar.gz; rename решает, какие файлы брать и куда класть
func extract(archive, dir string, rename func(string) (string, bool)) error {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	safe := func(name string) (string, bool) {
		rel, ok := rename(name)
		if !ok {
			return "", false
		}
		rel = filepath.Clean(filepath.FromSlash(rel))
		if filepath.IsAbs(rel) || rel == "." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) || rel == ".." {
			return "", false
		}
		return filepath.Join(dir, rel), true
	}
	if strings.HasSuffix(archive, ".zip") {
		zr, err := zip.OpenReader(archive)
		if err != nil {
			return err
		}
		defer zr.Close()
		for _, f := range zr.File {
			if f.FileInfo().IsDir() {
				continue
			}
			target, ok := safe(f.Name)
			if !ok {
				continue
			}
			rc, err := f.Open()
			if err != nil {
				return err
			}
			err = writeFrom(target, rc, f.Mode())
			rc.Close()
			if err != nil {
				return err
			}
		}
		return nil
	}
	file, err := os.Open(archive)
	if err != nil {
		return err
	}
	defer file.Close()
	gz, err := gzip.NewReader(file)
	if err != nil {
		return err
	}
	tr := tar.NewReader(gz)
	var links [][2]string
	for {
		h, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
		target, ok := safe(h.Name)
		if !ok {
			continue
		}
		switch h.Typeflag {
		case tar.TypeReg:
			if err := writeFrom(target, tr, os.FileMode(h.Mode)); err != nil {
				return err
			}
		case tar.TypeSymlink:
			// Ссылки только внутри распакованной папки (npm → ../lib/…)
			resolved := filepath.Join(filepath.Dir(target), filepath.FromSlash(h.Linkname))
			if !filepath.IsAbs(h.Linkname) && strings.HasPrefix(resolved, dir+string(filepath.Separator)) {
				links = append(links, [2]string{h.Linkname, target})
			}
		}
	}
	for _, l := range links {
		_ = os.MkdirAll(filepath.Dir(l[1]), 0o755)
		_ = os.Symlink(l[0], l[1])
	}
	return nil
}

func writeFrom(target string, r io.Reader, mode os.FileMode) error {
	if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
		return err
	}
	perm := os.FileMode(0o644)
	if mode&0o111 != 0 {
		perm = 0o755
	}
	f, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, perm)
	if err != nil {
		return err
	}
	_, err = io.Copy(f, r)
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	return err
}

func validPackages(pkgs []string) bool {
	if len(pkgs) > 20 {
		return false
	}
	for _, p := range pkgs {
		if !packageRE.MatchString(p) {
			return false
		}
	}
	return true
}

func sortedPackages(pkgs map[string]bool) []string {
	var out []string
	for p, ok := range pkgs {
		if ok {
			out = append(out, p)
		}
	}
	sort.Strings(out)
	return out
}
