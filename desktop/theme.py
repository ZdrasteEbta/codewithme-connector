"""Цвета сайта и оформление окна."""
import sys

from PyQt6.QtGui import QFontDatabase

DARK = {
    "ink": "#0e0f13", "deep": "#111318", "panel": "#14161c", "panel2": "#1a1d24", "raise": "#1d2029",
    "line": "#23262f", "line2": "#2a2e3a", "line3": "#3a3f4d",
    "fg": "#eceef3", "fg2": "#d5d9e3", "soft": "#b4bac8", "mute": "#9aa1b2", "dim": "#8a91a3", "faint": "#6b7285",
    "lime": "#c5f25c", "lime2": "#ddfb95", "limebg": "#161a12", "limeline": "#3c4a1e", "onlime": "#0e0f13",
    "rose": "#ff8a8a", "rosebg": "#1f1315", "roseline": "#5a2a30", "amberline": "#5a4a2a",
    "done": "#5fd38d", "code": "#0f1115", "card": "#121419", "select": "#2d3a18",
    "keyword": "#c5f25c", "string": "#e6c384", "number": "#f0a58f", "comment": "#6b7285", "def": "#8ec7ff", "op": "#b4bac8",
}

LIGHT = {
    "ink": "#f4f5f7", "deep": "#eceef1", "panel": "#ffffff", "panel2": "#f3f4f6", "raise": "#eaecef",
    "line": "#e3e5e9", "line2": "#d5d8de", "line3": "#b8bcc5",
    "fg": "#16181d", "fg2": "#272a31", "soft": "#434852", "mute": "#575c67", "dim": "#656a75", "faint": "#868b95",
    "lime": "#2c3038", "lime2": "#111317", "limebg": "#eceef1", "limeline": "#c4c8d0", "onlime": "#ffffff",
    "rose": "#c1343b", "rosebg": "#fdeeee", "roseline": "#efb3b6", "amberline": "#e5cd95",
    "done": "#1f9a52", "code": "#f8f9fa", "card": "#fbfbfc", "select": "#d9dde4",
    "keyword": "#6a3fb5", "string": "#a35a00", "number": "#b0352f", "comment": "#868b95", "def": "#1a62b8", "op": "#434852",
}

if sys.platform == "win32":
    UI_FONT, CODE_FONTS = "Segoe UI", ("Cascadia Mono", "Consolas")
elif sys.platform == "darwin":
    UI_FONT, CODE_FONTS = "Helvetica Neue", ("Menlo", "Monaco")
else:
    UI_FONT, CODE_FONTS = "Noto Sans", ("DejaVu Sans Mono", "Liberation Mono")


def palette(name: str) -> dict:
    return LIGHT if name == "light" else DARK


