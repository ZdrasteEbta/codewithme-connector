"""Части окна: панель курсов-папок и результат запуска."""
import base64
import html
import json
import re

from PyQt6.QtCore import QByteArray, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QFontMetrics, QIcon, QImage, QTextDocument
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
    QTextBrowser, QVBoxLayout, QWidget, QWidgetAction,
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


class ClickRow(QFrame):
    """Строка, по которой можно щёлкнуть целиком."""

    def __init__(self, on_click, name):
        super().__init__()
        self.setObjectName(name)
        self.on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.on_click()


# Пока сайт старой версии не присылает язык курса, окно знает его само
LANGUAGE_LABELS = {"python": "Python", "javascript": "JavaScript", "html-css": "HTML & CSS", "rust": "Rust"}
LIBRARY_LANGUAGE = {
    "dom": "javascript", "react": "javascript", "vue": "javascript", "nodejs": "javascript", "express": "javascript",
    "canvas": "javascript", "phaser": "javascript", "macroquad": "rust",
}


class Picker(QPushButton):
    """Выпадающий выбор: название и стрелка справа, по щелчку список."""

    def __init__(self, text, arrow, big=False):
        super().__init__()
        self.setObjectName("picker")
        self.setProperty("big", "true" if big else "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        box = QHBoxLayout(self)
        box.setContentsMargins(12, 0, 10, 0)
        box.setSpacing(6)
        self.caption = QLabel(text)
        self.caption.setObjectName("pickerText")
        self.arrow = QLabel()
        self.arrow.setPixmap(arrow)
        for w in (self.caption, self.arrow):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        box.addWidget(self.caption, 1)
        box.addWidget(self.arrow)
        self.setFixedHeight(40 if big else 36)
        self.clicked.connect(self.open_menu)
        self.menu = QMenu(self)

    def open_menu(self):
        self.menu.setMinimumWidth(self.width())
        self.menu.exec(self.mapToGlobal(self.rect().bottomLeft()))


class Sidebar(QScrollArea):
    """Слева выбор языка, под ним выбор курса или библиотеки этого языка и темы курса с номерами."""

    def __init__(self, on_open, settings):
        super().__init__()
        self.on_open, self.settings = on_open, settings
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumWidth(190)
        self.host = QWidget()
        self.host.setObjectName("gridHost")
        self.box = QVBoxLayout(self.host)
        self.box.setContentsMargins(10, 12, 10, 12)
        self.box.setSpacing(2)
        self.setWidget(self.host)
        self.tree, self.key, self.t, self.c = {}, None, None, None
        self.sig = None
        self.active_cell = None
        self.scrolled_to = None

    @staticmethod
    def groups(courses: list) -> dict:
        """Курсы по языкам: {язык: {'label', 'items'}}. Библиотека идёт под курсом своего языка."""
        out = {}
        for item in courses:
            library = item.get("kind") == "library"
            group = item.get("group") or (LIBRARY_LANGUAGE.get(item.get("id"), "python") if library else item.get("id", ""))
            label = item.get("groupLabel") or LANGUAGE_LABELS.get(group) or item.get("title", "")
            out.setdefault(group, {"label": label, "items": []})["items"].append(item)
        return out

    def show_tree(self, tree, key, t, c, force=False):
        self.tree, self.key, self.t, self.c = tree, key, t, c
        sig = json.dumps([tree, key, c["ink"], t["courses"]], sort_keys=True)
        if sig == self.sig and not force:
            return
        self.sig = sig
        scroll = self.verticalScrollBar().value()
        clear_layout(self.box)
        self.active_cell = None

        courses = tree.get("courses") or []
        if tree and not courses:
            courses = [{"id": "current", "title": tree.get("title", ""), "href": tree.get("href", ""), "kind": "course"}]
        active = tree.get("href")
        groups = self.groups(courses)
        current = next((x for x in courses if x.get("href") == active), courses[0] if courses else None)
        if current:
            group_id = next(g for g, v in groups.items() if current in v["items"])
            group = groups[group_id]
            self.add_caption(t["pick_language"])
            language = Picker(group["label"], icon("down", c["mute"], 12), big=True)
            for gid, entry in groups.items():
                main = next((x for x in entry["items"] if x.get("kind") != "library"), entry["items"][0])
                action = language.menu.addAction(entry["label"])
                action.setCheckable(True)
                action.setChecked(gid == group_id)
                action.triggered.connect(lambda _=False, h=main.get("href", ""), same=gid == group_id: same or self.on_open(h))
            self.box.addWidget(language)
            if len(group["items"]) > 1:
                self.box.addSpacing(8)
                self.add_caption(t["pick_course"])
                course = Picker(current.get("title", ""), icon("down", c["mute"], 12))
                regular = [x for x in group["items"] if x.get("kind") != "library"]
                libraries = [x for x in group["items"] if x.get("kind") == "library"]
                self.add_section(course.menu, t["main_course"])
                for item in regular:
                    self.add_choice(course.menu, item, current)
                # Библиотеки по разделам, как на странице курса: «Данные», «GameDev», «Веб»…
                sections = {}
                for item in libraries:
                    sections.setdefault(item.get("section") or t["libraries"].capitalize(), []).append(item)
                for name, items in sections.items():
                    self.add_section(course.menu, name)
                    for item in items:
                        self.add_choice(course.menu, item, current)
                self.box.addWidget(course)
            self.box.addSpacing(10)
        for n, topic in enumerate(tree.get("rows", []), 1):
            self.box.addWidget(self.make_topic(n, topic))
        self.box.addStretch(1)

        target = self.active_cell
        if target is not None and key != self.scrolled_to:
            self.scrolled_to = key
            QTimer.singleShot(0, lambda: self.ensureWidgetVisible(target))
        else:
            QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(scroll))

    def add_caption(self, text):
        caption = QLabel(text)
        caption.setObjectName("pickCaption")
        self.box.addWidget(caption)
        self.box.addSpacing(3)

    @staticmethod
    def add_section(menu, text):
        """Подпись раздела в списке: обычный addSection в этой теме рисуется пустой чертой."""
        label = QLabel(text)
        label.setObjectName("menuSection")
        action = QWidgetAction(menu)
        action.setDefaultWidget(label)
        action.setEnabled(False)
        menu.addAction(action)

    def add_choice(self, menu, item, current):
        action = menu.addAction(item.get("title", ""))
        action.setCheckable(True)
        action.setChecked(item is current)
        href = item.get("href", "")
        action.triggered.connect(lambda _=False: item is current or self.on_open(href))

    def make_topic(self, n, topic):
        """Тема — одна строка с номером. Её задачи открываются вкладками A, B, C над редактором."""
        cells = topic.get("cells") or []
        current = any(x.get("key") == self.key for x in cells) or (bool(topic.get("current")) and not self.key_in_tree())
        href = topic.get("href", "")
        row = ClickRow(lambda: self.on_open(href), "topicItem")
        state = "current" if current else "done" if topic.get("done") else "locked" if topic.get("cells") is None else ""
        row.setProperty("state", state)
        box = QVBoxLayout(row)
        box.setContentsMargins(12, 7, 10, 7)
        box.setSpacing(3)
        title = QLabel(f"{n}. {topic.get('title', '')}")
        title.setObjectName("topicText")
        title.setProperty("state", state)
        title.setWordWrap(True)
        box.addWidget(title)
        if current and not cells and topic.get("hint"):
            hint = QLabel(topic["hint"])
            hint.setObjectName("lockHint")
            hint.setWordWrap(True)
            box.addWidget(hint)
        if current:
            self.active_cell = row
        return row

    def key_in_tree(self) -> bool:
        return any(x.get("key") == self.key for row in self.tree.get("rows", []) for x in row.get("cells") or [])


