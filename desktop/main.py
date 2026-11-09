"""CodeWithMe IDE: запуск приложения."""
import argparse
import sys
import traceback
from pathlib import Path

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QIcon
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout

from backend import Api, Helper
from texts import TEXTS, system_locale
from theme import palette, stylesheet
from window import MainWindow

INSTANCE = "CodeWithMeIDE"


def resource(name: str) -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return str(base / name)


def ask_folder(t: dict) -> str | None:
    default = str(Path.home() / "CodeWithMe")
    d = QDialog()
    d.setWindowTitle(t["folder_title"])
    d.setMinimumWidth(480)
    box = QVBoxLayout(d)
    text = QLabel(t["folder_text"])
    text.setWordWrap(True)
    box.addWidget(text)
    row = QHBoxLayout()
    path = QLineEdit(default)
    choose = QPushButton(t["browse"])
    row.addWidget(path, 1)
    row.addWidget(choose)
    box.addLayout(row)
    go = QPushButton(t["continue"])
    go.setProperty("kind", "primary")
    go.setDefault(True)
    actions = QHBoxLayout()
    actions.addStretch(1)
    actions.addWidget(go)
    box.addLayout(actions)

    def browse():
        chosen = QFileDialog.getExistingDirectory(d, t["folder_title"], path.text())
        if chosen:
            path.setText(chosen)

    choose.clicked.connect(browse)
    go.clicked.connect(d.accept)
    return path.text().strip() if d.exec() else None


def report_error(kind, value, trace) -> None:
    """Ошибка в обработчике не должна закрывать приложение вместе с кодом ученика."""
    if sys.stderr:
        traceback.print_exception(kind, value, trace)


def main() -> int:
    sys.excepthook = report_error
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--folder", default="")
    args, _ = parser.parse_known_args()

    app = QApplication(sys.argv)
    app.setApplicationName("CodeWithMe IDE")
    app.setOrganizationName("CodeWithMe")
    app.setStyle("Fusion")
    icon = QIcon(resource("icon.png"))
    app.setWindowIcon(icon)

    # Вторая копия только поднимает окно первой
    probe = QLocalSocket()
    probe.connectToServer(INSTANCE)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.waitForBytesWritten(300)
        probe.disconnectFromServer()
        return 0
    QLocalServer.removeServer(INSTANCE)
    instance = QLocalServer()
    instance.listen(INSTANCE)

    settings = QSettings("CodeWithMe", "IDE-dev" if args.dev else "IDE")
    locale = settings.value("locale", system_locale())
    t = TEXTS.get(locale, TEXTS["ru"])
    app.setStyleSheet(stylesheet(palette(settings.value("theme", "dark"))))

    folder = args.folder or settings.value("folder", "")
    if not folder:
        folder = ask_folder(t)
        if not folder:
            return 0
    if not args.folder:
        settings.setValue("folder", folder)

    try:
        helper = Helper(folder, args.dev)
    except OSError as err:
        QMessageBox.critical(None, "CodeWithMe IDE", f'{t["start_failed"]}\n\n{err}')
        return 1
    if not helper.wait_ready():
        details = "\n".join(helper.last_lines)
        helper.stop()
        QMessageBox.critical(None, "CodeWithMe IDE", f'{t["start_failed"]}\n\n{details}')
        return 1

    window = MainWindow(Api(helper.port), settings)
    window.show()
    window.dark_title_bar()

    def wake():
        peer = instance.nextPendingConnection()
        if peer:
            peer.deleteLater()
        window.raise_window()

    instance.newConnection.connect(wake)
    code = app.exec()
    helper.stop()
    window.poller.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())
