"""Главное окно: сетка задач, редактор и результат."""
import json
import os
import sys

from PyQt6.QtCore import QSettings, Qt, QTimer, QUrl
from PyQt6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QDockWidget, QFileDialog, QMainWindow, QMessageBox, QSizePolicy, QSplitter, QStackedWidget, QTabBar, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from assist import Assistant
from backend import Api, StatePoller
from editor import CodeEditor
from icons import icon, mascot
from panels import DocTabs, KeyButton, ResultPanel, Sidebar, TabScroll, TaskTabs, button
from tests import TestRunner, TestsPanel, compare_output
from files import Explorer, language_for, read_text, run_language, same_path, write_text
from texts import TEXTS, system_locale
from theme import palette, stylesheet

LANGUAGE_NAMES = {"python": "Python", "javascript": "JavaScript", "node": "Node.js", "dom": "JavaScript", "html": "HTML", "rust": "Rust"}
DOCKS_VERSION = 4  # не повышать: так пропадает раскладка ученика; панели, которых больше нет, Qt сам пропускает


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
        self.base = "0"
        self.dirty = False
        self.file_ready = False
        self.task_folder = None
        self.menus = {}
        self.acts = {}
        self.hotkey_rows = []

        self.setWindowTitle("CodeWithMe IDE")
        self.resize(1200, 780)
        self.setMinimumSize(760, 480)

        self.save_timer = QTimer(self, singleShot=True, interval=250, timeout=self.flush)
        self.watch_timer = QTimer(self, interval=1000, timeout=self.watch_file)
        self.watch_timer.start()

        self.build_ui()
        self.build_actions()
        self.set_theme(self.theme, remember=False)
        self.retitle()
        self.restore_layout()
        self.keep_file_tab = False
        self.restore_session()
        self.update_controls()
        # Раскладку и открытые файлы сохраняем на ходу, а не только при закрытии окна:
        # так они не пропадут, если окно закрыли не крестиком (выключили компьютер и т. п.)
        self.layout_saved = None
        self.layout_timer = QTimer(self, interval=2000, timeout=self.save_layout)
        self.layout_timer.start()

        self.poller = StatePoller(api, self)
        self.poller.changed.connect(self.apply_state)
        self.poller.start()

    # --- построение окна ---

    def build_ui(self):
        self.pages = QStackedWidget()
        self.setCentralWidget(self.pages)

        main = QWidget()
        mv = QVBoxLayout(main)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(0)
        self.pages.addWidget(main)
        self.pages.addWidget(self.build_connect())

        self.banner = QFrame()
        self.banner.setObjectName("banner")
        bh = QHBoxLayout(self.banner)
        bh.setContentsMargins(18, 4, 8, 4)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        self.banner_btn = button(kind="quiet")
        self.banner_btn.clicked.connect(self.open_site)
        bh.addWidget(self.banner_text, 1)
        bh.addWidget(self.banner_btn)
        mv.addWidget(self.banner)

        header = QFrame()
        header.setObjectName("header")
        hh = QHBoxLayout(header)
        hh.setContentsMargins(18, 10, 14, 10)
        hh.setSpacing(8)
        names = QVBoxLayout()
        names.setSpacing(1)
        self.place = QLabel()
        self.place.setObjectName("taskPlace")
        self.title = QLabel()
        self.title.setObjectName("taskTitle")
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        names.addWidget(self.place)
        names.addWidget(self.title)
        self.reset_btn = KeyButton(kind="quiet")
        self.stop_btn = KeyButton(kind="danger")
        self.run_btn = KeyButton(keys="Ctrl ↵")
        self.submit_btn = KeyButton(keys="Ctrl ⇧ ↵", kind="primary")
        self.reset_btn.clicked.connect(self.reset_code)
        self.stop_btn.clicked.connect(self.stop)
        self.run_btn.clicked.connect(self.run)
        self.submit_btn.clicked.connect(self.submit)
        hh.addLayout(names, 1)
        for b in (self.reset_btn, self.stop_btn, self.run_btn, self.submit_btn):
            hh.addWidget(b)
        mv.addWidget(header)

        # Код посередине; курсы, тесты и результат — панели, которые можно перетаскивать,
        # складывать вкладками в одно место или выносить отдельным окном, как в других IDE
        self.work = QMainWindow()
        self.work.setWindowFlags(Qt.WindowType.Widget)
        self.work.setObjectName("work")
        self.work.setDockOptions(
            QMainWindow.DockOption.AnimatedDocks | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.AllowNestedDocks
        )
        self.work.setTabPosition(Qt.DockWidgetArea.AllDockWidgetAreas, QTabWidget.TabPosition.North)
        mv.addWidget(self.work, 1)
        self.sidebar = Sidebar(self.open_task, self.settings)

        middle = QWidget()
        tv = QVBoxLayout(middle)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(0)
        file_bar = QFrame()
        file_bar.setObjectName("fileBar")
        fb = QHBoxLayout(file_bar)
        fb.setContentsMargins(8, 6, 18, 0)
        fb.setSpacing(10)
        # Один ряд вкладок: задачи темы A, B, C, а за ними любые открытые файлы из проводника
        self.task_tabs = TaskTabs(self.on_task_tab)
        self.doc_tabs = DocTabs()
        self.doc_tabs.addTab("")
        self.doc_tabs.setTabData(0, None)
        self.doc_tabs.currentChanged.connect(self.on_doc_tab)
        self.file_label = QLabel()
        self.file_label.setObjectName("fileName")
        self.saved_label = QLabel()
        self.saved_label.setObjectName("savedState")
        strip = QWidget()
        strip.setObjectName("tabStrip")
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(2)
        sl.addWidget(self.task_tabs)
        sl.addWidget(self.doc_tabs)
        sl.addStretch(1)
        # вкладок много — ряд прокручивается колёсиком, а не сжимает их до обрезков
        self.tab_scroll = TabScroll(strip, self.task_tabs)
        fb.addWidget(self.tab_scroll, 1)
        fb.addWidget(self.file_label)
        fb.addWidget(self.saved_label)
        tv.addWidget(file_bar)
        self.docs = {}  # путь -> {"path", "editor", "saved"}
        self.task_path = ""
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
        self.assist = Assistant(self.api, self.editor, self)
        tv.addWidget(self.editor_stack, 1)
        tv.addWidget(self.assist.bar)
        tv.addWidget(self.find_bar)
        self.work.setCentralWidget(middle)

        self.busy = QLabel()
        self.busy.setObjectName("busyBar")
        self.run_time = QLabel()
        self.run_time.setObjectName("runTime")
        self.tests_panel = TestsPanel(self.add_test)
        self.result_panel = ResultPanel(self.next_task, self.on_link)
        self.result = self.result_panel.browser
        self.sidebar_dock = self.make_dock("sidebarDock", self.sidebar)
        self.explorer = Explorer()
        self.explorer.open_file.connect(self.open_path)
        self.explorer.changed_root.connect(lambda path: self.settings.setValue("explorer/root", path))
        self.explorer_dock = self.make_dock("explorerDock", self.explorer)
        # Справа одна панель: сверху вывод запущенного файла (только когда он нужен), под ним тесты.
        # Отдельной панели Debug больше нет
        right = QSplitter(Qt.Orientation.Vertical)
        right.setHandleWidth(1)
        right.setChildrenCollapsible(False)
        self.console = self.result_panel.console
        self.console.setParent(right)
        right.addWidget(self.console)
        right.addWidget(self.tests_panel)
        right.setSizes([260, 500])
        self.right_split = right
        self.console.hide()
        self.result_panel.log_hide.clicked.connect(self.hide_console)
        self.tests_dock = self.make_dock("testsDock", right)
        self.tests_wanted = None
        self.place_docks()

        self.test_results = {}
        self.local_busy = ""
        self.file_running = ""
        self.runner = TestRunner(self.api, self)
        self.runner.step.connect(self.on_test_step)
        self.runner.result.connect(self.on_test_result)
        self.runner.file_done.connect(self.on_file_done)
        self.runner.live.connect(self.on_file_output)
        self.result_panel.stdin.submitted.connect(self.on_file_input)
        self.result_panel.stdin.eof.connect(lambda: self.runner.send_input(eof=True))
        self.runner.finished.connect(self.on_tests_finished)

        self.pos_label = QLabel()
        self.language_label = QLabel()
        self.code_label = QLabel()
        self.keys_label = QLabel()
        self.statusBar().addWidget(self.pos_label)
        self.statusBar().addWidget(self.language_label)
        self.statusBar().addWidget(self.busy, 1)
        self.statusBar().addPermanentWidget(self.run_time)
        self.statusBar().addPermanentWidget(self.code_label)
        self.statusBar().addPermanentWidget(self.keys_label)
        self.statusBar().setSizeGripEnabled(False)

        logo = QWidget()
        logo.setObjectName("cornerBox")
        lb = QHBoxLayout(logo)
        lb.setContentsMargins(10, 0, 8, 0)
        lb.setSpacing(8)
        self.logo_picture = QLabel()
        wordmark = QLabel("CodeWithMe")
        wordmark.setObjectName("wordmark")
        lb.addWidget(self.logo_picture)
        lb.addWidget(wordmark)
        logo.setFixedHeight(28)
        self.menuBar().setCornerWidget(logo, Qt.Corner.TopLeftCorner)
        state = QWidget()
        state.setObjectName("cornerBox")
        sb = QHBoxLayout(state)
        sb.setContentsMargins(0, 0, 12, 0)
        sb.setSpacing(6)
        self.site_dot = QLabel()
        self.site_label = QLabel()
        self.site_label.setObjectName("siteState")
        sb.addWidget(self.site_dot)
        sb.addWidget(self.site_label)
        state.setFixedHeight(28)
        self.menuBar().setCornerWidget(state, Qt.Corner.TopRightCorner)

    def build_connect(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.addStretch(1)
        center = Qt.AlignmentFlag.AlignCenter
        self.connect_mascot = QLabel()
        self.connect_mascot.setAlignment(center)
        self.connect_title = QLabel()
        self.connect_title.setObjectName("connectTitle")
        self.connect_text = QLabel()
        self.connect_text.setObjectName("connectText")
        self.connect_text.setWordWrap(True)
        card = QFrame()
        card.setObjectName("codeCard")
        card.setFixedWidth(460)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(20, 20, 20, 20)
        cv.setSpacing(4)
        self.pair_code = QLabel("—")
        self.pair_code.setObjectName("pairCode")
        self.pair_code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.code_ttl = QLabel()
        self.code_ttl.setObjectName("muted")
        for w in (self.pair_code, self.code_ttl):
            w.setAlignment(center)
            cv.addWidget(w)
        self.connect_btn = KeyButton(kind="primary")
        self.connect_btn.setFixedHeight(44)
        self.connect_btn.clicked.connect(self.open_site)
        self.connect_text.setFixedWidth(460)
        for w in (self.connect_mascot, self.connect_title, self.connect_text):
            w.setAlignment(center)
        box.addWidget(self.connect_mascot, 0, center)
        box.addSpacing(14)
        box.addWidget(self.connect_title, 0, center)
        box.addSpacing(6)
        box.addWidget(self.connect_text, 0, center)
        box.addSpacing(16)
        box.addWidget(card, 0, center)
        box.addSpacing(16)
        box.addWidget(self.connect_btn, 0, center)
        box.addStretch(1)
        return page

    def build_actions(self):
        e = lambda name: lambda: getattr(self.cur(), name)()  # команды правки — для открытой вкладки
        spec = [
            ("file", "new_file", ["Ctrl+N"], self.new_file),
            ("file", "open_file", ["Ctrl+O"], self.open_file_dialog),
            ("file", "open_dir", ["Ctrl+K"], self.open_dir),
            ("file", None, None, None),
            ("file", "save", ["Ctrl+S"], self.save_now),
            ("file", "save_as", ["Ctrl+Shift+S"], self.save_as),
            ("file", "close_tab", ["Ctrl+W"], lambda: self.close_tab(self.doc_tabs.currentIndex())),
            ("file", None, None, None),
            ("file", "open_folder", [], self.open_folder),
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
            ("edit", "add_next", ["Ctrl+D"], e("add_next_occurrence")),
            ("edit", "select_line", ["Ctrl+L"], e("select_line")),
            ("edit", "comment", ["Ctrl+/"], e("toggle_comment")),
            ("edit", "duplicate", ["Shift+Alt+Down"], e("duplicate_line")),
            ("edit", "move_up", ["Alt+Up"], e("move_up")),
            ("edit", "move_down", ["Alt+Down"], e("move_down")),
            ("edit", "delete_line", ["Ctrl+Shift+K"], e("delete_line")),
            ("edit", "indent", ["Ctrl+]"], e("indent_lines")),
            ("edit", "outdent", ["Ctrl+["], e("outdent_lines")),
            ("edit", None, None, None),
            ("edit", "find", ["Ctrl+F"], lambda: self.find_bar.open_bar(False)),
            ("edit", "replace", ["Ctrl+H"], lambda: self.find_bar.open_bar(True)),
            ("edit", "find_next", ["F3"], self.find_bar.next_match),
            ("edit", "find_prev", ["Shift+F3"], self.find_bar.prev_match),
            ("edit", "goto", ["Ctrl+G"], self.goto_line),
            ("edit", "complete", ["Ctrl+Space"], e("show_completion")),

            ("run_menu", "run", ["Ctrl+Return", "F5"], self.run),
            ("run_menu", "submit", ["Ctrl+Shift+Return"], self.submit),
            ("run_menu", "stop", ["Shift+F5"], self.stop),
            ("run_menu", "next", ["Ctrl+Alt+Right"], self.next_task),
            ("run_menu", None, None, None),
            ("run_menu", "reset", [], self.reset_code),

            ("view", "reset_panels", [], self.place_docks),
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
        # Панели в «Вид»: галочка стоит, пока панель открыта
        for dock, name, keys in ((self.sidebar_dock, "toggle_grid", ["Ctrl+B"]),
                                 (self.explorer_dock, "explorer", ["Ctrl+Shift+E"]), (self.tests_dock, "toggle_tests", [])):
            act = dock.toggleViewAction()
            if keys:
                act.setShortcuts([QKeySequence(k) for k in keys])
                self.hotkey_rows.append((name, keys))
            self.menus["view"].addAction(act)
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

    # --- язык и тема ---

    def retitle(self):
        t = self.t
        for name, menu in self.menus.items():
            menu.setTitle(t[name])
        for name, act in self.acts.items():
            act.setText(t[name])
        self.reset_btn.setText(t["reset"])
        self.stop_btn.setText(t["stop"])
        self.sidebar_dock.setWindowTitle(t["toggle_grid"])
        self.tests_dock.setWindowTitle(t["tests_tab"])
        self.explorer_dock.setWindowTitle(t["explorer"])
        for dock in (self.sidebar_dock, self.explorer_dock, self.tests_dock):
            dock.titleBarWidget().setText(dock.windowTitle())
        self.explorer.set_texts(t, palette(self.theme))
        self.result_panel.set_texts(t)
        self.hint.setText(t["pick"])
        self.show_tests()
        self.banner_text.setText(t["site_offline"])
        self.banner_btn.setText(t["open_site"])
        self.connect_title.setText(t["connect_title"])
        self.connect_text.setText(t["connect_text"])
        self.connect_btn.setText(t["open_site"])
        self.code_ttl.setText(t["code_ttl"])
        self.keys_label.setText(t["f1_hint"])
        self.find_bar.retitle(t)
        self.assist.retitle(t, self.locale)
        self.status_sig = None
        self.update_labels()
        self.show_position(*self.editor.getCursorPosition())
        self.render_status()
        self.rebuild_grid()

    def set_theme(self, name: str, remember=True):
        self.theme = "light" if name == "light" else "dark"
        c = palette(self.theme)
        QApplication.instance().setStyleSheet(stylesheet(c))
        for editor in [self.editor] + [d["editor"] for d in self.docs.values()]:
            editor.apply_theme(c)
        self.explorer.set_texts(self.t, c)
        self.paint_icons(c)
        self.status_sig = None
        self.render_status()
        self.rebuild_grid()
        self.dark_title_bar()
        if remember:
            self.settings.setValue("theme", self.theme)

    def paint_icons(self, c):
        self.logo_picture.setPixmap(mascot(c["lime"], 20))
        self.connect_mascot.setPixmap(mascot(c["lime"], 84))
        self.reset_btn.set_picture(icon("reset", c["mute"], 14))
        self.run_btn.set_picture(icon("play", c["fg"], 12))
        self.update_labels()

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
        code = (data.get("code") or "—").replace(" ", "")
        self.pair_code.setText(f"{code[:3]} {code[3:]}" if len(code) == 6 else code)

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
        c = palette(self.theme)
        online = bool(self.state.get("siteOnline"))
        self.site_label.setText(self.t["online"] if online else self.t["offline"])
        self.site_dot.setPixmap(icon("dot" if online else "ring", c["done"] if online else c["mute"], 10))
        code = self.state.get("code")
        self.code_label.setText(f'{self.t["code_label"]}: {code}' if code and not online else "")
        place = ""
        for row in (self.state.get("tree") or {}).get("rows", []):
            for cell in row.get("cells") or []:
                if cell.get("key") == self.key:
                    place = self.t["topic_task"].format(topic=row.get("title", ""), letter=cell.get("label", ""))
        self.place.setText(place)
        self.place.setVisible(bool(place))

    def busy_text(self):
        return self.local_busy or (self.status or {}).get("busy") or ""

    def local_tests(self) -> bool:
        """Задачи с вводом и выводом проверяются тестами прямо в окне, без сайта."""
        task = self.task or {}
        return bool(task) and not task.get("noInput") and task.get("language", "python") in ("python", "rust")

    def update_controls(self):
        online = bool(self.state.get("siteOnline"))
        self.banner.setVisible(not online)
        task, busy = self.task, bool(self.busy_text())
        ready = bool(task) and self.file_ready
        can = ready and online and not busy
        can_run = ready and not busy and (online or self.local_tests())
        label = (task or {}).get("runLabel") or self.t["run"]
        if self.runnable_doc():  # открыт обычный файл: «Запустить» запускает его
            can_run, label = not busy, self.t["run_file"]
        submit = (task or {}).get("submitLabel")
        self.run_btn.setText(label)
        self.submit_btn.setText(submit or self.t["submit"])
        self.submit_btn.setVisible(bool(submit) or not task)
        self.run_btn.setEnabled(can_run)
        self.submit_btn.setEnabled(can)
        self.reset_btn.setEnabled(ready and not busy)
        self.stop_btn.setVisible(busy)
        self.acts["run"].setEnabled(can_run)
        self.acts["submit"].setEnabled(can and bool(submit))
        self.acts["stop"].setEnabled(busy)
        self.acts["reset"].setEnabled(ready and not busy)
        self.acts["next"].setEnabled(bool((self.status or {}).get("next")) and online)
        has_tests = self.local_tests()
        if self.tests_wanted is None or not self.task:  # при запуске оставляем панели, как их расставили
            self.tests_wanted = has_tests if self.task else None
        elif has_tests != self.tests_wanted:  # прячем тесты только при смене задачи, а не после закрытия руками
            self.tests_wanted = has_tests
            self.tests_panel.setVisible(has_tests or not self.console.isVisible())
            self.tests_dock.setVisible(has_tests or self.console.isVisible())
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
            self.test_results = {}
            self.load_file(fresh=True)
            if self.keep_file_tab:  # первая задача после запуска: остаёмся на файле, открытом в прошлый раз
                self.keep_file_tab = False
            else:
                self.doc_tabs.setCurrentIndex(self.task_tab())  # новая задача — сразу её вкладка
            self.show_tests()
            if self.local_tests():
                self.show_tests_tab()
        else:
            self.title.setText(current.get("title", ""))
            if self.editor.locked != bool(current.get("locked")) and self.file_ready:
                self.editor.set_locked(bool(current.get("locked")))

    def load_file(self, fresh: bool):
        code, data = self.api.file(self.key)
        if code != 200:
            self.file_ready = False
            self.show_task_view()
            return
        self.base = data.get("version", "0")
        self.task_folder = data.get("folder")
        name = data.get("file", "")
        self.task_path = name if os.path.isabs(name) else os.path.join(self.task_folder or "", name)
        self.file_label.setText(os.path.basename(name))
        self.doc_tabs.setTabText(self.task_tab(), os.path.basename(name))
        if not self.explorer.root:
            self.explorer.set_root(self.settings.value("explorer/root") or self.state.get("folder") or self.task_folder or "")
        self.language_label.setText(LANGUAGE_NAMES.get(self.task.get("language"), ""))
        self.editor.set_language(self.task.get("language", "python"))
        self.editor.locked = bool(self.task.get("locked"))
        self.editor.load(data.get("content", ""), fresh)
        self.dirty = False
        self.file_ready = True
        self.show_task_view()
        self.assist.task_changed(self.task.get("language", "python"), self.task_folder, self.state.get("folder"))
        if fresh and self.cur() is self.editor:
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
        doc = self.cur_doc()
        if doc:
            self.save_doc(doc)
            return
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
        if not self.run_btn.isEnabled():
            return
        doc = self.runnable_doc()
        if doc:
            self.run_file(doc)
            return
        self.show_output()
        if self.local_tests():
            self.run_tests()
        else:
            self.show_result_tab()
            self.send("run", stdin="")

    # --- тесты справа ---

    def site_tests(self) -> list:
        task = self.task or {}
        site = task.get("tests")
        if site is None and task.get("stdin"):  # сайт старой версии присылает только первый пример
            site = [{"in": task["stdin"], "out": ""}]
        return [{"in": x.get("in", ""), "out": x.get("out", "")} for x in site or []]

    def all_tests(self) -> list:
        """Тесты с сайта (с правками ученика поверх, без удалённых) и свои. src — номер в своём списке."""
        edits = self.site_edits()
        tests = []
        for i, x in enumerate(self.site_tests()):
            edit = edits.get(str(i))
            if edit and edit.get("hidden"):
                continue
            test = {"in": (edit or x).get("in", ""), "out": (edit or x).get("out", ""), "kind": "edited" if edit else "site", "src": i}
            tests.append(test)
        own = [{"in": x.get("in", ""), "out": x.get("out", ""), "kind": "own", "src": j} for j, x in enumerate(self.own_tests())]
        return tests + own

    def stored(self, name: str, empty):
        if not self.key:
            return empty
        try:
            value = json.loads(self.settings.value(f"{name}/{self.key}", json.dumps(empty)))
        except (TypeError, ValueError):
            return empty
        return value if isinstance(value, type(empty)) else empty

    def own_tests(self) -> list:
        return [x for x in self.stored("tests", []) if isinstance(x, dict)]

    def save_own_tests(self, tests: list) -> None:
        self.settings.setValue(f"tests/{self.key}", json.dumps(tests, ensure_ascii=False))

    def site_edits(self) -> dict:
        """Правки тестов с сайта: номер теста -> {'in', 'out'}."""
        return {k: v for k, v in self.stored("site-tests", {}).items() if isinstance(v, dict)}

    def save_site_edits(self, edits: dict) -> None:
        self.settings.setValue(f"site-tests/{self.key}", json.dumps(edits, ensure_ascii=False))

    def show_tests(self):
        tests = self.all_tests() if self.task else []
        hidden = sum(1 for v in self.site_edits().values() if v.get("hidden")) if self.task else 0
        self.tests_panel.show_tests(tests, self.t, palette(self.theme), self.run_one_test, self.edit_test,
                                    self.delete_test, self.reset_test, hidden, self.restore_tests)
        for index, (verdict, title, res) in self.test_results.items():
            if index < len(self.tests_panel.cards):
                self.tests_panel.cards[index].set_result(verdict, title, res)

    def add_test(self):
        if not self.task:
            return
        tests = self.own_tests()
        tests.append({"in": "", "out": ""})
        self.save_own_tests(tests)
        self.show_tests()
        self.tests_panel.focus_last_input()

    def test_at(self, index: int):
        tests = self.all_tests()
        return tests[index] if 0 <= index < len(tests) else None

    def delete_test(self, index: int):
        """Свой тест удаляется насовсем, тест с сайта прячется: его можно вернуть кнопкой внизу."""
        test = self.test_at(index)
        if not test:
            return
        if test["kind"] == "own":
            tests = self.own_tests()
            del tests[test["src"]]
            self.save_own_tests(tests)
        else:
            edits = self.site_edits()
            edits[str(test["src"])] = {"hidden": True}
            self.save_site_edits(edits)
        self.test_results = {}
        self.show_tests()

    def restore_tests(self):
        edits = {k: v for k, v in self.site_edits().items() if not v.get("hidden")}
        self.save_site_edits(edits)
        self.test_results = {}
        self.show_tests()

    def reset_test(self, index: int):
        test = self.test_at(index)
        edits = self.site_edits()
        if test and test["kind"] != "own" and edits.pop(str(test["src"]), None) is not None:
            self.save_site_edits(edits)
            self.test_results.pop(index, None)
            self.show_tests()

    def edit_test(self, index: int, field: str, text: str):
        test = self.test_at(index)
        if not test:
            return
        if test["kind"] == "own":
            tests = self.own_tests()
            tests[test["src"]][field] = text
            self.save_own_tests(tests)
            return
        i = test["src"]
        original = self.site_tests()[i]
        edits = self.site_edits()
        edit = {"in": test["in"], "out": test["out"]}
        edit[field] = text
        if edit == original:
            edits.pop(str(i), None)
        else:
            edits[str(i)] = edit
        self.save_site_edits(edits)
        if index < len(self.tests_panel.cards):
            self.tests_panel.cards[index].mark_edited(str(i) in edits)

    def run_one_test(self, index: int):
        if self.run_btn.isEnabled() and self.local_tests():
            self.run_tests(only=index)

    def run_tests(self, only=None):
        if self.runner.running:
            return
        tests = self.all_tests()
        if not tests:
            self.add_test()
            tests = self.all_tests()
        jobs = [(i, x["in"]) for i, x in enumerate(tests) if only is None or i == only]
        self.save_timer.stop()
        self.flush()
        self.show_tests_tab()
        self.run_time.clear()
        for index, _ in jobs:
            self.test_results.pop(index, None)
            if index < len(self.tests_panel.cards):
                self.tests_panel.cards[index].set_waiting()
        task = self.task or {}
        self.local_busy = self.t["running"]
        self.update_controls()
        self.runner.start(jobs, task.get("language", "python"), self.editor.text(), task.get("pip") or [],
                          int(task.get("timeLimitMs") or 2000), self.t)

    def on_test_step(self, text: str):
        if self.runner.running and text != self.local_busy and not text.startswith(self.t["test_running"].split("{")[0]):
            self.result_panel.log(text, c=palette(self.theme))
        if self.runner.running:
            self.local_busy = text
            self.busy.setText(text)

    def on_test_result(self, index: int, res: dict):
        tests = self.all_tests()
        if index >= len(tests):
            return
        task = self.task or {}
        status = res.get("status", "")
        expected = tests[index].get("out", "")
        if status == "ok":
            if expected.strip():
                ok = compare_output(res.get("stdout", ""), expected, task.get("checker") or "tokens", task.get("abs"), task.get("rel"))
                verdict, title = ("OK", self.t["test_ok"]) if ok else ("WA", self.t["test_wa"])
            else:
                verdict, title = "", ""
        else:
            verdict = {"re": "RE", "tle": "TLE", "ce": "CE", "ole": "OLE"}.get(status, "!")
            title = self.t.get(f"test_{status}", self.t["run_failed"])
        self.test_results[index] = (verdict, title, res)
        head = " · ".join(x for x in (self.t["log_test"].format(n=index + 1), title or verdict,
                                       self.t["time_ms"].format(ms=res.get("timeMs", 0)) if "timeMs" in res else "") if x)
        self.result_panel.log(head, res.get("stdout") or "", "\n".join(x for x in (res.get("stderr"), res.get("error")) if x),
                              palette(self.theme))
        if index < len(self.tests_panel.cards):
            self.tests_panel.cards[index].set_result(verdict, title, res)

    def on_tests_finished(self):
        self.local_busy = ""
        if self.runner.mode == "file":
            self.update_controls()
            return
        results = list(self.test_results.values())
        passed = sum(1 for v, _, _ in results if v == "OK")
        checked = sum(1 for v, _, _ in results if v)
        self.run_time.setText(self.t["tests_passed"].format(passed=passed, total=checked) if checked else "")
        self.update_controls()

    def submit(self):
        if self.submit_btn.isEnabled() and self.submit_btn.isVisible():
            self.show_output()
            self.show_result_tab()
            self.send("submit")

    def runnable_doc(self):
        doc = self.cur_doc() if hasattr(self, "doc_tabs") else None
        return doc if doc and run_language(doc["path"]) else None

    def run_file(self, doc):
        """Сохраняет файл и запускает его в его папке, как в обычной IDE."""
        if self.runner.running or not self.save_doc(doc):
            return
        self.show_result_tab()
        name = os.path.basename(doc["path"])
        self.show_console()
        self.file_running = name
        self.result_panel.log(self.t["log_run_file"].format(name=name), c=palette(self.theme))
        self.local_busy = self.t["running"]
        self.update_controls()
        panel = self.result_panel
        stdin = panel.stdin.toPlainText()
        if stdin and not stdin.endswith("\n"):
            stdin += "\n"
        panel.stdin.clear()
        panel.set_live(True)
        panel.write(stdin, palette(self.theme)["lime"])  # заранее написанный ввод виден в журнале, как набранный
        panel.stdin.setFocus()
        self.runner.start_file(doc["path"], run_language(doc["path"]), stdin, self.t)

    def on_file_output(self, out: str, err: str):
        c = palette(self.theme)
        self.result_panel.write(out)
        self.result_panel.write(err, c["rose"])

    def on_file_input(self, text: str):
        """Enter в строке ввода: текст уходит программе и остаётся в журнале, как в терминале."""
        if not (self.runner.running and self.runner.mode == "file"):
            return
        self.result_panel.write(text + "\n", palette(self.theme)["lime"])
        self.runner.send_input(text + "\n")

    def on_file_done(self, res: dict):
        panel = self.result_panel
        panel.set_live(False)
        if panel.stdin.hasFocus():
            self.cur().setFocus()
        status = res.get("status", "")
        title = {"ok": self.t["file_done"], "re": self.t["file_exit"], "tle": self.t["test_tle"], "ce": self.t["test_ce"],
                 "ole": self.t["test_ole"], "cancelled": self.t["file_stopped"]}.get(status, self.t["run_failed"])
        parts = [self.file_running, title]
        if "timeMs" in res and status != "ce":
            parts.append(self.t["time_ms"].format(ms=res["timeMs"]))
        error = "\n".join(x for x in (res.get("stderr"), res.get("error")) if x)
        self.result_panel.log(" · ".join(p for p in parts if p), res.get("stdout") or "", error, palette(self.theme))
        self.run_time.setText(title)

    def stop(self):
        if self.runner.running:
            self.runner.stop()
        else:
            self.send("stop")

    def next_task(self):
        if (self.status or {}).get("next"):
            self.send("next")

    def on_task_tab(self, href: str, key):
        """Вкладка задачи: показывает её код; другая задача ещё и открывается на сайте."""
        self.doc_tabs.setCurrentIndex(self.task_tab())
        if key != self.key:
            self.open_task(href)

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
        editor = self.cur()
        d.setIntRange(1, max(1, editor.lines()))
        d.setIntValue(editor.getCursorPosition()[0] + 1)
        d.setOkButtonText(self.t["ok"])
        d.setCancelButtonText(self.t["cancel"])
        if d.exec():
            editor.go_to_line(d.intValue() - 1)

    def make_dock(self, name: str, widget) -> QDockWidget:
        dock = QDockWidget(self.work)
        dock.setObjectName(name)
        dock.setWidget(widget)
        # Свой заголовок без серых кнопок «открепить» и «закрыть»: за него панель перетаскивают,
        # а открыть и закрыть её можно в меню «Вид»
        title = QLabel()
        title.setObjectName("dockTitle")
        dock.setTitleBarWidget(title)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        return dock

    def place_docks(self):
        """Расположение по умолчанию: курсы слева, справа тесты и под ними Debug."""
        work, left, right = self.work, Qt.DockWidgetArea.LeftDockWidgetArea, Qt.DockWidgetArea.RightDockWidgetArea
        for dock, area in ((self.sidebar_dock, left), (self.explorer_dock, left), (self.tests_dock, right)):
            dock.setFloating(False)
            work.addDockWidget(area, dock)
            dock.show()
        work.tabifyDockWidget(self.sidebar_dock, self.explorer_dock)
        self.sidebar_dock.raise_()
        work.resizeDocks([self.sidebar_dock, self.tests_dock], [230, 420], Qt.Orientation.Horizontal)
        self.tests_wanted = None
        if hasattr(self, "runner"):  # при первой сборке окна кнопок ещё нет
            self.update_controls()
        self.tests_dock.raise_()

    def show_output(self):
        pass  # результат отправки виден в строке под редактором

    def show_result_tab(self):
        pass

    def show_console(self):
        """Вывод программы над тестами: появляется при запуске файла или выводе с сайта."""
        self.console.show()
        self.tests_panel.setVisible(self.local_tests())
        self.tests_dock.show()
        self.tests_dock.raise_()

    def hide_console(self):
        self.console.hide()
        self.tests_panel.show()
        if not self.local_tests():
            self.tests_dock.hide()

    def show_tests_tab(self):
        self.tests_dock.show()
        self.tests_dock.raise_()

    def zoom_in(self):
        self.cur().zoomIn(1)

    def zoom_out(self):
        self.cur().zoomOut(1)

    def zoom_reset(self):
        self.cur().set_zoom(0)

    # --- файлы и вкладки, как в обычной IDE ---

    def cur(self):
        """Редактор открытой вкладки (файл задачи или любой другой файл)."""
        doc = self.cur_doc()
        return doc["editor"] if doc else self.editor

    def cur_doc(self):
        path = self.doc_tabs.tabData(self.doc_tabs.currentIndex())
        return self.docs.get(path) if path else None

    def task_tab(self) -> int:
        return next(i for i in range(self.doc_tabs.count()) if self.doc_tabs.tabData(i) is None)

    def doc_index(self, key: str) -> int:
        return next((i for i in range(self.doc_tabs.count()) if self.doc_tabs.tabData(i) == key), -1)

    def show_task_view(self):
        if self.cur_doc() is None:
            self.editor_stack.setCurrentWidget(self.editor if self.file_ready else self.hint)

    def doc_key(self, path: str) -> str:
        return os.path.normcase(os.path.abspath(path))

    def open_path(self, path: str):
        if same_path(path, self.task_path):
            self.doc_tabs.setCurrentIndex(self.task_tab())
            return
        key = self.doc_key(path)
        if key in self.docs:
            self.select_doc(key)
            return
        text, error = read_text(path)
        if text is None:
            message = {"big": self.t["file_big"], "binary": self.t["file_binary"]}.get(error, error)
            QMessageBox.warning(self, self.t["cannot_open"], f"{os.path.basename(path)}\n\n{message}")
            return
        editor = CodeEditor()
        editor.apply_theme(palette(self.theme))
        editor.set_language(language_for(path))
        editor.load(text, True)
        editor.set_zoom(self.editor.get_zoom())
        doc = {"path": path, "editor": editor, "saved": text}
        editor.edited.connect(lambda: self.mark_doc(doc))
        editor.position_changed.connect(self.show_position)
        self.docs[key] = doc
        self.editor_stack.addWidget(editor)
        i = self.doc_tabs.addTab(os.path.basename(path))
        self.doc_tabs.setTabData(i, key)
        self.doc_tabs.setTabToolTip(i, path)
        close = button(kind="tabClose")
        close.setIcon(QIcon(icon("close", palette(self.theme)["mute"], 10)))
        close.setFixedSize(18, 18)
        close.setToolTip(self.t["close_tab"])
        close.clicked.connect(lambda _=False, k=key: self.close_tab(self.doc_index(k)))
        self.doc_tabs.setTabButton(i, QTabBar.ButtonPosition.RightSide, close)
        self.doc_tabs.setCurrentIndex(i)
        editor.setFocus()

    def select_doc(self, key: str):
        if self.doc_index(key) >= 0:
            self.doc_tabs.setCurrentIndex(self.doc_index(key))

    def mark_doc(self, doc):
        dirty = doc["editor"].text() != doc["saved"]
        key = self.doc_key(doc["path"])
        for i in range(self.doc_tabs.count()):
            if self.doc_tabs.tabData(i) == key:
                self.doc_tabs.setTabText(i, ("● " if dirty else "") + os.path.basename(doc["path"]))

    def on_doc_tab(self, index: int):
        doc = self.cur_doc()
        editor = doc["editor"] if doc else None
        if editor:
            self.editor_stack.setCurrentWidget(editor)
            self.language_label.setText({"text": ""}.get(editor.language, LANGUAGE_NAMES.get(editor.language, "")))
        else:
            self.show_task_view()
            self.language_label.setText(LANGUAGE_NAMES.get((self.task or {}).get("language"), ""))
        self.task_tabs.set_active(doc is None)
        self.file_label.setVisible(doc is None)  # имя файла задачи — только когда открыта задача
        QTimer.singleShot(0, self.tab_scroll.show_active)
        self.find_bar.editor = self.cur()
        line, col = self.cur().getCursorPosition()
        self.show_position(line, col)
        self.update_controls()

    def save_doc(self, doc) -> bool:
        text = doc["editor"].text()
        error = write_text(doc["path"], text)
        if error:
            QMessageBox.warning(self, self.t["cannot_save"], f"{doc['path']}\n\n{error}")
            return False
        doc["saved"] = text
        self.mark_doc(doc)
        return True

    def ask_save(self, names: list):
        """True — сохранить, False — не сохранять, None — отмена."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(self.t["save"])
        text = self.t["unsaved_text"].format(name=names[0]) if len(names) == 1 else self.t["unsaved_many"].format(names=", ".join(names))
        box.setText(text)
        save = box.addButton(self.t["save"], QMessageBox.ButtonRole.AcceptRole)
        skip = box.addButton(self.t["dont_save"], QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(self.t["cancel"], QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return True if box.clickedButton() is save else False if box.clickedButton() is skip else None

    def close_tab(self, index: int):
        key = self.doc_tabs.tabData(index)
        doc = self.docs.get(key) if key else None
        if not doc:
            return
        if doc["editor"].text() != doc["saved"]:
            answer = self.ask_save([os.path.basename(doc["path"])])
            if answer is None or (answer and not self.save_doc(doc)):
                return
        self.doc_tabs.removeTab(index)
        self.editor_stack.removeWidget(doc["editor"])
        doc["editor"].deleteLater()
        del self.docs[key]
        self.on_doc_tab(self.doc_tabs.currentIndex())

    def start_dir(self) -> str:
        return self.explorer.root or self.task_folder or os.path.expanduser("~")

    def open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, self.t["open_file"], self.start_dir())
        if path:
            self.open_path(path)

    def open_dir(self):
        self.explorer.choose_root()
        self.explorer_dock.show()
        self.explorer_dock.raise_()

    def new_file(self):
        path, _ = QFileDialog.getSaveFileName(self, self.t["new_file"], self.start_dir())
        if not path:
            return
        if not os.path.exists(path):
            error = write_text(path, "")
            if error:
                QMessageBox.warning(self, self.t["cannot_save"], f"{path}\n\n{error}")
                return
        self.open_path(path)

    def save_as(self):
        start = self.cur_doc()["path"] if self.cur_doc() else os.path.join(self.start_dir(), self.file_label.text())
        path, _ = QFileDialog.getSaveFileName(self, self.t["save_as"], start)
        if not path:
            return
        error = write_text(path, self.cur().text())
        if error:
            QMessageBox.warning(self, self.t["cannot_save"], f"{path}\n\n{error}")
            return
        doc = self.cur_doc()
        if doc and same_path(path, doc["path"]):
            doc["saved"] = doc["editor"].text()
            self.mark_doc(doc)
            return
        self.open_path(path)

    def unsaved_docs(self) -> list:
        return [d for d in self.docs.values() if d["editor"].text() != d["saved"]]

    def on_link(self, url: QUrl):
        text = url.toString()
        if text == "cwm:next":
            self.next_task()
        elif text.startswith("cwm:line:"):
            self.editor.go_to_line(int(text.rsplit(":", 1)[1]) - 1)

    # --- сетка и результат ---

    def rebuild_grid(self):
        tree = self.state.get("tree") or {}
        self.sidebar.show_tree(tree, self.key, self.t, palette(self.theme))
        self.task_tabs.show_row(tree, self.key, palette(self.theme), self.t)

    def render_status(self):
        s = self.status
        sig = json.dumps([s, self.theme, self.locale], sort_keys=True)
        if sig == self.status_sig:
            return
        had_result = self.status_sig is not None
        self.status_sig = sig
        self.run_time.setText(self.result_panel.show_status(s, self.t, palette(self.theme)))
        run = (s or {}).get("run")
        if run and not (s or {}).get("busy"):
            title = " · ".join(x for x in (self.t["log_site_run"], run.get("label"), run.get("time")) if x)
            self.result_panel.log(title, run.get("stdout") or "", run.get("stderr") or "", palette(self.theme))
        elif (s or {}).get("error"):
            self.result_panel.log((s.get("result") or {}).get("title") or self.t["stderr"], "", s["error"], palette(self.theme))
        if had_result and s and (s.get("run") or s.get("error")) and not s.get("busy"):
            self.show_console()

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
        value = s.value("geometry")
        if value is not None:
            self.restoreGeometry(value)
        value = s.value("docks")
        if value is not None:
            self.work.restoreState(value, DOCKS_VERSION)
        zoom = s.value("zoom")
        if zoom is not None:
            self.editor.set_zoom(int(zoom))
        value = s.value("right_split")
        if value is not None:
            self.right_split.restoreState(value)

    def save_layout(self):
        """Положение окна, панелей, размеры и открытые файлы; пишет только когда что-то изменилось."""
        s = self.settings
        layout = (bytes(self.saveGeometry()), bytes(self.work.saveState(DOCKS_VERSION)),
                  bytes(self.right_split.saveState()), self.editor.get_zoom(), json.dumps(self.session()))
        if layout == self.layout_saved:
            return
        self.layout_saved = layout
        s.setValue("geometry", self.saveGeometry())
        s.setValue("docks", self.work.saveState(DOCKS_VERSION))
        s.setValue("right_split", self.right_split.saveState())
        s.setValue("zoom", self.editor.get_zoom())
        s.setValue("session", json.dumps(self.session(), ensure_ascii=False))

    def session(self) -> dict:
        files = [self.docs[k]["path"] for k in (self.doc_tabs.tabData(i) for i in range(self.doc_tabs.count()))
                 if k and k in self.docs]
        doc = self.cur_doc()
        return {"files": files, "current": doc["path"] if doc else ""}

    def restore_session(self):
        """Снова открывает файлы, которые были открыты в прошлый раз (кроме удалённых)."""
        try:
            data = json.loads(self.settings.value("session") or "{}")
        except ValueError:
            return
        for path in data.get("files") or []:
            if isinstance(path, str) and os.path.isfile(path):
                self.open_path(path)
        current = data.get("current") or ""
        if current and self.doc_key(current) in self.docs:
            self.select_doc(self.doc_key(current))
            self.keep_file_tab = True
        elif self.doc_tabs.count():
            self.doc_tabs.setCurrentIndex(self.task_tab())

    def raise_window(self):
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        unsaved = self.unsaved_docs()
        if unsaved:
            answer = self.ask_save([os.path.basename(d["path"]) for d in unsaved])
            if answer is None or (answer and not all(self.save_doc(d) for d in unsaved)):
                event.ignore()
                return
        self.save_timer.stop()
        self.flush()
        self.assist.close()
        self.layout_saved = None
        self.save_layout()
        event.accept()
