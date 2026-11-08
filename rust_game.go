package main

// Игры на Rust (курс GameDev): программа ученика собирается cargo вместе с крейтами.
// Крейты выбирает не сайт: в коннектор встроены «наборы» — Cargo.toml и Cargo.lock с точными
// версиями и контрольными суммами (сейчас один набор — macroquad). Сайт может только назвать набор.
// cargo ставится при первом запуске игрового курса — ровно той же версии, что и rustc.
// Набор один раз собирается заранее (прогрев) в envs/rust/<набор>; потом пересобирается
// только код ученика — около секунды. Готовая игра копируется в cache/rust-game по хешу кода,
// чтобы открытое окно прошлой версии игры не мешало собрать новую.

import (
	"bytes"
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
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

//go:embed kits/macroquad/Cargo.toml kits/macroquad/Cargo.lock kits/macroquad/warm.rs
var kitFiles embed.FS

type rustKit struct {
	toml, lock string
	warm       string // программа прогрева: собирает все крейты набора
}

// rustKits — наборы крейтов, которые разрешено собирать
var rustKits = map[string]rustKit{}

func init() {
	for _, name := range []string{"macroquad"} {
		read := func(file string) string {
			data, err := kitFiles.ReadFile("kits/" + name + "/" + file)
			if err != nil {
				panic("набор " + name + ": нет " + file)
			}
			// git на Windows мог поменять концы строк — для cargo и хеша приводим к \n
			return strings.ReplaceAll(string(data), "\r\n", "\n")
		}
		rustKits[name] = rustKit{toml: read("Cargo.toml"), lock: read("Cargo.lock"), warm: read("warm.rs")}
	}
}

func (k rustKit) hash() string {
	sum := sha256.Sum256([]byte(k.toml + "\x00" + k.lock + "\x00" + k.warm))
	return hex.EncodeToString(sum[:])[:16]
}

// validCrates: набор можно назвать только для Rust и только из встроенного списка
func validCrates(lang string, crates []string) bool {
	if len(crates) == 0 {
		return true
	}
	if lang != "rust" || len(crates) > 1 {
		return false
	}
	_, ok := rustKits[crates[0]]
	return ok
}

func exeSuffix() string {
	if runtime.GOOS == "windows" {
		return ".exe"
	}
	return ""
}

func (w *Workspace) CargoExe() string { return w.Path("runtimes", "rust", "bin", "cargo"+exeSuffix()) }

func (w *Workspace) kitDir(name string) string { return w.Path("envs", "rust", name) }

// kitReady — набор прогрет этой версией набора и этим Rust
func (w *Workspace) kitReady(name, rustVersion string) bool {
	k, ok := rustKits[name]
	if !ok || rustVersion == "" {
		return false
	}
	if _, err := os.Stat(w.CargoExe()); err != nil {
		return false
	}
	data, err := os.ReadFile(filepath.Join(w.kitDir(name), ".ready"))
	return err == nil && strings.TrimSpace(string(data)) == k.hash()+" "+rustVersion
}

// readyKits — прогретые наборы (для /status)
func (w *Workspace) readyKits(rustVersion string) []string {
	out := []string{}
	for name := range rustKits {
		if w.kitReady(name, rustVersion) {
			out = append(out, name)
		}
	}
	sort.Strings(out)
	return out
}

// cargoEnv — окружение для cargo: свой CARGO_HOME в папке, наш rustc, без чужих настроек сборки
func (w *Workspace) cargoEnv(dir string) []string {
	target, _ := rustTarget()
	return w.Env(map[string]string{
		"CARGO_HOME":               w.Path("cache", "cargo"),
		"CARGO_TARGET_DIR":         filepath.Join(dir, "target"),
		"CARGO_BUILD_TARGET":       target,
		"CARGO_TERM_COLOR":         "never",
		"CARGO_TERM_PROGRESS_WHEN": "never",
		"CARGO_INCREMENTAL":        "1",
		"RUSTC":                    w.RustcExe(),
		"RUSTC_WRAPPER":            "",
		"RUSTFLAGS":                "",
		"PATH":                     filepath.Dir(w.RustcExe()) + string(os.PathListSeparator) + os.Getenv("PATH"),
	})
}

// writeIfChanged не трогает файл с тем же содержимым: иначе cargo пересобирал бы лишнее
func writeIfChanged(path, text string) error {
	if old, err := os.ReadFile(path); err == nil && string(old) == text {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	return os.WriteFile(path, []byte(text), 0o644)
}

func (w *Workspace) writeKit(name, mainRs string) (string, error) {
	k := rustKits[name]
	dir := w.kitDir(name)
	for _, f := range [][2]string{{"Cargo.toml", k.toml}, {"Cargo.lock", k.lock}, {filepath.Join("src", "main.rs"), mainRs}} {
		if err := writeIfChanged(filepath.Join(dir, f[0]), f[1]); err != nil {
			return "", err
		}
	}
	return dir, nil
}

var errBuildTimeout = errors.New("timeout")

// cargoBuild собирает проект в dir; возвращает сообщения cargo и rustc
func (w *Workspace) cargoBuild(dir string, limit time.Duration) (string, error) {
	cmd := exec.Command(w.CargoExe(), "build", "--locked", "--quiet", "--color", "never")
	cmd.Dir = dir
	cmd.Env = w.cargoEnv(dir)
	hideWindow(cmd)
	var msg bytes.Buffer
	cmd.Stdout = &msg
	cmd.Stderr = &msg
	if err := cmd.Start(); err != nil {
		return "", err
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case err := <-done:
		return msg.String(), err
	case <-time.After(limit):
		_ = cmd.Process.Kill()
		<-done
		return msg.String(), errBuildTimeout
	}
}

var cargoNoiseRE = regexp.MustCompile("(?m)^error: could not compile `game`.*\\n?")

// cleanCargo убирает из сообщений пути папки набора и служебную строку cargo
func cleanCargo(text, dir string) string {
	text = cargoNoiseRE.ReplaceAllString(text, "")
	for _, p := range []string{dir + string(filepath.Separator), filepath.ToSlash(dir) + "/"} {
		text = strings.ReplaceAll(text, p, "")
	}
	text = strings.ReplaceAll(text, filepath.Join("src", "main.rs"), "main.rs")
	text = strings.ReplaceAll(text, "src/main.rs", "main.rs")
	return strings.TrimSpace(text)
}

// kitLocks: в одной папке набора одновременно идёт только одна сборка (прогрев или код ученика)
var kitLocks sync.Map

func kitLock(name string) *sync.Mutex {
	l, _ := kitLocks.LoadOrStore(name, &sync.Mutex{})
	return l.(*sync.Mutex)
}

var rustVersionOnlyRE = regexp.MustCompile(`^[0-9]+\.[0-9]+\.[0-9]+$`)

// installCargo ставит cargo той же версии, что и установленный rustc (манифест этой версии)
func (in *Installer) installCargo(rustVersion string) error {
	if !rustVersionOnlyRE.MatchString(rustVersion) {
		return fmt.Errorf("неизвестная версия Rust %q", rustVersion)
	}
	target, err := rustTarget()
	if err != nil {
		return err
	}
	in.setStep("Скачиваю cargo " + rustVersion)
	manifest, err := httpGet("https://static.rust-lang.org/dist/channel-rust-"+rustVersion+".toml", 8<<20)
	if err != nil {
		return err
	}
	_, urls, sums, err := rustPackages(manifest, target, []string{"cargo"})
	if err != nil {
		return err
	}
	archive, err := download(in.ws, urls[0], sums[0])
	if err != nil {
		return err
	}
	defer os.Remove(archive)
	return extract(archive, in.ws.Path("runtimes", "rust"), rustStrip)
}

// warmKit один раз собирает все крейты набора, чтобы потом собирался только код ученика
func (in *Installer) warmKit(name, rustVersion string) error {
	mu := kitLock(name)
	mu.Lock()
	defer mu.Unlock()
	dir, err := in.ws.writeKit(name, rustKits[name].warm)
	if err != nil {
		return err
	}
	_ = os.Remove(filepath.Join(dir, ".ready"))
	in.setStep("Скачиваю и собираю " + name + " — один раз, до нескольких минут")
	text, err := in.ws.cargoBuild(dir, 30*time.Minute)
	if errors.Is(err, errBuildTimeout) {
		return fmt.Errorf("сборка %s заняла больше 30 минут", name)
	}
	if err != nil {
		text = strings.TrimSpace(cleanCargo(text, dir))
		if len(text) > 1500 {
			text = "…" + text[len(text)-1500:]
		}
		return fmt.Errorf("не удалось собрать %s: %v\n%s", name, err, text)
	}
	return os.WriteFile(filepath.Join(dir, ".ready"), []byte(rustKits[name].hash()+" "+rustVersion), 0o644)
}

// buildGame собирает игру ученика с крейтами набора (или берёт готовую из кеша).
// Возвращает путь к программе, текст ошибок компиляции или ошибку окружения
func (w *Workspace) buildGame(name, code string) (exe, compileErr string, err error) {
	k := rustKits[name]
	sum := sha256.Sum256([]byte("rust-game-v1\n" + name + "\n" + k.hash() + "\n" + code))
	id := hex.EncodeToString(sum[:])[:24]
	cacheDir := w.Path("cache", "rust-game")
	if err := os.MkdirAll(cacheDir, 0o755); err != nil {
		return "", "", err
	}
	// Имя видно в диспетчере задач: game-<хеш>
	exe = filepath.Join(cacheDir, "game-"+id+exeSuffix())
	mu := kitLock(name)
	mu.Lock()
	defer mu.Unlock()
	if _, err := os.Stat(exe); err == nil {
		now := time.Now()
		_ = os.Chtimes(exe, now, now)
		return exe, "", nil
	}
	dir, err := w.writeKit(name, code)
	if err != nil {
		return "", "", err
	}
	text, err := w.cargoBuild(dir, 5*time.Minute)
	if errors.Is(err, errBuildTimeout) {
		return "", "Сборка заняла больше 5 минут", nil
	}
	if err != nil {
		clean := cleanCargo(text, dir)
		if strings.Contains(text, "could not compile `game`") {
			return "", clean, nil
		}
		// Не ошибка в коде: например, нет интернета, а крейты удалили из кеша
		if clean == "" {
			clean = err.Error()
		}
		return "", "", fmt.Errorf("сборка не удалась: %s", clean)
	}
	target, _ := rustTarget()
	built := filepath.Join(dir, "target", target, "debug", "game"+exeSuffix())
	if err := copyFile(built, exe); err != nil {
		return "", "", err
	}
	pruneRustCache(cacheDir, 10)
	return exe, "", nil
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	tmp := dst + ".tmp"
	out, err := os.OpenFile(tmp, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o755)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		os.Remove(tmp)
		return err
	}
	if err := out.Close(); err != nil {
		os.Remove(tmp)
		return err
	}
	return os.Rename(tmp, dst)
}
