"""Цвета и шрифты сайта, оформление окна."""
import sys
from pathlib import Path

from PyQt6.QtGui import QFontDatabase

DARK = {
    "ink": "#0e0f13", "deep": "#111318", "panel": "#14161c", "panel2": "#1a1d24", "raise": "#1d2029",
    "line": "#23262f", "line2": "#2a2e3a", "line3": "#3a3f4d",
    "fg": "#eceef3", "fg2": "#d5d9e3", "soft": "#b4bac8", "mute": "#9aa1b2", "dim": "#8a91a3", "faint": "#6b7285",
    "lime": "#c5f25c", "lime2": "#ddfb95", "limebg": "#161a12", "limeline": "#3c4a1e", "onlime": "#0e0f13", "onlimekeys": "#3a4a12",
    "rose": "#ff8a8a", "rosebg": "#1f1315", "roseline": "#5a2a30", "amberline": "#5a4a2a", "onrose": "#0e0f13",
    "done": "#5fd38d", "ondone": "#0e0f13", "wantbg": "#101a14", "wantline": "#245238",
    "code": "#0f1115", "card": "#121419", "select": "#2d3a18",
    "keyword": "#c5f25c", "string": "#e6c384", "number": "#f0a58f", "comment": "#8a91a3", "def": "#8ec7ff", "op": "#b4bac8",
}

LIGHT = {
    "ink": "#f4f5f7", "deep": "#eceef1", "panel": "#ffffff", "panel2": "#f3f4f6", "raise": "#eaecef",
    "line": "#e3e5e9", "line2": "#d5d8de", "line3": "#b8bcc5",
    "fg": "#16181d", "fg2": "#272a31", "soft": "#434852", "mute": "#575c67", "dim": "#656a75", "faint": "#868b95",
    "lime": "#2c3038", "lime2": "#111317", "limebg": "#eceef1", "limeline": "#c4c8d0", "onlime": "#ffffff", "onlimekeys": "#d5d8de",
    "rose": "#c1343b", "rosebg": "#fdeeee", "roseline": "#efb3b6", "amberline": "#e5cd95", "onrose": "#ffffff",
    "done": "#17803f", "ondone": "#ffffff", "wantbg": "#edf7f0", "wantline": "#bcdcc7",
    "code": "#f8f9fa", "card": "#ffffff", "select": "#d9dde4",
    "keyword": "#6a3fb5", "string": "#a35a00", "number": "#b0352f", "comment": "#656a75", "def": "#1a62b8", "op": "#434852",
}

if sys.platform == "win32":
    SYSTEM_UI, SYSTEM_CODE = "Segoe UI", "Consolas"
elif sys.platform == "darwin":
    SYSTEM_UI, SYSTEM_CODE = "Helvetica Neue", "Menlo"
else:
    SYSTEM_UI, SYSTEM_CODE = "Noto Sans", "DejaVu Sans Mono"

_loaded = False


def load_fonts() -> None:
    """Шрифты сайта лежат внутри приложения: ученику ничего ставить не нужно."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "fonts"
    for path in sorted(base.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))


def _family(name: str, fallback: str) -> str:
    return name if name in QFontDatabase.families() else fallback


def ui_family() -> str:
    return _family("Manrope", SYSTEM_UI)


def code_family() -> str:
    return _family("JetBrains Mono", SYSTEM_CODE)


def logo_family() -> str:
    return _family("Unbounded", ui_family())


def palette(name: str) -> dict:
    return LIGHT if name == "light" else DARK


def stylesheet(c: dict) -> str:
    ui, code, logo = ui_family(), code_family(), logo_family()
    return f"""
