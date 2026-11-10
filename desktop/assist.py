"""Помощь при вводе: красная линия, подсказка параметров и установка библиотек."""
import html
import threading
import time

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from checks import PythonSignatures, check, family_of
from hints import call_at, local_signature, render_signature, signature_from_jedi
from panels import ClickLabel, button
from theme import code_family

CHECK_DELAY = {"python": 350, "js": 700, "rust": 900}
TIP_DELAY = 70
ENV_TTL = 2.0
RECHECK_MISSING_MS = 5000
INSTALL_POLL_MS = 900


class LatestWorker(QObject):
    """Поток, который выполняет только самый свежий запрос. Устаревшие запросы отбрасываются."""

    done = pyqtSignal(int, object)

    def __init__(self, work, parent=None):
        super().__init__(parent)
        self.work = work
        self.wake = threading.Condition()
        self.pending = None
        self.closed = False
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, seq: int, *args) -> None:
        with self.wake:
            self.pending = (seq, args)
            self.wake.notify()

    def _loop(self) -> None:
        while True:
            with self.wake:
                while self.pending is None and not self.closed:
                    self.wake.wait()
                if self.closed:
                    return
                seq, args = self.pending
                self.pending = None
            result = self.work(*args)
            if not self.closed:
                self.done.emit(seq, result)

    def close(self) -> None:
        with self.wake:
            self.closed = True
            self.wake.notify()


class AssistBar(QFrame):
    """Полоса под редактором: первая ошибка и кнопка установки библиотек."""

    def __init__(self, on_problem, on_install):
        super().__init__()
        self.setObjectName("assistBar")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.problem_row = QFrame()
        self.problem_row.setObjectName("problemRow")
        ph = QHBoxLayout(self.problem_row)
        ph.setContentsMargins(18, 5, 14, 5)
        ph.setSpacing(10)
        self.problem = ClickLabel("", on_problem)
        self.problem.setObjectName("problemText")
        self.problem.setWordWrap(True)
        self.problem.setTextFormat(Qt.TextFormat.RichText)
        self.more = QLabel()
        self.more.setObjectName("muted")
        ph.addWidget(self.problem, 1)
        ph.addWidget(self.more)
        root.addWidget(self.problem_row)

        self.deps_row = QFrame()
        self.deps_row.setObjectName("depsRow")
        dh = QHBoxLayout(self.deps_row)
        dh.setContentsMargins(18, 6, 14, 6)
        dh.setSpacing(10)
        self.deps = QLabel()
        self.deps.setObjectName("depsText")
        self.deps.setWordWrap(True)
        self.install_btn = button(kind="primary")
        self.install_btn.clicked.connect(on_install)
        dh.addWidget(self.deps, 1)
        dh.addWidget(self.install_btn)
        root.addWidget(self.deps_row)
        self.deps_row.hide()
        self.problem_row.hide()


