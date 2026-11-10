"""Части окна: панель курсов-папок и результат запуска."""
import base64
import html
import json
import re
import time

from PyQt6.QtCore import QByteArray, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QIcon, QImage, QTextCharFormat, QTextCursor, QTextDocument
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
    QSplitter, QTextBrowser, QVBoxLayout, QWidget, QWidgetAction,
)

from icons import done_mark, icon
from theme import code_family

CELL_SIZE = 30
CELL_GAP = 5
CHIPS_IN_ROW = 16
MAX_OUTPUT = 40000
MAX_LOG_BLOCKS = 20000  # строк в журнале запусков, старые уходят
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
        self.on_open = on_open  # on_open(href, key)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(2)
        self.sig = None
        self.buttons = {}
        self.key = None
        self.active = True  # False — сейчас открыт другой файл, задача не подсвечена
        self.compact = False  # мало места: на вкладках только буквы, название — в подсказке

    def extra_width(self) -> int:
        """Насколько ряд станет шире, если вернуть полные названия."""
        return sum(b.extra_w for b in self.buttons.values())

    def set_compact(self, compact: bool):
        if compact == self.compact:
            return
        self.compact = compact
        for b in self.buttons.values():
            b.setText(b.short_text if compact else b.full_text)

    def set_active(self, active: bool):
        self.active = active
        for key, b in self.buttons.items():
            set_active_prop(b, active and key == self.key)

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
        self.key = key
        self.buttons = {}
        clear_layout(self.row)
        cells = (row or {}).get("cells") or []
        for cell in cells:
            label = str(cell.get("label", ""))
            title = cell.get("title") or ""
            text = f"{label}. {title}" if title else label
            font = QFont(self.font())  # как у вкладки в теме: 13px, жирный — иначе «…» не помещается
            font.setPixelSize(13)
            font.setWeight(QFont.Weight.Bold)
            b = QPushButton(QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, 180))
            b.setObjectName("taskTab")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            active = self.active and cell.get("key") == key
            b.setProperty("active", "true" if active else "false")
            if cell.get("done"):
                b.setIcon(QIcon(icon("check", c["done"], 12)))
            b.setToolTip(title or text)
            href = cell.get("href", "")
            b.clicked.connect(lambda _=False, h=href, k=cell.get("key"): self.on_open(h, k))
            self.buttons[cell.get("key")] = b
            b.full_text, b.short_text = b.text(), label
            fm = QFontMetrics(font)
            b.extra_w = max(0, fm.horizontalAdvance(b.full_text) - fm.horizontalAdvance(label)) + 4
            if self.compact:
                b.setText(label)
            self.row.addWidget(b)
        if row and not cells and row.get("hint"):
            hint = QLabel(row["hint"])
            hint.setObjectName("muted")
            self.row.addWidget(hint)


class TabScroll(QScrollArea):
    """Ряд вкладок без полосы прокрутки: колесо листает его вбок, выбранная вкладка всегда видна."""

    def __init__(self, strip: QWidget, tasks: "TaskTabs"):
        super().__init__()
        self.tasks = tasks
        self.setObjectName("tabScroll")
        self.setWidget(strip)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        strip.installEventFilter(self)

    def sizeHint(self):
        return QSize(200, self.widget().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(80, self.widget().minimumSizeHint().height())

    def wheelEvent(self, e):
        bar = self.horizontalScrollBar()
        delta = e.angleDelta().y() or e.angleDelta().x()
        bar.setValue(bar.value() - delta // 2)
        e.accept()

    def eventFilter(self, obj, e):
        if e.type() == e.Type.LayoutRequest:
            self.setFixedHeight(self.widget().sizeHint().height())
            QTimer.singleShot(0, self.fit)
        return False

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self.fit)

    def fit(self):
        """Не хватает места — у задач остаются буквы A, B, C; появилось — названия возвращаются."""
        full = self.widget().sizeHint().width() + (self.tasks.extra_width() if self.tasks.compact else 0)
        self.tasks.set_compact(full > self.viewport().width())
        self.show_active()

    def show_active(self):
        for b in self.widget().findChildren(QPushButton):
            if b.property("active") == "true" and b.isVisible():
                self.ensureWidgetVisible(b, 24, 0)
                return


def set_active_prop(widget, active: bool):
    value = "true" if active else "false"
    if widget.property("active") != value:
        widget.setProperty("active", value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


class DocTabs(QWidget):
    """Вкладки открытых файлов в одном ряду с задачами A, B, C.
    Нулевая вкладка — файл задачи: своей кнопки у неё нет, её показывают сами вкладки задач.
    Повторяет нужную часть QTabBar, чтобы окно работало с ней так же."""

    currentChanged = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(2)
        self.tabs = []  # {"data", "button"}
        self.current = -1

    def count(self) -> int:
        return len(self.tabs)

    def currentIndex(self) -> int:
        return self.current

    def addTab(self, text: str) -> int:
        b = None
        if self.tabs:  # первая вкладка — задача, без кнопки
            b = QPushButton(text)
            b.setObjectName("taskTab")
            b.setProperty("file", "true")
            b.setProperty("active", "false")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, w=b: self.setCurrentIndex(self._index_of(w)))
            inner = QHBoxLayout(b)
            inner.setContentsMargins(0, 0, 6, 0)
            inner.addStretch(1)
            self.row.addWidget(b)
        self.tabs.append({"data": None, "button": b})
        if self.current < 0:
            self.setCurrentIndex(0)
        return len(self.tabs) - 1

    def _index_of(self, widget) -> int:
        return next((i for i, t in enumerate(self.tabs) if t["button"] is widget), -1)

    def setTabData(self, i: int, data):
        self.tabs[i]["data"] = data

    def tabData(self, i: int):
        return self.tabs[i]["data"] if 0 <= i < len(self.tabs) else None

    def setTabText(self, i: int, text: str):
        if self.tabs[i]["button"]:
            self.tabs[i]["button"].setText(text)

    def tabText(self, i: int) -> str:
        return self.tabs[i]["button"].text() if self.tabs[i]["button"] else ""

    def setTabToolTip(self, i: int, text: str):
        if self.tabs[i]["button"]:
            self.tabs[i]["button"].setToolTip(text)

    def setTabButton(self, i: int, _position, widget):
        b = self.tabs[i]["button"]
        if b:
            b.layout().addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)

    def setCurrentIndex(self, i: int):
        if not 0 <= i < len(self.tabs) or i == self.current:
            return
        self.current = i
        for n, t in enumerate(self.tabs):
            if t["button"]:
                set_active_prop(t["button"], n == i)
        self.currentChanged.emit(i)

    def removeTab(self, i: int):
        tab = self.tabs.pop(i)
        if tab["button"]:
            self.row.removeWidget(tab["button"])
            tab["button"].deleteLater()
        if self.current == i:
            self.current = -1
            self.setCurrentIndex(max(0, i - 1))  # как в обычных IDE: соседняя вкладка слева
        elif self.current > i:
            self.current -= 1


