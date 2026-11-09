"""Главное окно: сетка задач, редактор и результат."""
import base64
import html
import json
import re
import sys

from PyQt6.QtCore import QByteArray, QEvent, QSettings, Qt, QTimer, QUrl
from PyQt6.QtGui import QAction, QDesktopServices, QImage, QKeySequence, QShortcut, QTextDocument
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSplitter, QStackedWidget,
    QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from backend import Api, StatePoller
from editor import CodeEditor
from texts import TEXTS, system_locale
from theme import code_family, palette, stylesheet

CELL_SIZE = 26
CELL_GAP = 4
MAX_OUTPUT = 40000
PY_ERROR = re.compile(r'(File "([^"\n]*)", )(line (\d+))')
FILE_ERROR = re.compile(r'([\w./\\:-]*\.(?:rs|js|mjs)):(\d+)')
FOREIGN = ("site-packages", "lib\\python", "lib/python", "/rustc/", "node_modules", "node:", "<frozen")


def button(text="", kind=None, checkable=False):
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    b.setCheckable(checkable)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def link_errors(text: str) -> str:
    """Экранирует вывод и превращает номера строк в ссылки на редактор."""
    out = html.escape(text, quote=False)

    def py(m):
        if any(x in m.group(2) for x in FOREIGN):
            return m.group(0)
        return f'{m.group(1)}<a href="cwm:line:{m.group(4)}">{m.group(3)}</a>'

    def other(m):
        if any(x in m.group(1) for x in FOREIGN):
            return m.group(0)
        return f'<a href="cwm:line:{m.group(2)}">{m.group(0)}</a>'

    return FILE_ERROR.sub(other, PY_ERROR.sub(py, out))


class ClickLabel(QLabel):
    def __init__(self, text, on_click):
        super().__init__(text)
        self.on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.on_click()


