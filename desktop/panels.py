"""Части окна: панель курсов-папок и результат запуска."""
import base64
import html
import json
import re

from PyQt6.QtCore import QByteArray, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QImage, QTextDocument
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QTextBrowser, QVBoxLayout, QWidget,
)

from icons import done_mark, icon
from theme import code_family

CELL_SIZE = 30
CELL_GAP = 5
CHIPS_IN_ROW = 16
MAX_OUTPUT = 40000
PY_ERROR = re.compile(r'(File "([^"\n]*)", )(line (\d+))')
FILE_ERROR = re.compile(r'([\w./\\:-]*\.(?:rs|js|mjs)):(\d+)')
FOREIGN = ("site-packages", "lib\\python", "lib/python", "/rustc/", "node_modules", "node:", "<frozen")
VERDICT_CODE = re.compile(r"^([A-Z]{2,4}) · (.+)$", re.S)


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


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


class ClickLabel(QLabel):
    def __init__(self, text, on_click):
        super().__init__(text)
        self.on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.on_click()


class KeyButton(QPushButton):
    """Кнопка со значком и подписью клавиш прямо на ней."""

    def __init__(self, text="", keys="", kind=None):
        super().__init__()
        if kind:
            self.setProperty("kind", kind)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(36)
        box = QHBoxLayout(self)
        box.setContentsMargins(12, 0, 12, 0)
        box.setSpacing(8)
        self.picture = QLabel()
        self.caption = QLabel(text)
        self.caption.setObjectName("btnText")
        self.keys = QLabel(keys)
        self.keys.setObjectName("btnKeys")
        for w in (self.picture, self.caption, self.keys):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            box.addWidget(w)
        self.picture.hide()
        self.keys.setVisible(bool(keys))

    def setText(self, text):
        self.caption.setText(text)

    def text(self):
        return self.caption.text()

    def set_picture(self, pixmap):
        self.picture.setPixmap(pixmap)
        self.picture.show()

    def sizeHint(self):
        return QSize(self.layout().sizeHint().width(), 36)