class InputBox(QPlainTextEdit):
    """Строка ввода под журналом, как в терминале: Enter отдаёт текст программе,
    Shift+Enter — новая строка, Ctrl+D — конец ввода. Пока ничего не запущено,
    написанное здесь уйдёт программе при следующем запуске файла."""

    submitted = pyqtSignal(str)
    eof = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.live = False

    def keyPressEvent(self, e):
        mods = e.modifiers()
        if self.live and e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not mods & Qt.KeyboardModifier.ShiftModifier:
            text = self.toPlainText()
            self.clear()
            self.submitted.emit(text)
            return
        if self.live and e.key() == Qt.Key.Key_D and mods & Qt.KeyboardModifier.ControlModifier:
            self.eof.emit()
            return
        super().keyPressEvent(e)


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
        # Ниже — журнал всех запусков: тесты, установка, сборка, запуски на сайте
        log_host = QWidget()
        log_host.setObjectName("logHost")
        lv = QVBoxLayout(log_host)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        log_bar = QFrame()
        log_bar.setObjectName("logBar")
        lb = QHBoxLayout(log_bar)
        lb.setContentsMargins(14, 4, 8, 4)
        self.log_title = QLabel()
        self.log_title.setObjectName("logTitle")
        self.log_clear = button(kind="quiet")
        self.log_clear.clicked.connect(lambda: self.log_box.clear())
        self.log_hide = button(kind="quiet")
        lb.addWidget(self.log_title, 1)
        lb.addWidget(self.log_clear)
        lb.addWidget(self.log_hide)
        self.log_box = QPlainTextEdit()
        self.log_box.setObjectName("logBox")
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(MAX_LOG_BLOCKS)
        self.log_box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.stdin = InputBox()
        self.stdin.setObjectName("stdinBox")
        self.stdin.setFixedHeight(48)
        lv.addWidget(log_bar)
        lv.addWidget(self.log_box, 1)
        lv.addWidget(self.stdin)
        self.console = log_host  # окно встраивает вывод программы над тестами, отдельной панели нет
        split = QSplitter(Qt.Orientation.Vertical)
        split.setHandleWidth(1)
        split.addWidget(self.browser)
        split.addWidget(log_host)
        split.setSizes([110, 300])
        root.addWidget(split, 1)

    def set_texts(self, t):
        self.t = t
        self.log_title.setText(t["debug_log"])
        self.log_clear.setText(t["debug_clear"])
        self.log_hide.setText(t["console_hide"])
        self.set_live(self.stdin.live)

    def set_live(self, live: bool):
        """Программа запущена и читает ввод: строка ввода отправляет текст сразу по Enter."""
        self.stdin.live = live
        t = getattr(self, "t", None)
        if t:
            self.stdin.setPlaceholderText(t["file_input_live"] if live else t["file_stdin"])
        if live:
            self.log_box.appendPlainText("")  # вывод программы пойдёт с новой строки

    def write(self, text: str, color=None):
        """Дописывает вывод работающей программы прямо в конец журнала, без перевода строки."""
        if not text:
            return
        cursor = self.log_box.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        if color:
            fmt.setForeground(QColor(color))
        cursor.insertText(text.replace("\r\n", "\n"), fmt)
        bar = self.log_box.verticalScrollBar()
        bar.setValue(bar.maximum())

    def log(self, title: str, body: str = "", error: str = "", c=None):
        """Добавляет запись в журнал: заголовок, вывод программы и ошибки красным."""
        esc = lambda x: html.escape(x, quote=False)
        stamp = time.strftime("%H:%M:%S")
        parts = [f'<span style="color:{c["mute"]};">{stamp}</span> <b>{esc(title)}</b>']
        if body:
            parts.append(f'<pre style="margin:0;">{esc(body.rstrip()[:MAX_OUTPUT])}</pre>')
        if error:
            parts.append(f'<pre style="margin:0;color:{c["rose"]};">{esc(error.rstrip()[:MAX_OUTPUT])}</pre>')
        self.log_box.appendHtml("".join(parts))
        bar = self.log_box.verticalScrollBar()
        bar.setValue(bar.maximum())

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