class FindBar(QFrame):
    def __init__(self, editor: CodeEditor, window):
        super().__init__()
        self.setObjectName("findBar")
        self.editor, self.window_ = editor, window
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 5, 8, 5)
        root.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(4)
        self.find_edit = QLineEdit()
        self.case = button(kind="quiet", checkable=True)
        self.word = button(kind="quiet", checkable=True)
        self.regex = button(kind="quiet", checkable=True)
        self.prev_btn = button("↑", "quiet")
        self.next_btn = button("↓", "quiet")
        self.info = QLabel()
        self.info.setObjectName("muted")
        close = button("✕", "quiet")
        for w in (self.find_edit, self.case, self.word, self.regex, self.prev_btn, self.next_btn, self.info, close):
            top.addWidget(w)
        top.setStretch(0, 1)
        root.addLayout(top)

        self.replace_row = QWidget()
        bottom = QHBoxLayout(self.replace_row)
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(4)
        self.replace_edit = QLineEdit()
        self.one = button()
        self.all = button()
        for w in (self.replace_edit, self.one, self.all):
            bottom.addWidget(w)
        bottom.setStretch(0, 1)
        root.addWidget(self.replace_row)

        self.find_edit.textChanged.connect(lambda: self.search(live=True))
        self.find_edit.returnPressed.connect(self.next_match)
        self.replace_edit.returnPressed.connect(self.replace_one)
        self.prev_btn.clicked.connect(self.prev_match)
        self.next_btn.clicked.connect(self.next_match)
        self.one.clicked.connect(self.replace_one)
        self.all.clicked.connect(self.replace_all)
        close.clicked.connect(self.close_bar)
        for box in (self.case, self.word, self.regex):
            box.toggled.connect(lambda: self.search(live=True))
        QShortcut(QKeySequence("Escape"), self, self.close_bar, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.hide()

    def retitle(self, t):
        self.find_edit.setPlaceholderText(t["find_ph"])
        self.replace_edit.setPlaceholderText(t["replace_ph"])
        self.case.setText(t["case"])
        self.word.setText(t["word"])
        self.regex.setText(t["regex"])
        self.one.setText(t["replace_one"])
        self.all.setText(t["replace_all"])
        self.info.clear()

    def open_bar(self, replace: bool):
        self.replace_row.setVisible(replace)
        self.show()
        chosen = self.editor.selectedText()
        if chosen and "\n" not in chosen:
            self.find_edit.setText(chosen)
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def close_bar(self):
        self.hide()
        self.editor.setFocus()

    def _find(self, forward, line=-1, index=-1, wrap=True):
        return self.editor.findFirst(
            self.find_edit.text(), self.regex.isChecked(), self.case.isChecked(), self.word.isChecked(),
            wrap, forward, line, index, True, False, self.regex.isChecked(),
        )

    def _report(self, found):
        self.info.setText("" if found else self.window_.t["not_found"])

    def search(self, live=False):
        if not self.find_edit.text():
            self.info.clear()
            return False
        line, index = -1, -1
        if live:
            l1, c1, _, _ = self.editor.getSelection()
            if l1 >= 0:
                line, index = l1, c1
        found = self._find(True, line, index)
        self._report(found)
        return found

    def next_match(self):
        self._report(self._find(True) if self.find_edit.text() else False)

    def prev_match(self):
        if not self.find_edit.text():
            return
        l1, c1, _, _ = self.editor.getSelection()
        if l1 < 0:
            l1, c1 = self.editor.getCursorPosition()
        self._report(self._find(False, l1, c1))

    def replace_one(self):
        if self.editor.hasSelectedText() and not self.editor.isReadOnly() and self.editor.selectedText():
            self.search(live=True)
            self.editor.replace(self.replace_edit.text())
        self.next_match()

    def replace_all(self):
        if not self.find_edit.text():
            return
        count = 0
        self.editor.beginUndoAction()
        found = self._find(True, 0, 0, wrap=False)
        while found and count < 20000:
            if not self.editor.isReadOnly():
                self.editor.replace(self.replace_edit.text())
                count += 1
            found = self.editor.findNext()
        self.editor.endUndoAction()
        self.info.setText(self.window_.t["replaced"].format(n=count))


class MainWindow(QMainWindow):
    def __init__(self, api: Api, settings: QSettings):
        super().__init__()
        self.api, self.settings = api, settings
        self.locale = settings.value("locale", system_locale())
        if self.locale not in TEXTS:
            self.locale = "ru"
        self.theme = settings.value("theme", "dark")
        self.t = TEXTS[self.locale]
        self.site_theme = None
        self.state: dict = {}
        self.task = None
        self.key = None
        self.status = None
        self.status_sig = None
        self.grid_sig = None
        self.grid_cols = 0
        self.base = "0"
        self.dirty = False
        self.file_ready = False
        self.task_folder = None
        self.menus = {}
        self.acts = {}
        self.hotkey_rows = []
        self.active_cell = None

        self.setWindowTitle("CodeWithMe IDE")
        self.resize(1040, 700)
        self.setMinimumSize(640, 420)

        self.save_timer = QTimer(self, singleShot=True, interval=250, timeout=self.flush)
        self.watch_timer = QTimer(self, interval=1000, timeout=self.watch_file)
        self.watch_timer.start()

        self.build_ui()
        self.build_actions()
        self.set_theme(self.theme, remember=False)
        self.retitle()
        self.restore_layout()
        self.update_controls()

        self.poller = StatePoller(api, self)
        self.poller.changed.connect(self.apply_state)
        self.poller.start()

    # --- построение окна ---

    def build_ui(self):
        self.pages = QStackedWidget()
        self.setCentralWidget(self.pages)

        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setHandleWidth(1)
        self.pages.addWidget(self.split)
        self.pages.addWidget(self.build_connect())

        self.grid_area = QScrollArea()
        self.grid_area.setWidgetResizable(True)
        self.grid_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_host = QWidget()
        self.grid_host.setObjectName("gridHost")
        self.grid_layout = QVBoxLayout(self.grid_host)
        self.grid_layout.setContentsMargins(0, 0, 0, 10)
        self.grid_layout.setSpacing(4)
        self.grid_area.setWidget(self.grid_host)
        self.grid_area.setMinimumWidth(170)
        self.grid_area.viewport().installEventFilter(self)
        self.split.addWidget(self.grid_area)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        self.split.addWidget(right)
        self.split.setStretchFactor(1, 1)

        self.banner = QFrame()
        self.banner.setObjectName("banner")
        bh = QHBoxLayout(self.banner)
        bh.setContentsMargins(12, 4, 8, 4)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        self.banner_btn = button(kind="quiet")
        self.banner_btn.clicked.connect(self.open_site)
        bh.addWidget(self.banner_text, 1)
        bh.addWidget(self.banner_btn)
        rv.addWidget(self.banner)

        header = QFrame()
        header.setObjectName("header")
        hh = QHBoxLayout(header)
        hh.setContentsMargins(12, 6, 8, 6)
        hh.setSpacing(6)
        self.title = QLabel()
        self.title.setObjectName("taskTitle")
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.reset_btn = button(kind="quiet")
        self.stop_btn = button(kind="danger")
        self.run_btn = button()
        self.submit_btn = button(kind="primary")
        self.reset_btn.clicked.connect(self.reset_code)
        self.stop_btn.clicked.connect(self.stop)
        self.run_btn.clicked.connect(self.run)
        self.submit_btn.clicked.connect(self.submit)
        hh.addWidget(self.title, 1)
        for b in (self.reset_btn, self.stop_btn, self.run_btn, self.submit_btn):
            hh.addWidget(b)
        rv.addWidget(header)

        self.vsplit = QSplitter(Qt.Orientation.Vertical)
        self.vsplit.setHandleWidth(1)
        rv.addWidget(self.vsplit, 1)

        top = QWidget()
        tv = QVBoxLayout(top)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(0)
        self.editor_stack = QStackedWidget()
        self.hint = QLabel()
        self.hint.setObjectName("emptyHint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setWordWrap(True)
        self.hint.setMargin(30)
        self.editor = CodeEditor()
        self.editor_stack.addWidget(self.hint)
        self.editor_stack.addWidget(self.editor)
        self.editor.edited.connect(self.on_edited)
        self.editor.position_changed.connect(self.show_position)
        self.find_bar = FindBar(self.editor, self)
        tv.addWidget(self.editor_stack, 1)
        tv.addWidget(self.find_bar)
        self.vsplit.addWidget(top)

        self.bottom = QWidget()
        bv = QVBoxLayout(self.bottom)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(0)
        bar = QFrame()
        bar.setObjectName("outputBar")
        ob = QHBoxLayout(bar)
        ob.setContentsMargins(12, 3, 6, 3)
        self.output_title = QLabel()
        self.output_title.setObjectName("muted")
        self.busy = QLabel()
        self.busy.setObjectName("busyBar")
        self.stdin_btn = button(kind="quiet", checkable=True)
        self.stdin_btn.toggled.connect(self.toggle_stdin)
        ob.addWidget(self.output_title)
        ob.addWidget(self.busy, 1)
        ob.addWidget(self.stdin_btn)
        bv.addWidget(bar)
        self.stdin = QPlainTextEdit()
        self.stdin.setMaximumHeight(78)
        self.stdin.hide()
        bv.addWidget(self.stdin)
        self.result = QTextBrowser()
        self.result.setOpenLinks(False)
        self.result.anchorClicked.connect(self.on_link)
        bv.addWidget(self.result, 1)
        self.vsplit.addWidget(self.bottom)
        self.vsplit.setStretchFactor(0, 3)
        self.vsplit.setStretchFactor(1, 2)
        self.vsplit.setSizes([420, 220])
        self.split.setSizes([230, 810])

        self.pos_label = QLabel()
        self.saved_label = QLabel()
        self.code_label = QLabel()
        self.site_label = QLabel()
        self.statusBar().addWidget(self.pos_label)
        self.statusBar().addWidget(self.saved_label)
        self.statusBar().addPermanentWidget(self.code_label)
        self.statusBar().addPermanentWidget(self.site_label)
        self.statusBar().setSizeGripEnabled(False)

    def build_connect(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.addStretch(1)
        self.connect_title = QLabel()
        self.connect_title.setObjectName("connectTitle")
        self.connect_text = QLabel()
        self.connect_text.setObjectName("muted")
        self.connect_text.setWordWrap(True)
        self.pair_code = QLabel("—")
        self.pair_code.setObjectName("pairCode")
        self.pair_code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.connect_btn = button(kind="primary")
        self.connect_btn.clicked.connect(self.open_site)
        for w in (self.connect_title, self.connect_text, self.pair_code):
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box.addWidget(w)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.connect_btn)
        row.addStretch(1)
        box.addSpacing(10)
        box.addLayout(row)
        box.addStretch(1)
        return page

    def build_actions(self):
        e = self.editor
        spec = [
            ("file", "save", ["Ctrl+S"], self.save_now),
            ("file", "open_folder", ["Ctrl+Shift+E"], self.open_folder),
            ("file", "open_site", ["Ctrl+Shift+O"], self.open_site),
            ("file", None, None, None),
            ("file", "exit", ["Ctrl+Q"], self.close),

            ("edit", "undo", ["Ctrl+Z"], lambda: self.focused("undo")),
            ("edit", "redo", ["Ctrl+Y", "Ctrl+Shift+Z"], lambda: self.focused("redo")),
            ("edit", None, None, None),
            ("edit", "cut", ["Ctrl+X"], lambda: self.focused("cut")),
            ("edit", "copy", ["Ctrl+C"], lambda: self.focused("copy")),
            ("edit", "paste", ["Ctrl+V"], lambda: self.focused("paste")),
            ("edit", "select_all", ["Ctrl+A"], lambda: self.focused("selectAll")),
            ("edit", None, None, None),
            ("edit", "add_next", ["Ctrl+D"], e.add_next_occurrence),
            ("edit", "select_line", ["Ctrl+L"], e.select_line),
            ("edit", "comment", ["Ctrl+/"], e.toggle_comment),
            ("edit", "duplicate", ["Shift+Alt+Down"], e.duplicate_line),
            ("edit", "move_up", ["Alt+Up"], e.move_up),
            ("edit", "move_down", ["Alt+Down"], e.move_down),
            ("edit", "delete_line", ["Ctrl+Shift+K"], e.delete_line),
            ("edit", "indent", ["Ctrl+]"], e.indent_lines),
            ("edit", "outdent", ["Ctrl+["], e.outdent_lines),
            ("edit", None, None, None),
            ("edit", "find", ["Ctrl+F"], lambda: self.find_bar.open_bar(False)),
            ("edit", "replace", ["Ctrl+H"], lambda: self.find_bar.open_bar(True)),
            ("edit", "find_next", ["F3"], self.find_bar.next_match),
            ("edit", "find_prev", ["Shift+F3"], self.find_bar.prev_match),
            ("edit", "goto", ["Ctrl+G"], self.goto_line),
            ("edit", "complete", ["Ctrl+Space"], e.show_completion),

            ("run_menu", "run", ["Ctrl+Return", "F5"], self.run),
            ("run_menu", "submit", ["Ctrl+Shift+Return"], self.submit),
            ("run_menu", "stop", ["Shift+F5"], self.stop),
            ("run_menu", "next", ["Ctrl+Alt+Right"], self.next_task),
            ("run_menu", None, None, None),
            ("run_menu", "reset", [], self.reset_code),

            ("view", "toggle_grid", ["Ctrl+B"], self.toggle_grid),
            ("view", "toggle_output", ["Ctrl+J"], self.toggle_output),
            ("view", None, None, None),
            ("view", "zoom_in", ["Ctrl+=", "Ctrl++"], self.zoom_in),
            ("view", "zoom_out", ["Ctrl+-"], self.zoom_out),
            ("view", "zoom_reset", ["Ctrl+0"], self.zoom_reset),
            ("view", None, None, None),
            ("view", "theme", ["Ctrl+Shift+T"], self.toggle_theme),

            ("help", "hotkeys", ["F1"], self.show_hotkeys),
            ("help", "about", [], self.show_about),
        ]
        for name in ("file", "edit", "run_menu", "view", "help"):
            self.menus[name] = self.menuBar().addMenu("")
        for menu, name, keys, handler in spec:
            if name is None:
                self.menus[menu].addSeparator()
                continue
            act = QAction(self)
            if keys:
                act.setShortcuts([QKeySequence(k) for k in keys])
                self.hotkey_rows.append((name, keys))
            act.triggered.connect(lambda _=False, h=handler: h())
            self.menus[menu].addAction(act)
            self.acts[name] = act

    def eventFilter(self, obj, event):
        if obj is self.grid_area.viewport() and event.type() == QEvent.Type.Resize:
            if self.columns() != self.grid_cols:
                self.rebuild_grid(force=True)
        return super().eventFilter(obj, event)

    # --- язык и тема ---

    def retitle(self):
        t = self.t
        for name, menu in self.menus.items():
            menu.setTitle(t[name])
        for name, act in self.acts.items():
            act.setText(t[name])
        self.reset_btn.setText(t["reset"])
        self.stop_btn.setText(t["stop"])
        self.stdin_btn.setText(t["stdin"])
        self.stdin.setPlaceholderText(t["stdin_ph"])
        self.output_title.setText(t["output"])
        self.hint.setText(t["pick"])
        self.banner_text.setText(t["site_offline"])
        self.banner_btn.setText(t["open_site"])
        self.connect_title.setText(t["connect_title"])
        self.connect_text.setText(t["connect_text"])
        self.connect_btn.setText(t["open_site"])
        self.find_bar.retitle(t)
        self.status_sig = None
        self.grid_sig = None
        self.update_labels()
        self.show_position(*self.editor.getCursorPosition())
        self.render_status()
        self.rebuild_grid()

    def set_theme(self, name: str, remember=True):
        self.theme = "light" if name == "light" else "dark"
        c = palette(self.theme)
        QApplication.instance().setStyleSheet(stylesheet(c))
        self.editor.apply_theme(c)
        self.status_sig = None
        self.render_status()
        self.dark_title_bar()
        if remember:
            self.settings.setValue("theme", self.theme)

    def dark_title_bar(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes

            value = ctypes.c_int(0 if self.theme == "light" else 1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 20, ctypes.byref(value), ctypes.sizeof(value))
        except (OSError, AttributeError):
            pass

    def toggle_theme(self):
        self.set_theme("light" if self.theme == "dark" else "dark")

    # --- состояние от сайта ---

    def apply_state(self, data: dict):
        self.state = data
        tree = data.get("tree") or {}
        locale = tree.get("locale")
        if locale in TEXTS and locale != self.locale:
            self.locale = locale
            self.t = TEXTS[locale]
            self.settings.setValue("locale", locale)
            self.retitle()
        theme = tree.get("theme")
        if theme in ("dark", "light") and theme != self.site_theme:
            self.site_theme = theme
            if theme != self.theme:
                self.set_theme(theme)

        online = bool(data.get("siteOnline"))
        self.pages.setCurrentIndex(0 if tree or online or self.task else 1)
        self.pair_code.setText(data.get("code") or "—")

        current = data.get("current")
        if current:
            self.set_task(current)
        status = data.get("status")
        self.status = status if status and status.get("key") == self.key else None

        self.update_labels()
        self.render_status()
        self.update_controls()
        self.rebuild_grid()

    def update_labels(self):
        online = bool(self.state.get("siteOnline"))
        self.site_label.setText(self.t["online"] if online else self.t["offline"])
        code = self.state.get("code")
        self.code_label.setText(f'{self.t["code_label"]}: {code}' if code and not online else "")

    def busy_text(self):
        return (self.status or {}).get("busy") or ""

    def update_controls(self):
        online = bool(self.state.get("siteOnline"))
        self.banner.setVisible(not online)
        task, busy = self.task, bool(self.busy_text())
        ready = bool(task) and self.file_ready
        can = ready and online and not busy
        label = (task or {}).get("runLabel") or self.t["run"]
        submit = (task or {}).get("submitLabel")
        self.run_btn.setText(label)
        self.submit_btn.setText(submit or self.t["submit"])
        self.submit_btn.setVisible(bool(submit) or not task)
        self.run_btn.setEnabled(can)
        self.submit_btn.setEnabled(can)
        self.reset_btn.setEnabled(ready and not busy)
        self.stop_btn.setVisible(busy)
        self.acts["run"].setEnabled(can)
        self.acts["submit"].setEnabled(can and bool(submit))
        self.acts["stop"].setEnabled(busy)
        self.acts["reset"].setEnabled(ready and not busy)
        self.acts["next"].setEnabled(bool((self.status or {}).get("next")) and online)
        self.stdin_btn.setVisible(bool(task) and not task.get("noInput"))
        if self.stdin_btn.isHidden() and self.stdin.isVisible():
            self.stdin_btn.setChecked(False)
        self.run_btn.setToolTip("Ctrl+Enter · F5")
        self.submit_btn.setToolTip("Ctrl+Shift+Enter")
        self.stop_btn.setToolTip("Shift+F5")
        self.busy.setText(self.busy_text())

    # --- задача и файл ---

    def set_task(self, current: dict):
        key = current["key"]
        changed = key != self.key
        if changed:
            self.flush()
        self.task = current
        if changed:
            self.key = key
            self.status = None
            self.title.setText(current.get("title", ""))
            self.stdin.setPlainText(current.get("stdin") or "")
            self.load_file(fresh=True)
        else:
            self.title.setText(current.get("title", ""))
            if self.editor.locked != bool(current.get("locked")) and self.file_ready:
                self.editor.set_locked(bool(current.get("locked")))

    def load_file(self, fresh: bool):
        code, data = self.api.file(self.key)
        if code != 200:
            self.file_ready = False
            self.editor_stack.setCurrentWidget(self.hint)
            return
        self.base = data.get("version", "0")
        self.task_folder = data.get("folder")
        self.editor.set_language(self.task.get("language", "python"))
        self.editor.locked = bool(self.task.get("locked"))
        self.editor.load(data.get("content", ""), fresh)
        self.dirty = False
        self.file_ready = True
        self.editor_stack.setCurrentWidget(self.editor)
        if fresh:
            self.editor.setFocus()

    def on_edited(self):
        if self.file_ready:
            self.dirty = True
            self.saved_label.clear()
            self.save_timer.start()

    def flush(self):
        if not (self.dirty and self.key and self.file_ready):
            return True
        code, data = self.api.write(self.key, self.editor.text(), self.base)
        if code != 200:
            return False
        self.base = data.get("version", self.base)
        self.dirty = False
        self.saved_label.setText(self.t["saved"])
        return True

    def save_now(self):
        self.save_timer.stop()
        self.flush()
        self.saved_label.setText(self.t["saved"])

    def watch_file(self):
        """Файл могли изменить в другом редакторе или сайт мог только что создать его."""
        if not self.key or self.dirty:
            return
        code, data = self.api.file(self.key)
        if code != 200:
            return
        if not self.file_ready:
            self.load_file(fresh=True)
            self.update_controls()
        elif data.get("version") != self.base:
            self.base = data.get("version")
            if data.get("content") != self.editor.text():
                self.editor.load(data.get("content", ""), False)

    def show_position(self, line, col):
        self.pos_label.setText(self.t["line_col"].format(line=line + 1, col=col + 1))

    # --- команды ---

    def send(self, kind, **extra):
        if not self.key:
            return
        self.save_timer.stop()
        self.flush()
        self.api.command(kind, key=self.key, **extra)

    def run(self):
        if self.run_btn.isEnabled():
            self.show_output()
            self.send("run", stdin=self.stdin.toPlainText())

    def submit(self):
        if self.submit_btn.isEnabled() and self.submit_btn.isVisible():
            self.show_output()
            self.send("submit")

    def stop(self):
        self.send("stop")

    def next_task(self):
        if (self.status or {}).get("next"):
            self.send("next")

    def open_task(self, href: str):
        self.flush()
        self.api.command("open", href=href, locale=self.locale)

    def open_site(self):
        self.api.post("/app/open-site", {})

    def open_folder(self):
        folder = self.task_folder or self.state.get("folder")
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def reset_code(self):
        if not self.task:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(self.t["reset"])
        box.setText(self.t["reset_confirm"])
        yes = box.addButton(self.t["reset"], QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(self.t["cancel"], QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            self.editor.replace_all_text(self.task.get("starter", ""))
            self.editor.setFocus()

    def focused(self, name: str):
        widget = QApplication.focusWidget()
        method = getattr(widget, name, None)
        if method:
            method()

    def goto_line(self):
        d = QInputDialog(self)
        d.setInputMode(QInputDialog.InputMode.IntInput)
        d.setWindowTitle(self.t["goto"])
        d.setLabelText(self.t["goto_prompt"])
        d.setIntRange(1, max(1, self.editor.lines()))
        d.setIntValue(self.editor.getCursorPosition()[0] + 1)
        d.setOkButtonText(self.t["ok"])
        d.setCancelButtonText(self.t["cancel"])
        if d.exec():
            self.editor.go_to_line(d.intValue() - 1)

    def toggle_grid(self):
        self.grid_area.setVisible(not self.grid_area.isVisible())

    def toggle_output(self):
        self.bottom.setVisible(not self.bottom.isVisible())

    def show_output(self):
        if not self.bottom.isVisible():
            self.bottom.show()

    def toggle_stdin(self, on):
        self.stdin.setVisible(on)

    def zoom_in(self):
        self.editor.zoomIn(1)

    def zoom_out(self):
        self.editor.zoomOut(1)

    def zoom_reset(self):
        self.editor.set_zoom(0)

    def on_link(self, url: QUrl):
        text = url.toString()
        if text == "cwm:next":
            self.next_task()
        elif text.startswith("cwm:line:"):
            self.editor.go_to_line(int(text.rsplit(":", 1)[1]) - 1)

    # --- сетка ---

    def columns(self):
        width = self.grid_area.viewport().width() - 26
        return max(3, (width + CELL_GAP) // (CELL_SIZE + CELL_GAP))

    def rebuild_grid(self, force=False):
        tree = self.state.get("tree") or {}
        cols = self.columns()
        sig = json.dumps([tree, self.key, cols, self.theme], sort_keys=True)
        if sig == self.grid_sig and not force:
            return
        first = self.grid_sig is None or self.grid_cols == 0
        self.grid_sig, self.grid_cols = sig, cols
        scroll = self.grid_area.verticalScrollBar().value()
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.active_cell = None
        if tree:
            head = QLabel(tree.get("title", ""))
            head.setObjectName("gridTitle")
            head.setWordWrap(True)
            self.grid_layout.addWidget(head)
            progress = QLabel(f'{tree.get("done", 0)} / {tree.get("total", 0)}')
            progress.setObjectName("gridProgress")
            self.grid_layout.addWidget(progress)
            for row in tree.get("rows", []):
                self.grid_layout.addWidget(self.make_row(row, cols))
        self.grid_layout.addStretch(1)
        if first and self.active_cell is not None:
            cell = self.active_cell
            QTimer.singleShot(0, lambda: self.grid_area.ensureWidgetVisible(cell))
        else:
            QTimer.singleShot(0, lambda: self.grid_area.verticalScrollBar().setValue(scroll))

    def make_row(self, row: dict, cols: int):
        frame = QFrame()
        frame.setObjectName("row")
        frame.setProperty("state", "done" if row.get("done") else "current" if row.get("current") else "")
        box = QVBoxLayout(frame)
        box.setContentsMargins(8, 5, 8, 7)
        box.setSpacing(5)
        href = row.get("href", "")
        name = ClickLabel(row.get("title", ""), lambda h=href: self.open_task(h))
        name.setObjectName("rowHead")
        name.setWordWrap(True)
        box.addWidget(name)
        cells = row.get("cells")
        if cells:
            grid = QGridLayout()
            grid.setSpacing(CELL_GAP)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            for i, cell in enumerate(cells):
                grid.addWidget(self.make_cell(cell), i // cols, i % cols)
            box.addLayout(grid)
        elif row.get("hint"):
            hint = QLabel(row["hint"])
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            hint.setStyleSheet("font-size: 11px;")
            box.addWidget(hint)
        return frame

    def make_cell(self, cell: dict):
        b = QPushButton(str(cell.get("label", "")))
        b.setObjectName("cell")
        b.setFixedSize(CELL_SIZE, CELL_SIZE)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        active = cell.get("key") == self.key
        done = bool(cell.get("done"))
        b.setProperty("state", "doneactive" if active and done else "active" if active else "done" if done else "")
        if cell.get("title"):
            b.setToolTip(cell["title"])
        href = cell.get("href", "")
        b.clicked.connect(lambda _=False, h=href: self.open_task(h))
        if active:
            self.active_cell = b
        return b

    # --- результат ---

    def render_status(self):
        s = self.status
        sig = json.dumps([s, self.theme, self.locale], sort_keys=True)
        if sig == self.status_sig:
            return
        had_result = self.status_sig is not None
        self.status_sig = sig
        c = palette(self.theme)
        esc = lambda x: html.escape(str(x), quote=False)
        mono = f"font-family:'{code_family()}';"

        def box(label, body, color=None, bg=None):
            head = f'<div style="color:{c["dim"]};font-size:11px;">{esc(label)}</div>' if label else ""
            return (
                f'{head}<table width="100%" cellspacing="0" cellpadding="6" bgcolor="{bg or c["code"]}"><tr><td>'
                f'<pre style="{mono}color:{color or c["fg2"]};white-space:pre-wrap;margin:0;">{body}</pre></td></tr></table>'
                f'<div style="font-size:5px;">&nbsp;</div>'
            )

        doc = self.result.document()
        doc.setDefaultStyleSheet(f"a {{ color: {c['lime']}; }}")
        parts = []
        if s:
            result = s.get("result")
            if result:
                tone = {"ok": c["done"], "fail": c["rose"]}.get(result.get("tone"), c["fg"])
                xp = f' <span style="color:{c["lime"]};">{esc(result["xp"])}</span>' if result.get("xp") else ""
                parts.append(f'<div style="color:{tone};font-size:16px;font-weight:600;">{esc(result.get("title", ""))}{xp}</div>')
            if s.get("next"):
                parts.append(f'<div><a href="cwm:next" style="color:{c["lime"]};font-weight:600;">{esc(s["next"])} →</a></div>')
            tests = s.get("tests")
            if tests:
                chips = []
                for test in tests:
                    tone = {"ok": c["done"], "fail": c["rose"]}.get(test.get("tone"), c["faint"])
                    mark = test.get("verdict") or "…"
                    chips.append(f'<span style="{mono}color:{tone};">{test.get("n")}:{esc(mark)}</span>')
                parts.append("<div>" + " &nbsp; ".join(chips) + "</div>")
            for item in s.get("diff") or []:
                kind = item.get("kind")
                color = c["rose"] if kind == "got" else c["done"] if kind == "want" else None
                parts.append(box(item.get("label", ""), esc(item.get("text", "")[:MAX_OUTPUT]), color))
            if s.get("error"):
                parts.append(box(self.t["stderr"], link_errors(s["error"][:MAX_OUTPUT]), c["rose"], c["rosebg"]))
            run = s.get("run")
            if run:
                bits = [esc(x) for x in (run.get("label"), run.get("time")) if x]
                if bits:
                    tone = c["rose"] if run.get("tone") == "fail" else c["mute"]
                    parts.append(f'<div style="color:{tone};">{" · ".join(bits)}</div>')
                out = run.get("stdout") or ""
                if out:
                    parts.append(box(self.t["stdout"], link_errors(out[:MAX_OUTPUT])))
                elif not run.get("stderr"):
                    parts.append(f'<div style="color:{c["faint"]};">{esc(self.t["no_output"])}</div>')
                if run.get("stderr"):
                    parts.append(box(self.t["stderr"], link_errors(run["stderr"][:MAX_OUTPUT]), c["rose"], c["rosebg"]))
                for i, data in enumerate(run.get("images") or []):
                    image = QImage.fromData(QByteArray(base64.b64decode(data.split(",", 1)[-1])))
                    if not image.isNull():
                        name = QUrl(f"cwmimg:{i}")
                        doc.addResource(QTextDocument.ResourceType.ImageResource, name, image)
                        width = min(image.width(), 520)
                        parts.append(f'<div><img src="cwmimg:{i}" width="{width}"></div>')
            if s.get("note"):
                parts.append(f'<div style="color:{c["faint"]};font-size:11px;">{esc(s["note"])}</div>')
        if not parts:
            parts.append(f'<div style="color:{c["faint"]};">{esc(self.t["output_empty"])}</div>')
        self.result.setHtml("".join(parts))
        if had_result and s and (s.get("result") or s.get("run")):
            self.show_output()

    # --- справка ---

    def show_hotkeys(self):
        rows = [(self.t[name], " · ".join(keys)) for name, keys in self.hotkey_rows]
        rows.append((self.t["multicursor"], self.t["multicursor_keys"]))
        d = QDialog(self)
        d.setWindowTitle(self.t["hotkeys"])
        d.resize(460, 560)
        box = QVBoxLayout(d)
        box.setContentsMargins(0, 0, 0, 0)
        table = QTableWidget(len(rows), 2)
        table.setHorizontalHeaderLabels([self.t["action"], self.t["shortcut"]])
        table.verticalHeader().hide()
        table.setShowGrid(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        for i, (action, keys) in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(action))
            table.setItem(i, 1, QTableWidgetItem(keys))
        box.addWidget(table)
        d.exec()

    def show_about(self):
        box = QMessageBox(self)
        box.setWindowTitle(self.t["about"])
        box.setText(self.t["about_text"].format(version=self.state.get("version", ""), folder=self.state.get("folder", "")))
        box.addButton(self.t["ok"], QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    # --- окно ---

    def restore_layout(self):
        s = self.settings
        for key, restore in (("geometry", self.restoreGeometry), ("split", self.split.restoreState), ("vsplit", self.vsplit.restoreState)):
            value = s.value(key)
            if value is not None:
                restore(value)
        zoom = s.value("zoom")
        if zoom is not None:
            self.editor.set_zoom(int(zoom))

    def raise_window(self):
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        self.save_timer.stop()
        self.flush()
        s = self.settings
        s.setValue("geometry", self.saveGeometry())
        s.setValue("split", self.split.saveState())
        s.setValue("vsplit", self.vsplit.saveState())
        s.setValue("zoom", self.editor.get_zoom())
        event.accept()
