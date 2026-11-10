// РљРѕРЅРЅРµРєС‚РѕСЂ CodeWithMe: СЃРІСЏР·С‹РІР°РµС‚ СЃР°Р№С‚ codewithme.app СЃ РїР°РїРєРѕР№ РЅР° РєРѕРјРїСЊСЋС‚РµСЂРµ СѓС‡РµРЅРёРєР°.
// Python, Node.js Рё Р±РёР±Р»РёРѕС‚РµРєРё СЃС‚Р°РІСЏС‚СЃСЏ РІ СЌС‚Сѓ РїР°РїРєСѓ РїСЂРё РїРµСЂРІРѕРј Р·Р°РїСѓСЃРєРµ РєРѕРґР°,
// Р·Р°РґР°С‡Рё РІС‹РїРѕР»РЅСЏСЋС‚СЃСЏ РЅР° РєРѕРјРїСЊСЋС‚РµСЂРµ, Р° СЂРµС€РµРЅРёСЏ Р»РµР¶Р°С‚ РІ С„Р°Р№Р»Р°С…, РєРѕС‚РѕСЂС‹Рµ РјРѕР¶РЅРѕ РѕС‚РєСЂС‹С‚СЊ РІ Р»СЋР±РѕРј СЂРµРґР°РєС‚РѕСЂРµ.
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

var version = "0.6.2" // Р·Р°РјРµРЅСЏРµС‚СЃСЏ РїСЂРё СЃР±РѕСЂРєРµ СЂРµР»РёР·Р°: -ldflags "-X main.version=вЂ¦"

const site = "https://codewithme.app"

var devOrigins = []string{"http://localhost:3000", "http://127.0.0.1:3000"}

const configName = "cwm-connector.json"

func itoa(n int) string { return strconv.Itoa(n) }

func main() {
	dev := flag.Bool("dev", false, "СЂР°Р·СЂРµС€РёС‚СЊ С‚Р°РєР¶Рµ Р»РѕРєР°Р»СЊРЅСѓСЋ СЂР°Р·СЂР°Р±РѕС‚РєСѓ СЃР°Р№С‚Р° (localhost:3000)")
	folderFlag := flag.String("folder", "", "РїР°РїРєР° CodeWithMe (РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ СЃРїСЂРѕСЃРёС‚СЊ РїСЂРё РїРµСЂРІРѕРј Р·Р°РїСѓСЃРєРµ)")
	desktop := flag.Bool("desktop", false, "СЂР°Р±РѕС‚Р°С‚СЊ РІРЅСѓС‚СЂРё РїСЂРёР»РѕР¶РµРЅРёСЏ CodeWithMe IDE Рё Р·Р°РІРµСЂС€РёС‚СЊСЃСЏ РІРјРµСЃС‚Рµ СЃ РЅРёРј")
	flag.Parse()

	fmt.Printf("CodeWithMe IDE %s\n", version)
	folder, err := chooseFolder(*folderFlag)
	if err != nil {
		fail("РќРµ СѓРґР°Р»РѕСЃСЊ РІС‹Р±СЂР°С‚СЊ РїР°РїРєСѓ: %v", err)
	}
	ws := &Workspace{Root: folder}
	if err := ws.Prepare(); err != nil {
		fail("РќРµ СѓРґР°Р»РѕСЃСЊ СЃРѕР·РґР°С‚СЊ РїР°РїРєСѓ %s: %v", folder, err)
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
		fail("РџРѕСЂС‚С‹ 47615вЂ“47619 Р·Р°РЅСЏС‚С‹: РІРѕР·РјРѕР¶РЅРѕ, РєРѕРЅРЅРµРєС‚РѕСЂ РёР»Рё РјРѕСЃС‚ СѓР¶Рµ Р·Р°РїСѓС‰РµРЅ РІ РґСЂСѓРіРѕРј РѕРєРЅРµ.")
	}

	origins := map[string]bool{site: true, "https://www.codewithme.app": true}
	if *dev {
		for _, o := range devOrigins {
			origins[o] = true
		}
	}
	srv := &Server{
		port:     port,
		origins:  origins,
		ws:       ws,
		pairing:  NewPairing(ws.Path(".cwm", "tokens.json")),
		runs:     NewRuns(),
		inst:     NewInstaller(ws),
		tasks:    NewTasks(ws),
		ide:      NewIDE(ws.Path(".cwm", "ide-tree.json")),
		siteBase: site,
	}
	if *dev {
		srv.siteBase = devOrigins[0]
	}
	fmt.Printf("РџР°РїРєР°: %s\n", folder)
	fmt.Printf("Р Р°Р±РѕС‚Р°РµС‚ РЅР° 127.0.0.1:%d. Р§С‚РѕР±С‹ РІС‹РєР»СЋС‡РёС‚СЊ вЂ” Ctrl+C РёР»Рё Р·Р°РєСЂРѕР№С‚Рµ СЌС‚Рѕ РѕРєРЅРѕ.\n", port)
	if *dev {
		fmt.Println("Р РµР¶РёРј СЂР°Р·СЂР°Р±РѕС‚РєРё: РїСЂРёРЅРёРјР°СЋС‚СЃСЏ Р·Р°РїСЂРѕСЃС‹ Рё СЃ localhost:3000.")
	}
	fmt.Printf("CWM_PORT=%d\n", port)
	if *desktop {
		go srv.watchWindow()
	}
	server := &http.Server{Handler: srv, ReadHeaderTimeout: 10 * time.Second}
	if err := server.Serve(ln); err != nil {
		fail("%v", err)
	}
}

