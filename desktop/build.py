"""Собирает приложение. Помощник на Go должен лежать рядом: ../codewithme-helper[.exe].

Windows: PyInstaller собирает папку, а запускалка на Go (../launcher) прячет её в один .exe и
распаковывает при первом запуске версии в %USERPROFILE%/.codewithme — так окно открывается за секунду, а не после распаковки каждый раз.
Нужен go (переменная GO или go в PATH). macOS: папка .app. Linux: один файл."""
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import PyInstaller.__main__

here = Path(__file__).resolve().parent
helper = here.parent / ("codewithme-helper.exe" if os.name == "nt" else "codewithme-helper")
if not helper.exists():
    sys.exit(f"Нет файла {helper}: сначала соберите его через go build")

sep = os.pathsep
unused = [
    "PyQt6.QtBluetooth", "PyQt6.QtDBus", "PyQt6.QtDesigner", "PyQt6.QtHelp", "PyQt6.QtMultimedia",
    "PyQt6.QtMultimediaWidgets", "PyQt6.QtNfc", "PyQt6.QtOpenGL", "PyQt6.QtOpenGLWidgets", "PyQt6.QtPdf",
    "PyQt6.QtPdfWidgets", "PyQt6.QtPositioning", "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtQuick3D",
    "PyQt6.QtQuickWidgets", "PyQt6.QtRemoteObjects", "PyQt6.QtSensors", "PyQt6.QtSerialPort", "PyQt6.QtSql",
    "PyQt6.QtSvgWidgets", "PyQt6.QtTest", "PyQt6.QtWebChannel", "PyQt6.QtWebSockets", "PyQt6.QtXml",
    "tkinter", "PIL",  # unittest нужен pyflakes, pydoc нужен jedi
]
args = [
    str(here / "main.py"),
    "--name", "CodeWithMe-IDE",
    "--noconfirm", "--clean", "--windowed",
    "--onedir" if sys.platform in ("darwin", "win32") else "--onefile",  # на macOS приложением считается папка .app
    # На Windows папка приложения — только заготовка для запускалки: кладём её в build, в dist будет один .exe
    "--distpath", str(here / ("build/app" if sys.platform == "win32" else "dist")),
    "--workpath", str(here / "build"),
    "--specpath", str(here / "build"),
    "--paths", str(here),
    "--icon", str(here / "icon.ico"),
    "--add-binary", f"{helper}{sep}.",
    "--add-data", f"{here / 'icon.png'}{sep}.",
    "--add-data", f"{here / 'fonts'}{sep}fonts",
    # jedi запускает в окружении ученика свой файл, а подсказки берёт из .pyi: нужны исходники и данные
    "--collect-all", "jedi",
    "--collect-all", "parso",
    "--hidden-import", "pyflakes.checker",
    "--copy-metadata", "pyflakes",  # в метаданных лежит текст лицензии
]
for name in unused:
    args += ["--exclude-module", name]
PyInstaller.__main__.run(args)

if sys.platform == "win32":
    root = here.parent
    version = os.environ.get("VERSION") or re.search(r'var version = "([^"]+)"', (root / "main.go").read_text("utf-8")).group(1)
    folder = here / "build" / "app" / "CodeWithMe-IDE"
    archive = root / "launcher" / "app.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(folder).as_posix())
    go = os.environ.get("GO") or shutil.which("go")
    if not go:
        sys.exit("Нет go: укажите путь в переменной GO")
    (here / "dist").mkdir(exist_ok=True)
    out = here / "dist" / "CodeWithMe-IDE.exe"
    env = {**os.environ, "CGO_ENABLED": "0", "GOOS": "windows", "GOARCH": "amd64"}
    subprocess.run([go, "build", "-trimpath", "-ldflags", f"-s -w -H windowsgui -X main.version={version}", "-o", str(out), "."],
                   cwd=root / "launcher", env=env, check=True)
    archive.unlink()
    # Go не умеет вшивать иконку: ставим её тем же способом, что PyInstaller ставит своему .exe
    from PyInstaller.utils.win32.icon import CopyIcons
    CopyIcons(str(out), str(here / "icon.ico"))
    print(f"Built {out} (version {version})")  # латиницей: консоль Windows в CI не печатает кириллицу
