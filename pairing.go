package main

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"strings"
	"sync"
	"time"
)

const (
	pairAttempts = 5
	pairTTL      = 10 * time.Minute
)

// Pairing — код сопряжения из 6 цифр и выданные сайту токены.
// Токены сохраняются в папке (.cwm/tokens.json), чтобы после перезапуска коннектора
// не вводить код заново.
type Pairing struct {
	mu        sync.Mutex
	code      string
	codeUntil time.Time
	attempts  int
	locked    bool
	tokens    []string
	file      string
}

func NewPairing(file string) *Pairing {
	p := &Pairing{file: file}
	if data, err := os.ReadFile(file); err == nil {
		_ = json.Unmarshal(data, &p.tokens)
	}
	p.newCode()
	return p
}

func randomDigits(n int) string {
	var b strings.Builder
	for i := 0; i < n; i++ {
		d, err := rand.Int(rand.Reader, big.NewInt(10))
		if err != nil {
			panic(err)
		}
		b.WriteByte(byte('0' + d.Int64()))
	}
	return b.String()
}

func (p *Pairing) newCode() {
	p.code = randomDigits(6)
	p.codeUntil = time.Now().Add(pairTTL)
	p.attempts = 0
	fmt.Println()
	fmt.Printf("  Код для сайта CodeWithMe:  %s %s\n", p.code[:3], p.code[3:])
	fmt.Println("  Введите его на странице урока. Код действует 10 минут.")
	fmt.Println()
}

// Pair возвращает токен или причину отказа: wrong, expired, locked
func (p *Pairing) Pair(code string) (string, string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.locked {
		return "", "locked"
	}
	if time.Now().After(p.codeUntil) {
		p.newCode()
		return "", "expired"
	}
	code = strings.ReplaceAll(code, " ", "")
	if subtle.ConstantTimeCompare([]byte(code), []byte(p.code)) != 1 {
		p.attempts++
		if p.attempts >= pairAttempts {
			p.locked = true
			logf("Слишком много неверных кодов. Сопряжение заблокировано — перезапустите коннектор.")
			return "", "locked"
		}
		return "", "wrong"
	}
	buf := make([]byte, 32)
	if _, err := rand.Read(buf); err != nil {
		panic(err)
	}
	token := base64.RawURLEncoding.EncodeToString(buf)
	p.tokens = append(p.tokens, token)
	if len(p.tokens) > 10 {
		p.tokens = p.tokens[len(p.tokens)-10:]
	}
	data, _ := json.Marshal(p.tokens)
	_ = writeFileAtomic(p.file, data)
	logf("Сайт подключён.")
	p.newCode() // код одноразовый
	return token, ""
}

func (p *Pairing) Valid(token string) bool {
	if token == "" {
		return false
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	ok := false
	for _, t := range p.tokens {
		if subtle.ConstantTimeCompare([]byte(token), []byte(t)) == 1 {
			ok = true
		}
	}
	return ok
}

func logf(format string, args ...any) {
	fmt.Printf("%s %s\n", time.Now().Format("15:04:05"), fmt.Sprintf(format, args...))
}
