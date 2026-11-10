"""Тесты справа от редактора, как в CP Editor: примеры с сайта и свои, запуск прямо на компьютере."""
import math
import re
import threading
import time

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetrics, QIcon
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget

from icons import icon
from panels import button, clear_layout
from theme import code_family

INSTALL_POLL_S = 0.8
OUTPUT_LIMIT = 1 << 20
MAX_LINES = 8
NUMBER = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def _exact(text: str) -> str:
    text = text.replace("\r\n", "\n")
    return text[:-1] if text.endswith("\n") else text


def compare_output(got: str, expected: str, checker: str = "tokens", abs_err=None, rel_err=None) -> bool:
    """То же сравнение, что у сайта (lib/checkers.mjs): по словам, точно или с погрешностью для чисел."""
    if checker == "exact":
        return _exact(got) == _exact(expected)
    a, b = got.split(), expected.split()
    if len(a) != len(b):
        return False
    if checker != "float":
        return a == b
    abs_err = 1e-6 if abs_err is None else abs_err
    rel_err = 1e-6 if rel_err is None else rel_err
    for x, y in zip(a, b):
        if not NUMBER.match(x) or not NUMBER.match(y):
            if x != y:
                return False
            continue
        fx, fy = float(x), float(y)
        if not (math.isfinite(fx) and math.isfinite(fy)) or abs(fx - fy) > max(abs_err, rel_err * abs(fy)):
            return False
    return True


class TestRunner(QObject):
    """Ставит Python или Rust, если их ещё нет, и прогоняет тесты по очереди в отдельном потоке."""

    step = pyqtSignal(str)
    result = pyqtSignal(int, dict)
    finished = pyqtSignal()

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.cancelled = False
        self.current = None
        self.running = False

    def start(self, jobs, language: str, code: str, pip: list, time_ms: int, texts: dict) -> None:
        self.cancelled, self.running = False, True
        threading.Thread(target=self._work, args=(jobs, language, code, pip, time_ms, texts), daemon=True).start()

    def stop(self) -> None:
        self.cancelled = True
        if self.current:
            self.api.post("/app/cancel", {"runId": self.current})

    def _work(self, jobs, language, code, pip, time_ms, t):
        body = {"language": "python", "pip": pip} if language == "python" else {"language": language}
        while not self.cancelled:
            status, data = self.api.post("/app/install", body, timeout=10)
            state = data.get("state") if status == 200 else "error"
            if state == "ready":
                break
            if state == "installing":
                self.step.emit(t["installing_step"].format(step=data.get("step") or t["installing"]))
                time.sleep(INSTALL_POLL_S)
                continue
            for index, _ in jobs:
                self.result.emit(index, {"status": "env-error", "error": data.get("error") or t["deps_failed"]})
            self._done()
            return
        for n, (index, stdin) in enumerate(jobs):
            if self.cancelled:
                break
            self.step.emit(t["test_running"].format(n=n + 1, total=len(jobs)))
            self.current = f"ide{int(time.time() * 1000)}x{index}"
            status, res = self.api.post("/app/run", {
                "runId": self.current, "language": language, "code": code, "stdin": stdin,
                "timeLimitMs": time_ms, "outputLimitBytes": OUTPUT_LIMIT,
            }, timeout=time_ms / 1000 + 180)  # в запас входит сборка программы на Rust
            if status != 200:
                res = {"status": "env-error", "error": t["run_failed"]}
            if not self.cancelled:
                self.result.emit(index, res)
        self._done()

    def _done(self):
        self.current = None
        self.running = False
        self.finished.emit()


