"""自定义样式：把 Fusion 那几个又小又黑的箭头换成清爽的浅色雪佛龙。

Qt 的 QSS 没法直接给下拉箭头/微调箭头指定图形（除非带外部图片文件），
但可以通过 QProxyStyle 拦下 `PE_IndicatorArrowDown` 这类绘制原语自己画 ——
既保持零资源文件，又能让箭头跟深色主题协调。
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QProxyStyle, QStyle

ARROW_ON = "#c8c8d2"
ARROW_OFF = "#6b6b74"

_CHEVRON_ELEMENTS = {
    QStyle.PrimitiveElement.PE_IndicatorArrowDown: False,
    QStyle.PrimitiveElement.PE_IndicatorArrowUp: True,
    QStyle.PrimitiveElement.PE_IndicatorSpinDown: False,
    QStyle.PrimitiveElement.PE_IndicatorSpinUp: True,
}


class DarkStyle(QProxyStyle):
    def __init__(self, base: str = "Fusion") -> None:
        super().__init__(base)

    def drawPrimitive(self, element, option, painter, widget=None) -> None:  # noqa: N802
        if element in _CHEVRON_ELEMENTS:
            enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
            self._draw_chevron(painter, option.rect, _CHEVRON_ELEMENTS[element], enabled)
            return
        super().drawPrimitive(element, option, painter, widget)

    @staticmethod
    def _draw_chevron(painter: QPainter, rect: QRectF, up: bool, enabled: bool) -> None:
        color = QColor(ARROW_ON if enabled else ARROW_OFF)
        pen = QPen(color, 1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        width = min(9.0, max(6.0, rect.width() * 0.7))
        height = width * 0.55
        cx = rect.center().x() + 0.5
        cy = rect.center().y() + 0.5

        path = QPainterPath()
        if up:
            path.moveTo(cx - width / 2.0, cy + height / 2.0)
            path.lineTo(cx, cy - height / 2.0)
            path.lineTo(cx + width / 2.0, cy + height / 2.0)
        else:
            path.moveTo(cx - width / 2.0, cy - height / 2.0)
            path.lineTo(cx, cy + height / 2.0)
            path.lineTo(cx + width / 2.0, cy - height / 2.0)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.restore()