func fail(format string, args ...any) {
	fmt.Printf(format+"\n", args...)
	fmt.Println("РќР°Р¶РјРёС‚Рµ Enter, С‡С‚РѕР±С‹ Р·Р°РєСЂС‹С‚СЊ РѕРєРЅРѕ.")
	_, _ = bufio.NewReader(os.Stdin).ReadString('\n')
	os.Exit(1)
}

// chooseFolder: --folder; РїР°РїРєР°, РІ РєРѕС‚РѕСЂРѕР№ Р»РµР¶РёС‚ СЃР°РјР° РїСЂРѕРіСЂР°РјРјР° (РµСЃР»Рё СЌС‚Рѕ СѓР¶Рµ РїР°РїРєР° CodeWithMe);
// СЃРѕС…СЂР°РЅС‘РЅРЅС‹Р№ РІС‹Р±РѕСЂ; РёРЅР°С‡Рµ СЃРїСЂРѕСЃРёС‚СЊ СѓС‡РµРЅРёРєР° (Enter вЂ” РїР°РїРєР° РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ).
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
	fmt.Println("Р’С‹Р±РµСЂРёС‚Рµ РїР°РїРєСѓ РґР»СЏ Р·Р°РЅСЏС‚РёР№. Р’ РЅРµР№ Р±СѓРґРµС‚ РІСЃС‘: Python, Р±РёР±Р»РёРѕС‚РµРєРё, РІР°С€ РєРѕРґ Рё СЂРµС€РµРЅРёСЏ.")
	fmt.Println("Р§С‚РѕР±С‹ РїРѕС‚РѕРј СѓРґР°Р»РёС‚СЊ РІСЃС‘, С‡С‚Рѕ РїРѕСЃС‚Р°РІРёР» РєРѕРЅРЅРµРєС‚РѕСЂ, РґРѕСЃС‚Р°С‚РѕС‡РЅРѕ СѓРґР°Р»РёС‚СЊ СЌС‚Сѓ РїР°РїРєСѓ.")
	fmt.Printf("РќР°Р¶РјРёС‚Рµ Enter, С‡С‚РѕР±С‹ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ %s,\nРёР»Рё РІСЃС‚Р°РІСЊС‚Рµ РїСѓС‚СЊ Рє РґСЂСѓРіРѕР№ РїР°РїРєРµ Рё РЅР°Р¶РјРёС‚Рµ Enter: ", def)
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