class TaskTabs(QWidget):
    """Задачи открытой темы вкладками над редактором: A, B, C."""

    def __init__(self, on_open):
        super().__init__()
        self.on_open = on_open
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(2)
        self.sig = None

    @staticmethod
    def current_row(tree: dict, key):
        rows = tree.get("rows", [])
        for row in rows:
            if any(x.get("key") == key for x in row.get("cells") or []):
                return row
        return next((r for r in rows if r.get("current")), None)

    def show_row(self, tree: dict, key, c: dict, t: dict):
        row = self.current_row(tree, key)
        sig = json.dumps([row, key, c["ink"]], sort_keys=True)
        if sig == self.sig:
            return
        self.sig = sig
        clear_layout(self.row)
        cells = (row or {}).get("cells") or []
        for cell in cells:
            label = str(cell.get("label", ""))
            title = cell.get("title") or ""
            text = f"{label}. {title}" if title else label
            b = QPushButton(QFontMetrics(self.font()).elidedText(text, Qt.TextElideMode.ElideRight, 190))
            b.setObjectName("taskTab")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            active = cell.get("key") == key
            b.setProperty("active", "true" if active else "false")
            if cell.get("done"):
                b.setIcon(QIcon(icon("check", c["done"], 12)))
            b.setToolTip(title or text)
            href = cell.get("href", "")
            b.clicked.connect(lambda _=False, h=href: self.on_open(h))
            self.row.addWidget(b)
        if row and not cells and row.get("hint"):
            hint = QLabel(row["hint"])
            hint.setObjectName("muted")
            self.row.addWidget(hint)
        self.row.addStretch(1)


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
