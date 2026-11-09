"""Собирает приложение одним файлом. Помощник на Go должен лежать рядом: ../codewithme-helper[.exe]."""
import os
import sys
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
    "tkinter", "unittest", "pydoc", "PIL",
]
args = [
    str(here / "main.py"),
    "--name", "CodeWithMe-IDE",
    "--noconfirm", "--clean", "--windowed",
    "--onedir" if sys.platform == "darwin" else "--onefile",  # на macOS приложением считается папка .app
    "--distpath", str(here / "dist"),
    "--workpath", str(here / "build"),
    "--specpath", str(here / "build"),
    "--paths", str(here),
    "--icon", str(here / "icon.ico"),
    "--add-binary", f"{helper}{sep}.",
    "--add-data", f"{here / 'icon.png'}{sep}.",
    "--add-data", f"{here / 'fonts'}{sep}fonts",
]
for name in unused:
    args += ["--exclude-module", name]
PyInstaller.__main__.run(args)
