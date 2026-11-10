"""Значки, нарисованные кодом: чёткие на любом экране и в цвете текущей темы."""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient

SCALE = 3  # запас для экранов с большой плотностью


def _canvas(size: int):
    pixmap = QPixmap(size * SCALE, size * SCALE)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(SCALE)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pixmap, painter


def _line(points):
    path = QPainterPath(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(*point)
    return path


def _folder():
    path = QPainterPath()
    path.moveTo(3, 7)
    path.quadTo(3, 5, 5, 5)
    path.lineTo(9, 5)
    path.lineTo(11, 7)
    path.lineTo(19, 7)
    path.quadTo(21, 7, 21, 9)
    path.lineTo(21, 17)
    path.quadTo(21, 19, 19, 19)
    path.lineTo(5, 19)
    path.quadTo(3, 19, 3, 17)
    path.closeSubpath()
    return path


def icon(name: str, color: str, size: int = 14) -> QPixmap:
    pixmap, p = _canvas(size)
    p.scale(size / 24, size / 24)
    pen = QPen(QColor(color), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if name == "down":
        p.drawPath(_line([(6, 9), (12, 15), (18, 9)]))
    elif name == "right":
        p.drawPath(_line([(9, 6), (15, 12), (9, 18)]))
    elif name == "folder":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawPath(_folder())
    elif name == "check":
        p.drawPath(_line([(5, 12.5), (9.5, 17), (19, 7.5)]))
    elif name == "lock":
        pen.setWidthF(2)
        p.setPen(pen)
        p.drawRoundedRect(QRectF(5, 11, 14, 9), 2, 2)
        arc = QPainterPath(QPointF(8, 11))
        arc.lineTo(8, 8)
        arc.arcTo(QRectF(8, 4, 8, 8), 180, -180)
        arc.lineTo(16, 11)
        p.drawPath(arc)
    elif name == "play":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawPath(_line([(7, 4), (21, 12), (7, 20)]))
    elif name == "reset":
        pen.setWidthF(2.2)
        p.setPen(pen)
        p.drawArc(QRectF(4, 4, 16, 16), 150 * 16, -300 * 16)
        p.drawPath(_line([(4, 4), (4, 9), (9, 9)]))
    elif name == "close":
        pen.setWidthF(2.2)
        p.setPen(pen)
        p.drawPath(_line([(7, 7), (17, 17)]))
        p.drawPath(_line([(17, 7), (7, 17)]))
    elif name == "new_file":
        pen.setWidthF(2)
        p.setPen(pen)
        p.drawPath(_line([(13, 3), (6, 3), (6, 21), (18, 21), (18, 8), (13, 3), (13, 8), (18, 8)]))
        p.drawPath(_line([(12, 11), (12, 17)]))
        p.drawPath(_line([(9, 14), (15, 14)]))
    elif name == "open":
        pen.setWidthF(2)
        p.setPen(pen)
        p.drawPath(_line([(3, 18), (3, 6), (9, 6), (11, 8), (19, 8), (19, 11)]))
        p.drawPath(_line([(3, 18), (6, 11), (22, 11), (19, 18), (3, 18)]))
    elif name == "dot":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(5, 5, 14, 14))
    elif name == "ring":
        pen.setWidthF(2.4)
        p.setPen(pen)
        p.drawEllipse(QRectF(6, 6, 12, 12))
    p.end()
    return pixmap


def done_mark(background: str, foreground: str, size: int = 40) -> QPixmap:
    pixmap, p = _canvas(size)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(background))
    p.drawEllipse(QRectF(0, 0, size, size))
    p.translate(size * 0.2, size * 0.2)
    p.scale(size * 0.6 / 24, size * 0.6 / 24)
    p.setPen(QPen(QColor(foreground), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(_line([(5, 12.5), (9.5, 17), (19, 7.5)]))
    p.end()
    return pixmap


def mascot(accent: str, size: int = 20) -> QPixmap:
    """Белый шар сайта в обеих темах; контровой свет снизу справа цвета акцента."""
    pixmap, p = _canvas(size)
    p.scale(size / 64, size / 64)
    glow = QRadialGradient(QPointF(23, 19), 50)
    glow.setColorAt(0, QColor("#ffffff"))
    glow.setColorAt(0.45, QColor("#e6e9ef"))
    glow.setColorAt(1, QColor("#9aa2b1"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(glow)
    p.drawEllipse(QRectF(2, 2, 60, 60))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(accent), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    arc = QPainterPath(QPointF(57.8, 44))
    arc.quadTo(46, 66, 24.6, 59.5)
    p.drawPath(arc)
    p.setPen(Qt.PenStyle.NoPen)
    ink = QColor("#121214")
    p.setBrush(ink)
    p.drawEllipse(QRectF(19.4, 24.4, 7.2, 11.2))
    p.drawEllipse(QRectF(37.4, 24.4, 7.2, 11.2))
    p.drawRoundedRect(QRectF(9.5, 31, 6, 2.4), 1.2, 1.2)
    p.drawRoundedRect(QRectF(48.5, 31, 6, 2.4), 1.2, 1.2)
    p.drawRoundedRect(QRectF(26.5, 39.5, 11, 2.6), 1.3, 1.3)
    p.setBrush(QColor("#ffffff"))
    p.drawEllipse(QPointF(22, 27.6), 1.3, 1.3)
    p.drawEllipse(QPointF(40, 27.6), 1.3, 1.3)
    p.end()
    return pixmap
