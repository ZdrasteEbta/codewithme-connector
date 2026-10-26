# Коннектор CodeWithMe

**[English below](#english)**

Небольшая программа с открытым кодом, которая связывает сайт [codewithme.app](https://codewithme.app) с папкой на вашем компьютере.

- **Всё в одной папке.** При первом запуске вы выбираете папку (по умолчанию `CodeWithMe` в домашней папке). Туда и только туда коннектор ставит Python, Node.js, библиотеки и складывает ваш код.
- **Ставится только то, что вы учите.** Пока вы просто читаете уроки, ничего не скачивается. Python скачивается, когда вы впервые запускаете код на Python, библиотека numpy — когда впервые запускаете задачу курса numpy, Node.js — когда впервые запускаете JavaScript.
- **Код — обычными файлами.** Каждая задача — своя папка с решением, условием, примерами тестов и историей отправок. Открывайте папку в VS Code, PyCharm или любом редакторе: правка файла сразу появляется на сайте, правка на сайте — в файле.
- **Задачи выполняются на вашем компьютере.** Быстрее, чем в браузере, и работают библиотеки, которым нужны окна или интернет (pygame, Tkinter, requests). Проверка ответов и прогресс — как обычно, на сайте.
- **Удалить всё = удалить папку.** Коннектор не меняет PATH, реестр и системные настройки и не ставит ничего вне папки.

## Как пользоваться

1. Скачайте файл для своей системы со страницы [Releases](https://github.com/ZdrasteEbta/codewithme-connector/releases/latest):
   - Windows — `cwm-connector-windows-amd64.exe`
   - macOS (M1–M4) — `cwm-connector-macos-arm64`, macOS (Intel) — `cwm-connector-macos-amd64`
   - Linux — `cwm-connector-linux-amd64`
2. Запустите его. Windows может предупредить «Windows защитила ваш компьютер» — программа не подписана платным сертификатом; нажмите «Подробнее» → «Выполнить в любом случае». На macOS: правый клик по файлу → «Открыть».
3. Нажмите Enter, чтобы использовать папку по умолчанию, или вставьте путь к своей.
4. Откройте задачу на codewithme.app и введите код из 6 цифр, который показал коннектор. Если браузер спросит про доступ к устройствам в локальной сети — разрешите.
5. Пока окно коннектора открыто, задачи выполняются на компьютере, а решения лежат в папке. Чтобы выключить — закройте окно.

## Что лежит в папке

```
CodeWithMe/
  README.txt          что это за папка
  courses/            ваш код: courses/python/loops/b/main.py, README.md (условие),
                      tests/01.in, tests/01.out (примеры), submissions/ (история отправок)
  runtimes/python/    Python 3.12 (скачивается через uv при первом запуске Python)
  runtimes/node/      Node.js 22 (при первом запуске JavaScript)
  envs/python/        библиотеки Python, которые вы учите
  tools/uv/           uv — установщик Python от Astral
  cache/              скачанные архивы, кэши библиотек, временные файлы
  .cwm/               настройки: токены сопряжения с сайтом, список задач
```

Рядом с самой программой появляется `cwm-connector.json` с путём к выбранной папке. Если положить программу прямо в папку CodeWithMe, этого файла не будет.

## Как удалить

Закройте окно коннектора и удалите папку `CodeWithMe` (и сам файл программы). Больше нигде ничего не остаётся.

## Безопасность

- Коннектор слушает только `127.0.0.1` (порты 47615–47619) — с других компьютеров к нему не подключиться.
- Запросы принимаются только со страниц `https://codewithme.app` и только по адресу 127.0.0.1/localhost (защита от DNS rebinding).
- Выполнять код, ставить библиотеки и работать с файлами можно только после сопряжения: коннектор показывает код из 6 цифр, вы вводите его на сайте. После 5 неверных кодов сопряжение блокируется до перезапуска.
- Сайт может передать только программу, входные данные и имена библиотек из PyPI. Файлы пишутся только внутри `courses/` выбранной папки.
- Python, uv и Node.js скачиваются только с официальных адресов (github.com/astral-sh/uv, python-build-standalone через uv, nodejs.org), контрольные суммы SHA-256 проверяются.
- Коннектор — не песочница: программа ученика работает с вашими правами, как если бы вы запустили её сами. Держите коннектор включённым, только пока занимаетесь.

Нашли уязвимость — напишите по адресу из [SECURITY.md](SECURITY.md).

## Сборка самостоятельно

Нужен Go 1.22+. Сторонних зависимостей нет.

```
go build -o cwm-connector .
./cwm-connector --folder ./CodeWithMe
```

`--dev` дополнительно разрешает запросы с `http://localhost:3000` (локальная разработка сайта).

Проверка контрольной суммы скачанного файла: сравните вывод `certutil -hashfile cwm-connector-windows-amd64.exe SHA256` (Windows) или `shasum -a 256 <файл>` (macOS/Linux) с файлом `SHA256SUMS.txt` в релизе.

Лицензия — MIT.

---

## English

A small open-source program that links [codewithme.app](https://codewithme.app) to a folder on your computer.

- **Everything in one folder.** On first start you pick a folder (default: `CodeWithMe` in your home directory). Python, Node.js, libraries and your code go there and nowhere else.
- **Only what you learn gets installed.** Nothing is downloaded while you just read lessons. Python is fetched the first time you run Python code, numpy the first time you run a numpy task, Node.js the first time you run JavaScript.
- **Your code as plain files.** Each task gets a folder with your solution, the statement, sample tests and submission history. Open it in VS Code or any editor: file edits show up on the site and vice versa.
- **Tasks run on your computer.** Checking answers and progress stay on the site.
- **Delete the folder to remove everything.** The connector never touches PATH, the registry or system settings.

Usage: download the file for your OS from [Releases](https://github.com/ZdrasteEbta/codewithme-connector/releases/latest), run it, press Enter to accept the default folder, then enter the 6-digit code it shows on a codewithme.app task page.

Security: listens on `127.0.0.1` only, accepts requests only from `https://codewithme.app` pages, requires pairing with a one-time 6-digit code, downloads runtimes only from official sources with SHA-256 verification. It is not a sandbox: your programs run with your permissions.

Build: `go build -o cwm-connector .` (Go 1.22+, no dependencies). License: MIT.