def stylesheet(c: dict) -> str:
    return f"""
* {{ font-family: "{UI_FONT}"; font-size: 13px; }}
QMainWindow, QWidget {{ background: {c['ink']}; color: {c['fg2']}; }}
QToolTip {{ background: {c['panel2']}; color: {c['fg']}; border: 1px solid {c['line2']}; padding: 3px 6px; }}
QSplitter::handle {{ background: {c['line']}; }}
QScrollArea {{ border: 0; background: {c['deep']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {c['line2']}; border-radius: 4px; min-height: 24px; min-width: 24px; margin: 1px; }}
QScrollBar::handle:hover {{ background: {c['line3']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenuBar {{ background: {c['deep']}; color: {c['mute']}; border-bottom: 1px solid {c['line']}; padding: 1px 4px; }}
QMenuBar::item {{ background: transparent; padding: 4px 9px; border-radius: 5px; }}
QMenuBar::item:selected {{ background: {c['raise']}; color: {c['fg']}; }}
QMenu {{ background: {c['panel']}; color: {c['fg2']}; border: 1px solid {c['line2']}; padding: 5px; }}
QMenu::item {{ padding: 5px 26px 5px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c['raise']}; color: {c['fg']}; }}
QMenu::item:disabled {{ color: {c['faint']}; }}
QMenu::separator {{ height: 1px; background: {c['line']}; margin: 4px 6px; }}
QStatusBar {{ background: {c['deep']}; color: {c['dim']}; border-top: 1px solid {c['line']}; }}
QStatusBar::item {{ border: 0; }}
QStatusBar QLabel {{ background: transparent; color: {c['dim']}; font-size: 12px; padding: 0 8px; }}

QPushButton {{ background: {c['panel2']}; color: {c['fg2']}; border: 1px solid {c['line2']}; border-radius: 7px; padding: 5px 12px; }}
QPushButton:hover {{ background: {c['raise']}; border-color: {c['line3']}; color: {c['fg']}; }}
QPushButton:disabled {{ color: {c['faint']}; background: {c['panel']}; border-color: {c['line']}; }}
QPushButton[kind="primary"] {{ background: {c['lime']}; color: {c['onlime']}; border-color: {c['lime']}; font-weight: 600; }}
QPushButton[kind="primary"]:hover {{ background: {c['lime2']}; border-color: {c['lime2']}; color: {c['onlime']}; }}
QPushButton[kind="primary"]:disabled {{ background: {c['panel2']}; color: {c['faint']}; border-color: {c['line']}; }}
QPushButton[kind="danger"] {{ color: {c['rose']}; border-color: {c['roseline']}; background: {c['rosebg']}; }}
QPushButton[kind="quiet"] {{ background: transparent; border-color: transparent; color: {c['mute']}; }}
QPushButton[kind="quiet"]:hover {{ background: {c['raise']}; color: {c['fg']}; }}
QPushButton[kind="quiet"]:checked {{ background: {c['raise']}; color: {c['fg']}; }}

QLineEdit, QPlainTextEdit {{ background: {c['code']}; color: {c['fg']}; border: 1px solid {c['line2']}; border-radius: 6px; padding: 4px 7px; selection-background-color: {c['select']}; selection-color: {c['fg']}; }}
QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {c['line3']}; }}
QPlainTextEdit {{ font-family: "{code_family()}"; }}
QTextBrowser {{ background: {c['card']}; color: {c['fg2']}; border: 0; padding: 8px 12px; selection-background-color: {c['select']}; selection-color: {c['fg']}; }}
QCheckBox {{ background: transparent; color: {c['mute']}; spacing: 5px; }}
QCheckBox::indicator {{ width: 13px; height: 13px; border: 1px solid {c['line3']}; border-radius: 3px; background: {c['code']}; }}
QCheckBox::indicator:checked {{ background: {c['lime']}; border-color: {c['lime']}; }}
QTableWidget {{ background: {c['panel']}; color: {c['fg2']}; border: 0; gridline-color: {c['line']}; }}
QHeaderView::section {{ background: {c['panel2']}; color: {c['mute']}; border: 0; padding: 5px 8px; }}
QDialog {{ background: {c['panel']}; }}
QDialog QLabel {{ background: transparent; }}
QInputDialog QLabel, QMessageBox QLabel {{ background: transparent; color: {c['fg2']}; }}
QLabel {{ background: transparent; }}

#gridHost {{ background: {c['deep']}; }}
#gridProgress {{ color: {c['faint']}; font-size: 12px; padding: 8px 12px 2px 12px; }}
#gridTitle {{ color: {c['fg']}; font-weight: 600; padding: 10px 12px 0 12px; }}
QFrame#row {{ background: transparent; border-radius: 8px; border: 1px solid transparent; }}
QFrame#row[state="current"] {{ background: {c['panel']}; border-color: {c['line2']}; }}
QFrame#row[state="done"] #rowHead {{ color: {c['done']}; }}
#rowHead {{ color: {c['soft']}; font-size: 12px; }}
QPushButton#cell {{ background: {c['panel2']}; border: 1px solid {c['line2']}; border-radius: 5px; padding: 0; color: {c['dim']}; font-size: 11px; font-family: "{code_family()}"; }}
QPushButton#cell:hover {{ border-color: {c['line3']}; color: {c['fg']}; }}
QPushButton#cell[state="done"] {{ background: {c['done']}; border-color: {c['done']}; color: {c['onlime'] if c is DARK else '#ffffff'}; }}
QPushButton#cell[state="active"] {{ background: {c['limebg']}; border: 2px solid {c['lime']}; color: {c['fg']}; }}
QPushButton#cell[state="doneactive"] {{ background: {c['done']}; border: 2px solid {c['fg']}; color: {c['onlime'] if c is DARK else '#ffffff'}; }}

#header {{ background: {c['panel']}; border-bottom: 1px solid {c['line']}; }}
#taskTitle {{ background: transparent; color: {c['fg']}; font-weight: 600; font-size: 14px; }}
#banner {{ background: {c['limebg']}; color: {c['soft']}; border-bottom: 1px solid {c['limeline']}; padding: 5px 12px; }}
#findBar {{ background: {c['panel']}; border-top: 1px solid {c['line']}; }}
#outputBar {{ background: {c['panel']}; border-top: 1px solid {c['line']}; border-bottom: 1px solid {c['line']}; }}
#busyBar {{ background: transparent; color: {c['mute']}; }}
#muted {{ background: transparent; color: {c['mute']}; }}
#bigCode, #pairCode {{ background: transparent; color: {c['lime']}; font-family: "{code_family()}"; font-size: 44px; font-weight: 700; }}
#connectTitle {{ background: transparent; color: {c['fg']}; font-size: 20px; font-weight: 600; }}
#emptyHint {{ background: {c['code']}; color: {c['faint']}; font-size: 14px; }}
"""


def code_family() -> str:
    """Первый установленный моноширинный шрифт: Cascadia есть не на каждой Windows 10."""
    installed = set(QFontDatabase.families())
    return next((name for name in CODE_FONTS if name in installed), CODE_FONTS[-1])