class Field(QPlainTextEdit):
    """Поле ввода или вывода: высота по числу строк, не больше MAX_LINES."""

    def __init__(self, text: str, editable: bool):
        super().__init__(text)
        self.setReadOnly(not editable)
        font = QFont(code_family(), 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabChangesFocus(True)
        self.textChanged.connect(self.fit)
        self.fit()

    def fit(self):
        count = self.toPlainText().rstrip("\n").count("\n") + 1
        lines = max(1, min(MAX_LINES, count))
        policy = Qt.ScrollBarPolicy.ScrollBarAsNeeded if count > MAX_LINES else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        self.setVerticalScrollBarPolicy(policy)
        self.setFixedHeight(QFontMetrics(self.font()).lineSpacing() * lines + 20)


class TestCard(QFrame):
    """Один тест: входные и выходные данные можно править. Цвет карточки говорит, совпал ли ответ."""

    def __init__(self, n: int, test: dict, t: dict, c: dict, on_run, on_edit, on_delete=None, on_reset=None):
        super().__init__()
        self.setObjectName("testCard")
        self.t, self.c = t, c
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(5)

        head = QHBoxLayout()
        head.setSpacing(7)
        name = QLabel(t["test_n"].format(n=n))
        name.setObjectName("testName")
        kind = test.get("kind", "site")
        self.tag = QLabel(t["test_own"] if kind == "own" else "")
        self.tag.setObjectName("testTag")
        self.verdict = QLabel()
        self.verdict.setObjectName("testVerdict")
        self.time = QLabel()
        self.time.setObjectName("testTime")
        head.addWidget(name)
        head.addWidget(self.tag)
        head.addStretch(1)
        head.addWidget(self.verdict)
        head.addWidget(self.time)
        box.addLayout(head)

        self.input = self._field(box, t["test_input"], test.get("in", ""))
        self.expected = self._field(box, t["test_expected"], test.get("out", ""))
        self.input.textChanged.connect(lambda: on_edit("in", self.input.toPlainText()))
        self.expected.textChanged.connect(lambda: on_edit("out", self.expected.toPlainText()))
        self.output_label = QLabel(t["test_output"])
        self.output_label.setObjectName("fieldLabel")
        self.output = Field("", False)
        self.output.setObjectName("outputField")
        self.error = QLabel()
        self.error.setObjectName("testError")
        self.error.setWordWrap(True)
        self.error.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        for w in (self.output_label, self.output, self.error):
            box.addWidget(w)
            w.hide()

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 4, 0, 0)
        actions.setSpacing(6)
        self.run = self._button(t["test_run_btn"], "play", c["fg"], t["test_run_one"], on_run)
        actions.addWidget(self.run)
        self.reset = None
        if on_reset:
            self.reset = self._button(t["test_reset"], "reset", c["mute"], t["test_reset_tip"], on_reset)
            actions.addWidget(self.reset)
            self.mark_edited(kind == "edited")
        actions.addStretch(1)
        if on_delete:
            remove = self._button(t["test_delete_btn"], "close", c["rose"], t["test_delete"], on_delete)
            remove.setProperty("kind", "softDanger")
            actions.addWidget(remove)
        box.addLayout(actions)

    def mark_edited(self, edited: bool):
        """Тест с сайта, который поправили у себя: подпись и кнопка «Как на сайте»."""
        self.tag.setText(self.t["test_edited"] if edited else self.t["test_site"])
        if self.reset:
            self.reset.setVisible(edited)

    @staticmethod
    def _button(text, picture, color, tip, on_click):
        b = button(text, "soft")
        b.setIcon(QIcon(icon(picture, color, 12)))
        b.setToolTip(tip)
        b.clicked.connect(on_click)
        return b

    @staticmethod
    def _field(box, label, text):
        caption = QLabel(label)
        caption.setObjectName("fieldLabel")
        field = Field(text, True)
        box.addWidget(caption)
        box.addWidget(field)
        return field

    def _tone(self, tone: str):
        for w in (self, self.verdict):
            w.setProperty("tone", tone)
            w.style().unpolish(w)
            w.style().polish(w)

    def set_waiting(self):
        self.verdict.setText("…")
        self.verdict.setToolTip("")
        self.time.clear()
        self._tone("")

    def set_result(self, verdict: str, title: str, res: dict):
        """Совпало: зелёная карточка без надписей. Не совпало: жёлтая. Ошибка: красная с причиной."""
        tone = {"OK": "ok", "WA": "wa", "": ""}.get(verdict, "err")
        self.verdict.setText("" if tone in ("ok", "") else title)
        self.verdict.setToolTip(title)
        self.time.setText(self.t["time_ms"].format(ms=res.get("timeMs", 0)) if res.get("status") in ("ok", "re", "tle") else "")
        self._tone(tone)
        self.output.setPlainText(res.get("stdout") or "")
        for w in (self.output_label, self.output):
            w.setVisible(True)
        error = "\n".join(x for x in (res.get("stderr"), res.get("error")) if x).strip()
        self.error.setText(error[:3000])
        self.error.setVisible(bool(error))


class TestsPanel(QScrollArea):
    def __init__(self, on_add):
        super().__init__()
        self.setObjectName("testsPanel")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("testsHost")
        self.box = QVBoxLayout(host)
        self.box.setContentsMargins(10, 10, 10, 12)
        self.box.setSpacing(8)
        self.setWidget(host)
        self.on_add = on_add
        self.cards = []

    def show_tests(self, tests: list, t: dict, c: dict, on_run, on_edit, on_delete, on_reset, hidden=0, on_restore=None):
        """tests: [{'in','out','kind'}], kind = site / edited / own; колбэки получают номер теста в списке."""
        clear_layout(self.box)
        self.cards = []
        for i, test in enumerate(tests):
            kind = test.get("kind", "site")
            card = TestCard(
                i + 1, test, t, c,
                on_run=lambda _=False, i=i: on_run(i),
                on_edit=lambda field, text, i=i: on_edit(i, field, text),
                on_delete=lambda _=False, i=i: on_delete(i),
                on_reset=(lambda _=False, i=i: on_reset(i)) if kind != "own" else None,
            )
            self.cards.append(card)
            self.box.addWidget(card)
        if not tests:
            empty = QLabel(t["tests_empty"])
            empty.setObjectName("muted")
            empty.setWordWrap(True)
            self.box.addWidget(empty)
        add = button(t["test_add"], "soft")
        add.clicked.connect(self.on_add)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(add)
        if hidden and on_restore:
            restore = button(t["tests_restore"].format(n=hidden), "soft")
            restore.setIcon(QIcon(icon("reset", c["mute"], 12)))
            restore.clicked.connect(on_restore)
            row.addWidget(restore)
        row.addStretch(1)
        self.box.addLayout(row)
        self.box.addStretch(1)

    def focus_last_input(self):
        if self.cards:
            self.ensureWidgetVisible(self.cards[-1])
            self.cards[-1].input.setFocus()
