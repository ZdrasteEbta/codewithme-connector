"""Заставка при запуске, как в PyCharm: маскот прыгает, пока готовится окно."""
import math
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QApplication, QWidget

W, H = 340, 250
BALL = 64


class Splash(QWidget):
    def __init__(self, c: dict, title: str, text: str, ui_family: str, logo_family: str):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.SplashScreen
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(W, H)
        self.c, self.title, self.text = c, title, text
        self.ui, self.logo = ui_family, logo_family
        self.started = time.perf_counter()
        self.timer = QTimer(self, interval=16, timeout=self.update)
        self.timer.start()
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - W // 2, screen.center().y() - H // 2)

    def pump(self):
        """Окно строится в том же потоке: между шагами даём заставке перерисоваться."""
        QApplication.processEvents()

    def paintEvent(self, _):
        c = self.c
        t = time.perf_counter() - self.started
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(c["line"]), 1))
        p.setBrush(QColor(c["panel"]))
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 18, 18)

        # Прыжок: высота по синусу, у земли шар сплющивается, в воздухе вытягивается
        period = 0.9
        phase = (t % period) / period
        lift = abs(math.sin(phase * math.pi))
        ground = 128
        y = ground - lift * 58
        squash = max(0.0, 1 - lift * 4) if lift < 0.25 else 0.0
        sx = 1 + 0.22 * squash - 0.06 * lift
        sy = 1 - 0.22 * squash + 0.08 * lift
        # Тень на земле: меньше и бледнее, когда шар высоко
        shadow = QColor(0, 0, 0, int(110 - 70 * lift))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(shadow)
        sw = 46 - 18 * lift
        p.drawEllipse(QPointF(W / 2, ground + BALL / 2 + 4), sw / 2, 4.5 - 2 * lift)

        p.save()
        p.translate(W / 2, y + BALL / 2)  # низ шара
        p.rotate(math.sin(phase * 2 * math.pi) * 6)
        p.scale(sx, sy)
        p.translate(-BALL / 2, -BALL)
        self.ball(p, t)
        p.restore()

        p.setPen(QColor(c["fg"]))
        p.setFont(QFont(self.logo, 15, QFont.Weight.Bold))
        p.drawText(QRectF(0, 178, W, 26), Qt.AlignmentFlag.AlignCenter, self.title)
        dots = "." * (int(t * 3) % 4)
        p.setPen(QColor(c["mute"]))
        p.setFont(QFont(self.ui, 10))
        p.drawText(QRectF(0, 206, W, 20), Qt.AlignmentFlag.AlignCenter, self.text + dots)
        p.end()

    def ball(self, p: QPainter, t: float):
        """Белый шар-маскот в масштабе 64: глаза смотрят по сторонам и моргают."""
        glow = QRadialGradient(QPointF(23, 19), 50)
        glow.setColorAt(0, QColor("#ffffff"))
        glow.setColorAt(0.45, QColor("#e6e9ef"))
        glow.setColorAt(1, QColor("#9aa2b1"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QRectF(2, 2, 60, 60))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(self.c["lime"]), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        arc = QPainterPath(QPointF(57.8, 44))
        arc.quadTo(46, 66, 24.6, 59.5)
        p.drawPath(arc)
        look = math.sin(t * 1.7) * 3
        blink = (t % 2.6) > 2.45
        eye_h = 1.6 if blink else 11.2
        ink = QColor("#121214")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink)
        for x in (19.4, 37.4):
            p.drawEllipse(QRectF(x + look, 30 - eye_h / 2, 7.2, eye_h))
        p.drawRoundedRect(QRectF(9.5, 31, 6, 2.4), 1.2, 1.2)
        p.drawRoundedRect(QRectF(48.5, 31, 6, 2.4), 1.2, 1.2)
        # Рот: улыбка, которая то шире, то уже
        smile = 2 + 2 * abs(math.sin(t * 2.2))
        p.setPen(QPen(ink, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        mouth = QPainterPath(QPointF(27, 40))
        mouth.quadTo(32, 40 + smile, 37, 40)
        p.drawPath(mouth)
        if not blink:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(QPointF(22 + look, 27.6), 1.3, 1.3)
            p.drawEllipse(QPointF(40 + look, 27.6), 1.3, 1.3)
