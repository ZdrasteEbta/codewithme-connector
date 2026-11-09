# CodeWithMe IDE

**[English below](#english)**

Маленький редактор кода с открытым исходным кодом. Условие задачи открыто на сайте [codewithme.app](https://codewithme.app), а код, запуск, отправка и результат находятся в приложении. Слева сетка тем и задач, как на сайте. Бинды смотрите по F1.

- **Всё в одной папке.** При первом запуске вы выбираете папку (по умолчанию `CodeWithMe` в домашней папке). Туда и только туда коннектор ставит Python, Node.js, Rust, библиотеки и складывает ваш код.
- **Ставится только то, что вы учите.** Пока вы просто читаете уроки, ничего не скачивается. Python скачивается, когда вы впервые запускаете код на Python, библиотека numpy — когда впервые запускаете задачу курса numpy, Node.js — когда впервые запускаете JavaScript, Rust (около 800 МБ на диске) — когда впервые запускаете задачу курса Rust, а cargo и игровой движок macroquad — когда впервые открываете курс игр на Rust.
- **Код — обычными файлами.** Каждая задача — своя папка с решением, условием, примерами тестов и историей отправок. Открывайте папку в VS Code, PyCharm или любом редакторе: правка файла сразу появляется на сайте, правка на сайте — в файле.
- **Задачи выполняются на вашем компьютере.** Быстрее, чем в браузере, и работают библиотеки, которым нужны окна или интернет (pygame, Tkinter, requests). Проверка ответов и прогресс — как обычно, на сайте.
- **Удалить всё = удалить папку.** Коннектор не меняет PATH, реестр и системные настройки и не ставит ничего вне папки.

## Как пользоваться

1. Скачайте файл для своей системы со страницы [Releases](https://github.com/ZdrasteEbta/codewithme-connector/releases/latest):
   - Windows — `CodeWithMe-IDE-windows-amd64.exe`
   - macOS (M1–M4) — `CodeWithMe-IDE-macos-arm64.zip`, macOS (Intel) — `CodeWithMe-IDE-macos-amd64.zip`
   - Linux — `CodeWithMe-IDE-linux-amd64`
2. Запустите его. Windows может предупредить «Windows защитила ваш компьютер» — программа не подписана платным сертификатом; нажмите «Подробнее» → «Выполнить в любом случае». На macOS: правый клик по приложению → «Открыть».
3. Выберите папку для занятий или оставьте предложенную.
4. Откройте codewithme.app и введите код из 6 цифр, который показало приложение. Если браузер спросит про доступ к устройствам в локальной сети — разрешите.
5. Выбирайте задачу в сетке слева: условие откроется на сайте, код — в приложении. Чтобы выключить — закройте окно.

## Что лежит в папке

```
CodeWithMe/
  README.txt          что это за папка
  courses/            ваш код: courses/python/loops/b/main.py, README.md (условие),
                      tests/01.in, tests/01.out (примеры), submissions/ (история отправок)
  runtimes/python/    Python 3.12 (скачивается через uv при первом запуске Python)
  runtimes/node/      Node.js 22 (при первом запуске JavaScript)
  runtimes/rust/      компилятор Rust (при первом запуске Rust) и cargo (для игр)
  envs/rust/          собранные крейты для игр на Rust (macroquad)
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
- Сайт может передать только программу, входные данные, имена библиотек из PyPI и npm и название набора крейтов Rust из списка, встроенного в коннектор (сейчас один — `macroquad`). Версии крейтов набора зафиксированы в коннекторе (`kits/`, Cargo.lock с контрольными суммами), сборка идёт с `--locked`: сайт не может заставить коннектор скачать другие крейты. Файлы пишутся только внутри `courses/` выбранной папки.
- Python, uv, Node.js и Rust (с cargo) скачиваются только с официальных адресов (github.com/astral-sh/uv, python-build-standalone через uv, nodejs.org, static.rust-lang.org), контрольные суммы SHA-256 проверяются. Крейты для игр — только с crates.io, их контрольные суммы проверяет cargo.
- Коннектор — не песочница: программа ученика работает с вашими правами, как если бы вы запустили её сами. Держите коннектор включённым, только пока занимаетесь.

Нашли уязвимость — напишите по адресу из [SECURITY.md](SECURITY.md).

## Сборка самостоятельно

Нужны Go 1.22+ и Python 3.12.

```
go build -o codewithme-helper .
pip install -r desktop/requirements.txt
python desktop/main.py --folder ./CodeWithMe
python desktop/build.py
```

Программа на Go запускает код и связывается с сайтом, окно написано на Python и Qt (папка `desktop/`). `--dev` дополнительно разрешает запросы с `http://localhost:3000` (локальная разработка сайта).

Проверка контрольной суммы скачанного файла: сравните вывод `certutil -hashfile CodeWithMe-IDE-windows-amd64.exe SHA256` (Windows) или `shasum -a 256 <файл>` (macOS/Linux) с файлом `SHA256SUMS.txt` в релизе.

Лицензия: программа на Go — MIT. Папка `desktop/` использует PyQt6 и QScintilla, поэтому она и собранное приложение распространяются по GPL-3.0.

---

## English

A small open-source code editor. The task statement stays on [codewithme.app](https://codewithme.app); your code, Run, Submit and the result live in the app. The left side is a grid of topics and tasks, like the website. Press F1 for the keyboard shortcuts.

- **Everything in one folder.** On first start you pick a folder (default: `CodeWithMe` in your home directory). Python, Node.js, Rust, libraries and your code go there and nowhere else.
- **Only what you learn gets installed.** Nothing is downloaded while you just read lessons. Python is fetched the first time you run Python code, numpy the first time you run a numpy task, Node.js the first time you run JavaScript, Rust (about 800 MB on disk) the first time you run a Rust task, cargo and the macroquad game engine the first time you open the Rust games course.
- **Your code as plain files.** Each task gets a folder with your solution, the statement, sample tests and submission history. Open it in VS Code or any editor: file edits show up on the site and vice versa.
- **Tasks run on your computer.** Checking answers and progress stay on the site.
- **Delete the folder to remove everything.** The connector never touches PATH, the registry or system settings.

Usage: download the file for your OS from [Releases](https://github.com/ZdrasteEbta/codewithme-connector/releases/latest), run it, choose a folder, then enter the 6-digit code it shows on codewithme.app. Pick a task in the grid: the statement opens on the website and the code opens in the app.

Security: listens on `127.0.0.1` only, accepts requests only from `https://codewithme.app` pages, requires pairing with a one-time 6-digit code, downloads runtimes only from official sources with SHA-256 verification. Rust crates come only from a built-in, version-pinned kit list (macroquad) and are built with `--locked`. It is not a sandbox: your programs run with your permissions.

Build: `go build -o codewithme-helper .`, then `pip install -r desktop/requirements.txt` and `python desktop/build.py` (Go 1.22+, Python 3.12). License: the Go program is MIT; `desktop/` uses PyQt6 and QScintilla, so it and the packaged app are GPL-3.0.
