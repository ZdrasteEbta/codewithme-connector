// Коннектор CodeWithMe: связывает сайт codewithme.app с папкой на компьютере ученика.
// Python, Node.js и библиотеки ставятся в эту папку при первом запуске кода,
// задачи выполняются на компьютере, а решения лежат в файлах, которые можно открыть в любом редакторе.
package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

var version = "0.1.0" // заменяется при сборке релиза: -ldflags "-X main.version=…"

const site = "https://codewithme.app"

var devOrigins = []string{"http://localhost:3000", "http://127.0.0.1:3000"}

const configName = "cwm-connector.json"

func itoa(n int) string { return strconv.Itoa(n) }

func main() {
	dev := flag.Bool("dev", false, "разрешить также локальную разработку сайта (localhost:3000)")
	folderFlag := flag.String("folder", "", "папка CodeWithMe (по умолчанию спросить при первом запуске)")
	flag.Parse()

	fmt.Printf("Коннектор CodeWithMe %s\n", version)
	folder, err := chooseFolder(*folderFlag)
	if err != nil {
		fail("Не удалось выбрать папку: %v", err)
	}
	ws := &Workspace{Root: folder}
	if err := ws.Prepare(); err != nil {
		fail("Не удалось создать папку %s: %v", folder, err)
	}

	var ln net.Listener
	port := 0
	for p := 47615; p < 47620; p++ {
		ln, err = net.Listen("tcp", "127.0.0.1:"+itoa(p))
		if err == nil {
			port = p
			break
		}
	}
	if ln == nil {
		fail("Порты 47615–47619 заняты: возможно, коннектор или мост уже запущен в другом окне.")
	}

	origins := map[string]bool{site: true}
	if *dev {
		for _, o := range devOrigins {
			origins[o] = true
		}
	}
	srv := &Server{
		port:    port,
		origins: origins,
		ws:      ws,
		pairing: NewPairing(ws.Path(".cwm", "tokens.json")),
		runs:    NewRuns(),
		inst:    NewInstaller(ws),
		tasks:   NewTasks(ws),
	}
	fmt.Printf("Папка: %s\n", folder)
	fmt.Printf("Работает на 127.0.0.1:%d. Чтобы выключить — Ctrl+C или закройте это окно.\n", port)
	if *dev {
		fmt.Println("Режим разработки: принимаются запросы и с localhost:3000.")
	}
	server := &http.Server{Handler: srv, ReadHeaderTimeout: 10 * time.Second}
	if err := server.Serve(ln); err != nil {
		fail("%v", err)
	}
}

func fail(format string, args ...any) {
	fmt.Printf(format+"\n", args...)
	fmt.Println("Нажмите Enter, чтобы закрыть окно.")
	_, _ = bufio.NewReader(os.Stdin).ReadString('\n')
	os.Exit(1)
}

// chooseFolder: --folder; папка, в которой лежит сама программа (если это уже папка CodeWithMe);
// сохранённый выбор; иначе спросить ученика (Enter — папка по умолчанию).
func chooseFolder(flagValue string) (string, error) {
	exe, _ := os.Executable()
	exeDir := filepath.Dir(exe)
	configPath := filepath.Join(exeDir, configName)
	save := func(folder string) {
		data, _ := json.MarshalIndent(map[string]string{"folder": folder}, "", "  ")
		_ = os.WriteFile(configPath, data, 0o644)
	}
	if flagValue != "" {
		abs, err := filepath.Abs(flagValue)
		if err == nil {
			save(abs)
		}
		return abs, err
	}
	if _, err := os.Stat(filepath.Join(exeDir, ".cwm")); err == nil {
		return exeDir, nil
	}
	if data, err := os.ReadFile(configPath); err == nil {
		var cfg struct {
			Folder string `json:"folder"`
		}
		if json.Unmarshal(data, &cfg) == nil && cfg.Folder != "" {
			return cfg.Folder, nil
		}
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	def := filepath.Join(home, "CodeWithMe")
	fmt.Println()
	fmt.Println("Выберите папку для занятий. В ней будет всё: Python, библиотеки, ваш код и решения.")
	fmt.Println("Чтобы потом удалить всё, что поставил коннектор, достаточно удалить эту папку.")
	fmt.Printf("Нажмите Enter, чтобы использовать %s,\nили вставьте путь к другой папке и нажмите Enter: ", def)
	line, _ := bufio.NewReader(os.Stdin).ReadString('\n')
	line = strings.Trim(strings.TrimSpace(line), `"'`)
	folder := def
	if line != "" {
		folder, err = filepath.Abs(line)
		if err != nil {
			return "", err
		}
	}
	save(folder)
	return folder, nil
}