* {{ font-family: "{ui}"; font-size: 13px; }}
QMainWindow, QWidget {{ background: {c['ink']}; color: {c['fg2']}; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: {c['panel2']}; color: {c['fg']}; border: 1px solid {c['line2']}; padding: 3px 6px; }}
QSplitter::handle {{ background: {c['line']}; }}
QScrollArea {{ border: 0; background: {c['deep']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {c['line2']}; border-radius: 4px; min-height: 24px; min-width: 24px; margin: 1px; }}
QScrollBar::handle:hover {{ background: {c['line3']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenuBar {{ background: {c['deep']}; color: {c['mute']}; border-bottom: 1px solid {c['line']}; padding: 3px 4px; }}
QMenuBar::item {{ background: transparent; padding: 4px 9px; border-radius: 6px; }}
QMenuBar::item:selected {{ background: {c['raise']}; color: {c['fg']}; }}
QMenu {{ background: {c['panel']}; color: {c['fg2']}; border: 1px solid {c['line2']}; padding: 5px; }}
QMenu::item {{ padding: 6px 26px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {c['raise']}; color: {c['fg']}; }}
QMenu::item:disabled {{ color: {c['faint']}; }}
QMenu::separator {{ height: 1px; background: {c['line']}; margin: 4px 6px; }}
QStatusBar {{ background: {c['deep']}; color: {c['mute']}; border-top: 1px solid {c['line']}; }}
QStatusBar::item {{ border: 0; }}
QStatusBar QLabel {{ background: transparent; color: {c['mute']}; font-size: 12px; padding: 0 8px; }}
#cornerBox {{ background: transparent; }}
#wordmark {{ font-family: "{logo}"; font-size: 12px; font-weight: 700; color: {c['fg']}; }}
#siteState {{ font-size: 12px; color: {c['mute']}; }}

QPushButton {{ background: {c['raise']}; color: {c['fg']}; border: 1px solid {c['line3']}; border-radius: 8px; padding: 5px 12px; font-weight: 700; }}
QPushButton:hover {{ border-color: {c['dim']}; }}
QPushButton:disabled {{ color: {c['faint']}; background: {c['panel']}; border-color: {c['line']}; }}
QPushButton[kind="primary"] {{ background: {c['lime']}; color: {c['onlime']}; border: 0; }}
QPushButton[kind="primary"]:hover {{ background: {c['lime2']}; }}
QPushButton[kind="primary"]:disabled {{ background: {c['panel2']}; color: {c['faint']}; }}
QPushButton[kind="danger"] {{ color: {c['rose']}; border-color: {c['roseline']}; background: {c['rosebg']}; }}
QPushButton[kind="quiet"] {{ background: transparent; border: 0; color: {c['mute']}; }}
QPushButton[kind="quiet"]:hover {{ background: {c['raise']}; color: {c['fg']}; }}
QPushButton[kind="quiet"]:checked {{ background: {c['raise']}; color: {c['fg']}; }}
#btnText {{ color: {c['fg']}; font-weight: 700; }}
#btnKeys {{ color: {c['mute']}; font-family: "{code}"; font-size: 11px; }}
QPushButton[kind="primary"] #btnText {{ color: {c['onlime']}; }}
QPushButton[kind="primary"] #btnKeys {{ color: {c['onlimekeys']}; }}
QPushButton[kind="quiet"] #btnText {{ color: {c['mute']}; }}
QPushButton[kind="danger"] #btnText {{ color: {c['rose']}; }}
#btnText:disabled, #btnKeys:disabled {{ color: {c["faint"]}; }}
QPushButton#tab {{ height: 22px; padding: 3px 11px; border: 0; border-radius: 6px; background: transparent; color: {c['mute']}; font-size: 12px; }}
QPushButton#tab:hover {{ color: {c['fg']}; }}
QPushButton#tab:checked {{ background: {c['raise']}; color: {c['fg']}; }}

QLineEdit, QPlainTextEdit {{ background: {c['code']}; color: {c['fg']}; border: 1px solid {c['line2']}; border-radius: 6px; padding: 4px 7px; selection-background-color: {c['select']}; selection-color: {c['fg']}; }}
QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {c['line3']}; }}
QPlainTextEdit {{ font-family: "{code}"; }}
QTextBrowser {{ background: {c['card']}; color: {c['fg2']}; border: 0; selection-background-color: {c['select']}; selection-color: {c['fg']}; }}
QCheckBox {{ background: transparent; color: {c['mute']}; spacing: 5px; }}
QTableWidget {{ background: {c['panel']}; color: {c['fg2']}; border: 0; gridline-color: {c['line']}; }}
QHeaderView::section {{ background: {c['panel2']}; color: {c['mute']}; border: 0; padding: 5px 8px; }}
QDialog {{ background: {c['panel']}; }}

#gridHost {{ background: {c["deep"]}; }}
#gridHost QWidget {{ background: transparent; }}
#sideSection {{ color: {c['mute']}; font-size: 11px; font-weight: 700; }}
#courseTitle {{ color: {c['fg2']}; font-weight: 700; }}
#courseTitle[active="true"] {{ color: {c['fg']}; font-size: 14px; }}
#count {{ color: {c['mute']}; font-family: "{code}"; font-size: 11px; }}
#count[done="true"] {{ color: {c['done']}; }}
QProgressBar#courseBar {{ background: {c['line2']}; border: 0; border-radius: 2px; }}
QProgressBar#courseBar::chunk {{ background: {c['lime']}; border-radius: 2px; }}
QFrame#row {{ background: transparent; border-radius: 10px; border: 1px solid transparent; }}
QFrame#row[state="current"] {{ background: {c['panel']}; border-color: {c['line2']}; }}
#rowHead {{ color: {c['soft']}; }}
QFrame#row[state="current"] #rowHead {{ color: {c['fg']}; font-weight: 700; }}
QPushButton#cell {{ background: transparent; border: 1px solid {c['line3']}; border-radius: 7px; padding: 0; color: {c['soft']}; font-size: 12px; font-family: "{code}"; font-weight: 400; }}
QPushButton#cell:hover {{ border-color: {c['fg']}; color: {c['fg']}; }}
QPushButton#cell[state="done"] {{ background: {c['done']}; border: 0; color: {c['ondone']}; }}
QPushButton#cell[state="active"] {{ background: {c['limebg']}; border: 2px solid {c['lime']}; color: {c['fg']}; }}
QPushButton#cell[state="doneactive"] {{ background: {c['done']}; border: 2px solid {c['fg']}; color: {c['ondone']}; }}
#lockHint {{ color: {c['mute']}; font-size: 12px; }}

#header {{ background: {c['panel']}; border-bottom: 1px solid {c['line']}; }}
#taskPlace {{ color: {c['mute']}; font-size: 12px; }}
#taskTitle {{ color: {c['fg']}; font-weight: 700; font-size: 16px; }}
#banner {{ background: {c['limebg']}; border-bottom: 1px solid {c['limeline']}; }}
#fileBar {{ background: {c['code']}; border-bottom: 1px solid {c['line']}; }}
#fileName {{ color: {c['mute']}; font-size: 12px; font-family: "{code}"; }}
#savedState {{ color: {c['mute']}; font-size: 12px; }}
#findBar {{ background: {c['panel']}; border-top: 1px solid {c['line']}; }}
#problemRow {{ background: {c['code']}; border-top: 1px solid {c['line']}; }}
#problemRow[bad="true"] {{ background: {c['rosebg']}; border-top: 1px solid {c['roseline']}; }}
#problemText {{ color: {c['mute']}; font-size: 12px; background: transparent; }}
#problemRow[bad="true"] #problemText {{ color: {c['fg']}; }}
#depsRow {{ background: {c['limebg']}; border-top: 1px solid {c['limeline']}; }}
#depsText {{ color: {c['fg']}; font-size: 12px; background: transparent; }}
#outputBar {{ background: {c['card']}; border-top: 1px solid {c['line2']}; border-bottom: 1px solid {c['line']}; }}
#busyBar, #runTime {{ color: {c['mute']}; font-size: 12px; }}
#runTime {{ font-family: "{code}"; }}
#muted {{ color: {c['mute']}; }}
#resultPanel, #verdict, #diffHost {{ background: {c['card']}; }}
#verdictTitle {{ color: {c['fg']}; font-size: 15px; font-weight: 700; }}
#verdictTitle[tone="ok"] {{ font-size: 16px; }}
#badge {{ font-family: "{code}"; font-size: 12px; color: {c['rose']}; background: {c['rosebg']}; border: 1px solid {c['roseline']}; border-radius: 6px; padding: 3px 8px; }}
#chip {{ font-family: "{code}"; font-size: 11px; border-radius: 5px; background: {c['raise']}; color: {c['mute']}; }}
#chip[tone="ok"] {{ background: {c['done']}; color: {c['ondone']}; }}
#chip[tone="fail"] {{ background: {c['rose']}; color: {c['onrose']}; }}
#diffLabel {{ color: {c['mute']}; font-size: 12px; }}
QPlainTextEdit#diffBox {{ background: {c['code']}; border: 1px solid {c['line']}; border-radius: 8px; color: {c['fg2']}; padding: 6px 8px; }}
QPlainTextEdit#diffBox[kind="got"] {{ background: {c['rosebg']}; border-color: {c['roseline']}; color: {c['rose']}; }}
QPlainTextEdit#diffBox[kind="want"] {{ background: {c['wantbg']}; border-color: {c['wantline']}; color: {c['done']}; }}
#pairCode {{ color: {c['lime']}; font-family: "{code}"; font-size: 44px; font-weight: 700; }}
#connectTitle {{ color: {c['fg']}; font-family: "{logo}"; font-size: 22px; font-weight: 700; }}
#connectText {{ color: {c['soft']}; font-size: 14px; }}
#codeCard {{ background: {c['panel']}; border: 1px solid {c['line2']}; border-radius: 14px; }}
#emptyHint {{ background: {c['code']}; color: {c['mute']}; font-size: 14px; }}
"""
