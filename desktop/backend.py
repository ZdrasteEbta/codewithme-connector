"""Связь приложения с невидимым помощником: запуск кода и обмен с сайтом."""
import http.client
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import deque
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

HELPER = "codewithme-helper.exe" if os.name == "nt" else "codewithme-helper"


def helper_path() -> Path:
    env = os.environ.get("CWM_HELPER")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / HELPER
    return Path(__file__).resolve().parent.parent / HELPER


class Helper:
    """Запускает помощника и читает его вывод, пока он работает."""

    def __init__(self, folder: str, dev: bool = False):
        args = [str(helper_path()), "--desktop", "--folder", folder]
        if dev:
            args.append("--dev")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        self.port = 0
        self.last_lines: deque[str] = deque(maxlen=20)
        self._ready = threading.Event()
        self.started = time.monotonic()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for raw in self.proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            self.last_lines.append(line)
            if line.startswith("CWM_PORT="):
                self.port = int(line.split("=", 1)[1])
                self._ready.set()
        self._ready.set()  # помощник завершился: ждать больше нечего

    def timed_out(self, limit: float = 20) -> bool:
        return time.monotonic() - self.started > limit

    def wait_ready(self, timeout: float = 20) -> bool:
        self._ready.wait(timeout)
        return self.port > 0

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class Api:
    """Запросы к помощнику. Соединение держится открытым: новое на Windows стоит около 15 мс,
    а повторное меньше миллисекунды. У каждого потока своё соединение."""

    def __init__(self, port: int):
        self.port = port
        self.origin = f"http://127.0.0.1:{port}"
        self.local = threading.local()

    def get(self, path: str, timeout: float = 5):
        return self._send("GET", path, None, {}, timeout)

    def post(self, path: str, body: dict, timeout: float = 5):
        headers = {"Content-Type": "application/json", "Origin": self.origin}
        return self._send("POST", path, json.dumps(body).encode("utf-8"), headers, timeout)

    def _drop(self) -> None:
        conn = getattr(self.local, "conn", None)
        if conn is not None:
            conn.close()
        self.local.conn = None

    def _send(self, method, path, body, headers, timeout):
        for attempt in (0, 1):
            conn = getattr(self.local, "conn", None)
            if conn is None:
                conn = self.local.conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
            conn.timeout = timeout
            if conn.sock is not None:
                conn.sock.settimeout(timeout)
            try:
                conn.request(method, path, body=body, headers=headers)
                res = conn.getresponse()
                data = res.read()
                if res.will_close:
                    self._drop()
            except (http.client.RemoteDisconnected, ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                self._drop()  # помощник закрыл старое соединение: пробуем один раз на новом
                if attempt:
                    return 0, {}
                continue
            except (OSError, http.client.HTTPException):
                self._drop()
                return 0, {}
            try:
                return res.status, json.loads(data or b"{}")
            except ValueError:
                return res.status, {}
        return 0, {}

    def file(self, key: str):
        return self.get("/app/file?key=" + urllib.parse.quote(key, safe=""))

    def write(self, key: str, content: str, base: str):
        return self.post("/app/file", {"key": key, "content": content, "base": base})

    def command(self, kind: str, **extra):
        return self.post("/app/cmd", {"type": kind, **extra})


class StatePoller(QThread):
    """Длинный опрос состояния. Пока он идёт, помощник знает, что приложение живо."""

    changed = pyqtSignal(dict)

    def __init__(self, api: Api, parent=None):
        super().__init__(parent)
        self.api = api
        self.running = True

    def run(self) -> None:
        seq = None
        while self.running:
            path = "/app/state" if seq is None else f"/app/state?since={seq}"
            code, data = self.api.get(path, timeout=15)
            if not self.running:
                return
            if code == 200:
                if data.get("seq") != seq:
                    seq = data.get("seq")
                    self.changed.emit(data)
            else:
                self.msleep(1000)

    def stop(self) -> None:
        """Вызывать после остановки помощника: тогда висящий запрос обрывается сразу."""
        self.running = False
        self.wait(3000)