class Sidebar(QScrollArea):
    """Курсы и темы разложены по папкам, внутри темы квадраты задач."""

    def __init__(self, on_open, settings):
        super().__init__()
        self.on_open, self.settings = on_open, settings
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumWidth(200)
        self.host = QWidget()
        self.host.setObjectName("gridHost")
        self.box = QVBoxLayout(self.host)
        self.box.setContentsMargins(10, 14, 10, 12)
        self.box.setSpacing(4)
        self.setWidget(self.host)
        self.tree, self.key, self.t, self.c = {}, None, None, None
        self.sig = None
        self.cols = 0
        self.active_cell = None
        self.scrolled_to = None
        try:
            self.folders = json.loads(settings.value("folders", "{}"))
        except (TypeError, ValueError):
            self.folders = {}

    def columns(self):
        width = self.viewport().width() - 66
        return max(3, (width + CELL_GAP) // (CELL_SIZE + CELL_GAP))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.t and self.columns() != self.cols:
            self.show_tree(self.tree, self.key, self.t, self.c, force=True)

    def toggle(self, folder: str, is_open: bool):
        self.folders[folder] = not is_open
        self.settings.setValue("folders", json.dumps(self.folders))
        self.show_tree(self.tree, self.key, self.t, self.c, force=True)

    def show_tree(self, tree, key, t, c, force=False):
        self.tree, self.key, self.t, self.c = tree, key, t, c
        cols = self.columns()
        sig = json.dumps([tree, key, cols, c["ink"], t["courses"]], sort_keys=True)
        if sig == self.sig and not force:
            return
        self.sig, self.cols = sig, cols
        scroll = self.verticalScrollBar().value()
        clear_layout(self.box)
        self.active_cell = None

        courses = tree.get("courses") or []
        if tree and not courses:
            courses = [{"id": "current", "title": tree.get("title", ""), "href": tree.get("href", ""), "kind": "course",
                        "done": tree.get("done", 0), "total": tree.get("total", 0)}]
        active = tree.get("href")
        regular = [x for x in courses if x.get("kind") != "library"]
        libraries = [x for x in courses if x.get("kind") == "library"]
        if regular:
            self.box.addWidget(self.section(t["courses"]))
            for course in regular:
                self.add_course(course, course.get("href") == active or len(courses) == 1)
        if libraries:
            has_active = any(x.get("href") == active for x in libraries)
            is_open = self.folders.get("#libraries", has_active)
            head = QWidget()
            row = QHBoxLayout(head)
            row.setContentsMargins(0, 8, 0, 2)
            row.setSpacing(5)
            toggle = lambda: self.toggle("#libraries", is_open)
            row.addWidget(self.chevron(is_open, toggle))
            label = ClickLabel(t["libraries"], toggle)
            label.setObjectName("sideSection")
            row.addWidget(label, 1)
            self.box.addWidget(head)
            if is_open:
                for course in libraries:
                    self.add_course(course, course.get("href") == active)
        self.box.addStretch(1)

        target = self.active_cell
        if target is not None and key != self.scrolled_to:
            self.scrolled_to = key
            QTimer.singleShot(0, lambda: self.ensureWidgetVisible(target))
        else:
            QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(scroll))

    def section(self, text):
        label = QLabel(text)
        label.setObjectName("sideSection")
        label.setContentsMargins(6, 0, 0, 2)
        return label

    def chevron(self, is_open, on_click, size=13):
        label = ClickLabel("", on_click)
        label.setPixmap(icon("down" if is_open else "right", self.c["mute"], size))
        label.setFixedSize(size + 4, size + 4)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    def picture(self, name, color, size):
        label = QLabel()
        label.setPixmap(icon(name, color, size))
        label.setFixedSize(size, size)
        return label

    def count(self, done, total):
        label = QLabel(f"{done} / {total}")
        label.setObjectName("count")
        label.setProperty("done", "true" if total and done >= total else "false")
        return label

    def add_course(self, course, active):
        c = self.c
        folder = "course:" + str(course.get("id"))
        is_open = active and self.folders.get(folder, True)
        toggle = (lambda: self.toggle(folder, is_open)) if active else (lambda: self.on_open(course.get("href", "")))
        done, total = course.get("done", 0), course.get("total", 0)
        head = QWidget()
        row = QHBoxLayout(head)
        row.setContentsMargins(2, 3, 4, 3)
        row.setSpacing(6)
        row.addWidget(self.chevron(is_open, toggle))
        color = c["lime"] if active else c["done"] if total and done >= total else c["mute"]
        row.addWidget(self.picture("folder", color, 16))
        title = ClickLabel(course.get("title", ""), toggle)
        title.setObjectName("courseTitle")
        title.setProperty("active", "true" if active else "false")
        title.setWordWrap(True)
        row.addWidget(title, 1)
        row.addWidget(self.count(done, total))
        self.box.addWidget(head)
        if not is_open:
            return

        bar = QProgressBar()
        bar.setObjectName("courseBar")
        bar.setTextVisible(False)
        bar.setFixedHeight(4)
        bar.setRange(0, max(1, total))
        bar.setValue(min(done, total))
        bar_box = QHBoxLayout()
        bar_box.setContentsMargins(8, 4, 4, 8)
        bar_box.addWidget(bar)
        self.box.addLayout(bar_box)

        rows = self.tree.get("rows", [])
        for topic in rows:
            self.box.addWidget(self.make_topic(topic))
        if rows and not rows[-1].get("done"):
            hint = QWidget()
            hint_row = QHBoxLayout(hint)
            hint_row.setContentsMargins(24, 6, 8, 6)
            hint_row.setSpacing(8)
            hint_row.addWidget(self.picture("lock", c["mute"], 14), 0, Qt.AlignmentFlag.AlignTop)
            text = QLabel(self.t["lock_hint"])
            text.setObjectName("lockHint")
            text.setWordWrap(True)
            hint_row.addWidget(text, 1)
            self.box.addWidget(hint)

    def make_topic(self, topic):
        c = self.c
        cells = topic.get("cells")
        has_active = any(x.get("key") == self.key for x in cells or [])
        folder = "topic:" + str(topic.get("id"))
        is_open = self.folders.get(folder, has_active or not topic.get("done"))
        frame = QFrame()
        frame.setObjectName("row")
        frame.setProperty("state", "current" if has_active or (topic.get("current") and not topic.get("done")) else "")
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(9)
        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(self.chevron(is_open, lambda: self.toggle(folder, is_open), 12))
        head.addWidget(self.picture("folder", c["done"] if topic.get("done") else c["lime"], 15))
        href = topic.get("href", "")

        def open_topic():
            if not is_open:
                self.folders[folder] = True
                self.settings.setValue("folders", json.dumps(self.folders))
                self.sig = None
            self.on_open(href)

        title = ClickLabel(topic.get("title", ""), open_topic)
        title.setObjectName("rowHead")
        title.setWordWrap(True)
        head.addWidget(title, 1)
        if cells:
            head.addWidget(self.count(sum(1 for x in cells if x.get("done")), len(cells)))
        outer.addLayout(head)
        if is_open and cells:
            grid = QGridLayout()
            grid.setSpacing(CELL_GAP)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            for i, cell in enumerate(cells):
                grid.addWidget(self.make_cell(cell), i // self.cols, i % self.cols)
            outer.addLayout(grid)
        elif is_open and topic.get("hint"):
            hint = QLabel(topic["hint"])
            hint.setObjectName("lockHint")
            hint.setWordWrap(True)
            outer.addWidget(hint)
        wrapper = QWidget()
        side = QHBoxLayout(wrapper)
        side.setContentsMargins(12, 0, 0, 0)
        side.addWidget(frame)
        return wrapper

    def make_cell(self, cell):
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
        b.clicked.connect(lambda _=False, h=href: self.on_open(h))
        if active:
            self.active_cell = b
        return b


class ResultPanel(QWidget):
    """Вердикт, тесты, сравнение ответов и вывод программы."""

    def __init__(self, on_next, on_link):
        super().__init__()
        self.setObjectName("resultPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.verdict = QWidget()
        self.verdict.setObjectName("verdict")
        self.verdict_row = QHBoxLayout(self.verdict)
        self.verdict_row.setContentsMargins(18, 14, 18, 6)
        self.verdict_row.setSpacing(12)
        self.mark = QLabel()
        self.badge = QLabel()
        self.badge.setObjectName("badge")
        middle = QVBoxLayout()
        middle.setSpacing(6)
        self.middle = middle
        self.title = QLabel()
        self.title.setObjectName("verdictTitle")
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.TextFormat.RichText)
        middle.addWidget(self.title)
        self.chips = QWidget()
        self.chips.setObjectName("verdict")
        self.chips_grid = QGridLayout(self.chips)
        self.chips_grid.setContentsMargins(0, 0, 0, 0)
        self.chips_grid.setSpacing(4)
        self.chips_grid.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.next_btn = KeyButton("", "Ctrl Alt →", "primary")
        self.next_btn.clicked.connect(on_next)
        self.verdict_row.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignVCenter)
        self.verdict_row.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)
        self.verdict_row.addLayout(middle, 1)
        self.verdict_row.addWidget(self.chips, 0, Qt.AlignmentFlag.AlignVCenter)
        self.verdict_row.addWidget(self.next_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(self.verdict)

        self.diff_host = QWidget()
        self.diff_host.setObjectName("diffHost")
        self.diff_grid = QGridLayout(self.diff_host)
        self.diff_grid.setContentsMargins(18, 6, 18, 8)
        self.diff_grid.setHorizontalSpacing(8)
        self.diff_grid.setVerticalSpacing(5)
        root.addWidget(self.diff_host)

        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(on_link)
        self.browser.document().setDocumentMargin(18)
        root.addWidget(self.browser, 1)

    def fill_verdict(self, s, t, c):
        result = s.get("result")
        self.verdict.setVisible(bool(result))
        if not result:
            return
        tone = result.get("tone") or ""
        title = result.get("title", "")
        code = VERDICT_CODE.match(title)
        self.mark.setVisible(tone == "ok")
        if tone == "ok":
            self.mark.setPixmap(done_mark(c["done"], c["ondone"]))
        self.badge.setVisible(bool(code) and tone != "ok")
        if code and tone != "ok":
            self.badge.setText(code.group(1))
            title = code.group(2)
        text = html.escape(title, quote=False)
        if result.get("xp"):
            text += f' <span style="color:{c["done"]};">{html.escape(result["xp"], quote=False)}</span>'
        self.title.setText(text)
        self.title.setProperty("tone", tone)
        self.title.style().unpolish(self.title)
        self.title.style().polish(self.title)

        clear_layout(self.chips_grid)
        tests = s.get("tests") or []
        self.chips.setVisible(bool(tests))
        for i, test in enumerate(tests):
            chip = QLabel(str(test.get("n", i + 1)))
            chip.setObjectName("chip")
            chip.setProperty("tone", test.get("tone") or "")
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setFixedSize(22, 22)
            if test.get("verdict"):
                chip.setToolTip(test["verdict"])
            self.chips_grid.addWidget(chip, i // CHIPS_IN_ROW, i % CHIPS_IN_ROW)
        # Решено: квадраты под заголовком, а справа кнопка следующей задачи
        if tone == "ok":
            self.middle.addWidget(self.chips, 0, Qt.AlignmentFlag.AlignLeft)
        else:
            self.verdict_row.insertWidget(3, self.chips, 0, Qt.AlignmentFlag.AlignVCenter)
        self.next_btn.setVisible(bool(s.get("next")))
        if s.get("next"):
            self.next_btn.setText(s["next"])

    def fill_diff(self, items):
        clear_layout(self.diff_grid)
        self.diff_host.setVisible(bool(items))
        texts = [item.get("text", "").rstrip("\n")[:MAX_OUTPUT] for item in items or []]
        lines = min(4, max([text.count("\n") + 1 for text in texts] or [1]))
        for col, item in enumerate(items or []):
            label = QLabel(item.get("label", ""))
            label.setObjectName("diffLabel")
            box = QPlainTextEdit(texts[col])
            box.setObjectName("diffBox")
            box.setProperty("kind", item.get("kind") or "")
            box.setReadOnly(True)
            box.setFixedHeight(lines * 19 + 22)
            box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.diff_grid.addWidget(label, 0, col)
            self.diff_grid.addWidget(box, 1, col)
            self.diff_grid.setColumnStretch(col, 1)

    def show_status(self, s, t, c):
        s = s or {}
        self.fill_verdict(s, t, c)
        self.fill_diff(s.get("diff"))
        esc = lambda x: html.escape(str(x), quote=False)
        mono = f"font-family:'{code_family()}';"

        def box(label, body, color=None, bg=None):
            return (
                f'<div style="color:{c["mute"]};font-size:12px;">{esc(label)}</div>'
                f'<table width="100%" cellspacing="0" cellpadding="8" bgcolor="{bg or c["code"]}"><tr><td>'
                f'<pre style="{mono}color:{color or c["fg2"]};white-space:pre-wrap;margin:0;">{body}</pre></td></tr></table>'
                f'<div style="font-size:5px;">&nbsp;</div>'
            )

        document = self.browser.document()
        document.setDefaultStyleSheet(f"a {{ color: {c['lime']}; }}")
        parts = []
        if s.get("error"):
            parts.append(box(t["stderr"], link_errors(s["error"][:MAX_OUTPUT]), c["rose"], c["rosebg"]))
        run = s.get("run")
        if run:
            if run.get("label"):
                tone = c["rose"] if run.get("tone") == "fail" else c["mute"]
                parts.append(f'<div style="color:{tone};font-weight:700;">{esc(run["label"])}</div>')
            out = run.get("stdout") or ""
            if out:
                parts.append(box(t["stdout"], link_errors(out[:MAX_OUTPUT])))
            elif not run.get("stderr"):
                parts.append(f'<div style="color:{c["mute"]};">{esc(t["no_output"])}</div>')
            if run.get("stderr"):
                parts.append(box(t["stderr"], link_errors(run["stderr"][:MAX_OUTPUT]), c["rose"], c["rosebg"]))
            for i, data in enumerate(run.get("images") or []):
                image = QImage.fromData(QByteArray(base64.b64decode(data.split(",", 1)[-1])))
                if not image.isNull():
                    document.addResource(QTextDocument.ResourceType.ImageResource, QUrl(f"cwmimg:{i}"), image)
                    parts.append(f'<div><img src="cwmimg:{i}" width="{min(image.width(), 520)}"></div>')
        if s.get("note"):
            parts.append(f'<div style="color:{c["mute"]};font-size:12px;">{esc(s["note"])}</div>')
        if not parts and not s.get("result"):
            parts.append(f'<div style="color:{c["mute"]};">{esc(t["output_empty"])}</div>')
        self.browser.setHtml("".join(parts))
        return (run or {}).get("time") or ""
