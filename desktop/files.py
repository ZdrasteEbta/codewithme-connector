"""Проводник файлов и вкладки открытых файлов, как в обычной IDE."""
import os

from PyQt6.QtCore import QDir, QFile, QModelIndex, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFileSystemModel, QIcon
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox, QTreeView, QVBoxLayout, QWidget,
)

from icons import icon
from panels import button

MAX_OPEN_BYTES = 5 << 20  # большие файлы в редакторе тормозят, их открывать не будем

LANGUAGES = {
    ".py": "python", ".pyw": "python", ".rs": "rust", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "javascript", ".jsx": "javascript", ".tsx": "javascript", ".json": "javascript",
    ".html": "html", ".htm": "html", ".css": "html", ".xml": "html", ".svg": "html",
}


def language_for(path: str) -> str:
    """Подсветка по расширению; всё прочее (txt, md, csv) показывается как текст."""
    return LANGUAGES.get(os.path.splitext(path)[1].lower(), "text")


RUNNABLE = {".py": "python", ".pyw": "python", ".js": "node", ".mjs": "node", ".cjs": "node", ".rs": "rust"}


def run_language(path: str) -> str:
    """Чем запускать файл: python, node, rust; пустая строка — такой файл не запускается."""
    return RUNNABLE.get(os.path.splitext(path)[1].lower(), "")


def same_path(a: str, b: str) -> bool:
    return bool(a and b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def read_text(path: str):
    """(текст, ошибка). Бинарные и слишком большие файлы не открываем."""
    try:
        if os.path.getsize(path) > MAX_OPEN_BYTES:
            return None, "big"
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        return None, str(e)
    if b"\0" in data[:8192]:
        return None, "binary"
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding).replace("\r\n", "\n"), None
        except UnicodeDecodeError:
            continue
    return None, "binary"


def write_text(path: str, text: str):
    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return None
    except OSError as e:
        return str(e)


class Explorer(QWidget):
    """Дерево папки: двойной щелчок открывает файл, правая кнопка — создать, переименовать, удалить."""

    open_file = pyqtSignal(str)
    changed_root = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("explorer")
        self.t, self.c = {}, {}
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("explorerBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 6, 6, 6)
        row.setSpacing(2)
        self.root_label = QLabel()
        self.root_label.setObjectName("explorerRoot")
        row.addWidget(self.root_label, 1)
        self.new_file_btn = self._tool(row, lambda: self.create(False))
        self.new_dir_btn = self._tool(row, lambda: self.create(True))
        self.open_btn = self._tool(row, self.choose_root)
        box.addWidget(bar)

        self.model = QFileSystemModel(self)
        self.model.setReadOnly(False)
        self.model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden)
        self.tree = QTreeView()
        self.tree.setObjectName("explorerTree")
        self.tree.setModel(self.model)
        for column in (1, 2, 3):
            self.tree.hideColumn(column)
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(False)
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context_menu)
        self.tree.activated.connect(self.activate)
        box.addWidget(self.tree, 1)
        self.root = ""

    def _tool(self, row, on_click):
        b = button(kind="quiet")
        b.setFixedSize(26, 24)
        b.clicked.connect(on_click)
        row.addWidget(b)
        return b

    def set_texts(self, t: dict, c: dict):
        self.t, self.c = t, c
        for b, name, tip in ((self.new_file_btn, "new_file", "new_file"), (self.new_dir_btn, "folder", "new_folder"),
                             (self.open_btn, "open", "open_dir")):
            b.setIcon(QIcon(icon(name, c["mute"], 14)))
            b.setToolTip(t[tip])
        self._show_root()

    def set_root(self, path: str):
        if not path or not os.path.isdir(path) or same_path(path, self.root):
            return
        self.root = path
        self.tree.setRootIndex(self.model.setRootPath(path))
        self._show_root()
        self.changed_root.emit(path)

    def _show_root(self):
        self.root_label.setText(os.path.basename(os.path.normpath(self.root)).upper() if self.root else "")
        self.root_label.setToolTip(self.root)

    def choose_root(self):
        path = QFileDialog.getExistingDirectory(self, self.t.get("open_dir", ""), self.root or os.path.expanduser("~"))
        if path:
            self.set_root(path)

    def activate(self, index: QModelIndex):
        path = self.model.filePath(index)
        if os.path.isfile(path):
            self.open_file.emit(path)

    def selected_dir(self) -> str:
        index = self.tree.currentIndex()
        if index.isValid():
            path = self.model.filePath(index)
            return path if os.path.isdir(path) else os.path.dirname(path)
        return self.root

    def create(self, folder: bool, where: str = ""):
        where = where or self.selected_dir()
        if not where:
            return
        name, ok = QInputDialog.getText(self, self.t["new_folder" if folder else "new_file"], self.t["name_prompt"])
        name = name.strip()
        if not ok or not name:
            return
        if any(x in name for x in '<>:"|?*') or name in (".", ".."):
            QMessageBox.warning(self, self.t["new_file"], self.t["bad_name"])
            return
        path = os.path.join(where, name)
        if os.path.exists(path):
            QMessageBox.warning(self, self.t["new_file"], self.t["file_exists"])
            return
        try:
            if folder:
                os.makedirs(path)
            else:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "x", encoding="utf-8").close()
        except OSError as e:
            QMessageBox.warning(self, self.t["new_file"], str(e))
            return
        self.tree.setCurrentIndex(self.model.index(path))
        if not folder:
            self.open_file.emit(path)

    def rename(self, path: str):
        old = os.path.basename(path)
        name, ok = QInputDialog.getText(self, self.t["rename"], self.t["name_prompt"], text=old)
        name = name.strip()
        if not ok or not name or name == old:
            return
        target = os.path.join(os.path.dirname(path), name)
        if os.path.exists(target):
            QMessageBox.warning(self, self.t["rename"], self.t["file_exists"])
            return
        try:
            os.rename(path, target)
        except OSError as e:
            QMessageBox.warning(self, self.t["rename"], str(e))

    def delete(self, path: str):
        """В корзину, а не насовсем: так удалённое можно вернуть."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(self.t["delete"])
        box.setText(self.t["delete_confirm"].format(name=os.path.basename(path)))
        yes = box.addButton(self.t["delete"], QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(self.t["cancel"], QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is yes and not QFile.moveToTrash(path):
            QMessageBox.warning(self, self.t["delete"], self.t["delete_failed"])

    def context_menu(self, point):
        index = self.tree.indexAt(point)
        path = self.model.filePath(index) if index.isValid() else self.root
        if not path:
            return
        is_dir = os.path.isdir(path)
        where = path if is_dir else os.path.dirname(path)
        menu = QMenu(self)
        if not is_dir:
            menu.addAction(self.t["open_file_item"], lambda: self.open_file.emit(path))
            menu.addSeparator()
        menu.addAction(self.t["new_file"], lambda: self.create(False, where))
        menu.addAction(self.t["new_folder"], lambda: self.create(True, where))
        if index.isValid():
            menu.addSeparator()
            menu.addAction(self.t["rename"], lambda: self.rename(path))
            menu.addAction(self.t["delete"], lambda: self.delete(path))
        menu.addSeparator()
        menu.addAction(self.t["reveal"], lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(where)))
        menu.exec(self.tree.viewport().mapToGlobal(point))