class Assistant(QObject):
    def __init__(self, api, editor, parent=None):
        super().__init__(parent)
        self.api, self.editor = api, editor
        self.t, self.locale = None, "ru"
        self.language, self.task_folder, self.folder = "", None, None
        self.env, self.env_at = None, 0.0
        self.report = None
        self.check_seq = self.sig_seq = 0
        self.tip_key = self.tip_sig = None
        self.installing = None
        self.install_error = ""
        self.signatures = PythonSignatures()
        self.bar = AssistBar(self.jump_to_problem, self.install)

        self.check_worker = LatestWorker(self._work_check, self)
        self.sig_worker = LatestWorker(self._work_signature, self)
        self.check_worker.done.connect(self._checked)
        self.sig_worker.done.connect(self._signature)

        self.check_timer = QTimer(self, singleShot=True, timeout=self.run_check)
        self.tip_timer = QTimer(self, singleShot=True, interval=TIP_DELAY, timeout=self.update_tip)
        self.recheck_timer = QTimer(self, interval=RECHECK_MISSING_MS, timeout=self._recheck_missing)
        self.install_timer = QTimer(self, interval=INSTALL_POLL_MS, timeout=self._poll_install)
        self.recheck_timer.start()

        editor.textChanged.connect(self.schedule)
        editor.textChanged.connect(self.tip_timer.start)
        editor.position_changed.connect(self._cursor_moved)

    # --- настройка ---

    def retitle(self, t: dict, locale: str) -> None:
        self.t, self.locale = t, locale
        self.render()
        self.schedule()

    def task_changed(self, language: str, task_folder: str | None, folder: str | None) -> None:
        self.language, self.task_folder, self.folder = language, task_folder, folder
        self.install_error = ""
        self.tip_key = None
        self.editor.hide_call_tip()
        self.check_timer.stop()
        self.run_check()

    def close(self) -> None:
        self.check_worker.close()
        self.sig_worker.close()

    # --- проверка ---

    def schedule(self) -> None:
        if self.language:
            self.check_timer.start(CHECK_DELAY.get(family_of(self.language), 500))

    def run_check(self) -> None:
        if not self.language or not self.t:
            return
        self.check_seq += 1
        self.check_worker.submit(self.check_seq, self.editor.text(), self.language, self.locale, self.task_folder)

    def _fresh_env(self):
        if time.monotonic() - self.env_at > ENV_TTL:
            code, data = self.api.get("/app/env")
            if code == 200:
                self.env, self.env_at = data, time.monotonic()
        return self.env

    def _work_check(self, code, language, locale, task_folder):
        return check(code, language, locale, self._fresh_env(), task_folder)

    def _checked(self, seq: int, report) -> None:
        if seq != self.check_seq:
            return
        self.report = report
        self.editor.set_problems(report.problems)
        self.render()

    def _recheck_missing(self) -> None:
        """Библиотеку мог поставить и сайт при запуске задачи."""
        if self.report and self.report.missing and not self.installing:
            self.run_check()

    # --- полоса под редактором ---

    def _current_problem(self):
        problems = self.report.problems if self.report else []
        if not problems:
            return None
        line = self.editor.getCursorPosition()[0]
        return next((p for p in problems if p.line == line), problems[0])

    def render(self) -> None:
        if not self.t:
            return
        report, t, bar = self.report, self.t, self.bar
        checked = bool(report and report.checked and self.language)
        bar.problem_row.setVisible(checked)
        problem = self._current_problem() if checked else None
        if bar.problem_row.property("bad") != bool(problem):
            bar.problem_row.setProperty("bad", bool(problem))
            for widget in (bar.problem_row, bar.problem):  # свойство поменялось: стиль надо применить заново
                widget.style().unpolish(widget)
                widget.style().polish(widget)
        if checked and not problem:
            bar.problem.setText(html.escape(t["no_problems"]))
            bar.more.clear()
        elif problem:
            text = f'<b>{html.escape(t["problem_line"].format(n=problem.line + 1))}</b> &nbsp;{html.escape(problem.message)}'
            if problem.example:
                text += f' &nbsp;{html.escape(t["should_be"])} <span style="font-family:\'{code_family()}\';">{html.escape(problem.example)}</span>'
            bar.problem.setText(text)
            others = len(report.problems) - 1
            bar.more.setText(t["more_problems"].format(n=others) if others else "")

        missing = report.missing if report else []
        bar.deps_row.setVisible(bool(missing) or bool(self.installing) or bool(self.install_error))
        if self.installing:
            bar.install_btn.setEnabled(False)
            bar.install_btn.setText(t["installing"])
        else:
            bar.install_btn.setEnabled(bool(missing))
            bar.install_btn.setText(t["deps_install"])
            bar.install_btn.setVisible(bool(missing))
            names = ", ".join(m.name for m in missing)
            bar.deps.setText(self.install_error or t["deps_missing"].format(names=names))

    def jump_to_problem(self) -> None:
        problem = self._current_problem()
        if problem:
            self.editor.go_to_problem(problem)

    # --- подсказка параметров ---

    def _cursor_moved(self, *_):
        self.tip_timer.start()
        if self.report and self.report.problems:
            self.render()

    def update_tip(self) -> None:
        family = family_of(self.language) if self.language else "html"
        if family == "html":
            self.editor.hide_call_tip()
            return
        text = self.editor.text()
        line, col = self.editor.getCursorPosition()
        rows = text.split("\n")
        offset = sum(len(r) + 1 for r in rows[:line]) + col
        call = call_at(text, offset, family)
        if not call:
            self.tip_key = self.tip_sig = None
            self.editor.hide_call_tip()
            return
        key = (call.name, call.open)
        if key != self.tip_key:
            self.tip_key, self.tip_sig = key, local_signature(family, call, text, self.locale)
            if self.tip_sig is None:
                self.editor.hide_call_tip()
                if family == "python":
                    self.sig_seq += 1
                    self.sig_worker.submit(self.sig_seq, text, line + 1, col)
        self.call = call
        self._show_tip()

    def _show_tip(self) -> None:
        if self.tip_sig:
            text, start, stop = render_signature(self.tip_sig[0], self.tip_sig[1], self.call)
            self.editor.show_call_tip(self.call.open, text, start, stop)

    def _work_signature(self, code, line, col):
        return self.signatures.lookup(code, line, col, self._fresh_env(), self.task_folder or self.folder)

    def _signature(self, seq: int, found) -> None:
        if seq == self.sig_seq and found and self.tip_key:
            self.tip_sig = signature_from_jedi(found, self.locale)
            self._show_tip()

    # --- установка библиотек ---

    def install(self) -> None:
        missing = self.report.missing if self.report else []
        if not missing or self.installing:
            return
        pip = [m.package for m in missing if m.kind == "pip"]
        npm = [m.package for m in missing if m.kind == "npm"]
        self.installing = {"language": "python", "pip": pip} if pip else {"language": "node", "npm": npm}
        self.install_error = ""
        self.render()
        self._poll_install(fresh=True)
        if self.installing:
            self.install_timer.start()

    def _poll_install(self, fresh: bool = False) -> None:
        if not self.installing:
            return
        code, data = self.api.post("/app/install", {**self.installing, "fresh": fresh})
        state = data.get("state") if code == 200 else "error"
        if state == "installing":
            self.bar.deps.setText(data.get("step") or self.t["installing"])
            return
        self.install_timer.stop()
        self.installing = None
        self.install_error = self.t["deps_failed"] if state != "ready" else ""
        self.env_at = 0.0
        self.signatures.reset()
        self.tip_key = None
        self.render()
        self.run_check()
