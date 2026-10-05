"""应用图标：用 QPainter 现画，零资源文件。

一份绘制代码同时供三处使用，保证完全一致：
* exe 的文件图标（packaging/make_icon.py 调它生成 .ico）
* 窗口标题栏左上角与任务栏（QApplication.setWindowIcon）

Windows 任务栏取的是 32/16 像素的小图，Alt+Tab 取大图，所以 QIcon 必须
把多个尺寸都塞进去，不能只放一张 256 再让系统去缩。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)

#: QIcon 里预置的尺寸
ICON_SIZES = (16, 20, 24, 32, 48, 64, 128, 256)

_icon_cache: QIcon | None = None


def draw_app_icon(size: int) -> QImage:
    """画一张 size×size 的应用图标（圆角蓝底 + 相框 + 红色标注箭头）。"""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    s = float(size)

    # 圆角渐变底
    background = QLinearGradient(0.0, 0.0, s, s)
    background.setColorAt(0.0, QColor("#3a6fd8"))
    background.setColorAt(1.0, QColor("#1f3f8f"))
    path = QPainterPath()
    path.addRoundedRect(
        QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92), s * 0.20, s * 0.20
    )
    painter.fillPath(path, QBrush(background))

    # 小尺寸下相框线条会糊成一团，直接省掉，只留箭头才看得清
    if size >= 32:
        painter.setPen(QPen(QColor(255, 255, 255, 235), max(1.0, s * 0.055)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(
            QRectF(s * 0.20, s * 0.24, s * 0.60, s * 0.52), s * 0.06, s * 0.06
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawEllipse(QRectF(s * 0.30, s * 0.34, s * 0.13, s * 0.13))

    # 红色标注箭头
    line_width = s * (0.10 if size >= 32 else 0.15)
    pen = QPen(QColor("#ff3b30"), line_width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(s * 0.30, s * 0.80), QPointF(s * 0.76, s * 0.32))

    head = s * (0.30 if size >= 32 else 0.34)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ff3b30"))
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(s * 0.88, s * 0.20),
                QPointF(s * 0.88 - head * 0.95, s * 0.20 + head * 0.28),
                QPointF(s * 0.88 - head * 0.28, s * 0.20 + head * 0.95),
            ]
        )
    )
    painter.end()
    return image


def app_icon() -> QIcon:
    """全局共用的多尺寸 QIcon（需要先有 QApplication）。"""
    global _icon_cache
    if _icon_cache is None:
        icon = QIcon()
        for size in ICON_SIZES:
            icon.addPixmap(QPixmap.fromImage(draw_app_icon(size)))
        _icon_cache = icon
    return _icon_cache
