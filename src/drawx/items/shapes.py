"""基础图形标注对象：矩形、椭圆、直线、箭头。"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPainterPathStroker, QPolygonF

from .base import AnnoItem, make_brush, make_pen


# ---------------------------------------------------------------- 命中区域
def _stroke_shape(shape_path: QPainterPath, width: float) -> QPainterPath:
    stroker = QPainterPathStroker()
    stroker.setWidth(max(8.0, width + 6.0))
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return stroker.createStroke(shape_path)


def _filled(style: dict) -> bool:
    return QColor(style.get("fill", "#00000000")).alpha() > 0


# ---------------------------------------------------------------- 封闭图形
class ShapeItem(AnnoItem):
    TYPE = "rect"
    LABEL = "矩形"
    CLOSED_SHAPE = True

    def __init__(self, style: dict | None = None) -> None:
        super().__init__(style)
        self._rect = QRectF(0.0, 0.0, 1.0, 1.0)
        self.refresh_origin()

    # -- 几何
    def local_rect(self) -> QRectF:
        return QRectF(self._rect)

    def set_local_rect(self, rect: QRectF) -> None:
        self.prepareGeometryChange()
        self._rect = QRectF(rect)
        self.refresh_origin()

    # -- 绘制
    def _build_path(self, rect: QRectF) -> QPainterPath:
        path = QPainterPath()
        path.addRect(rect)
        return path

    def _draw(self, painter, rect: QRectF) -> None:
        painter.drawRect(rect)

    def paint(self, painter, option, widget=None) -> None:
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        painter.setPen(make_pen(self.style))
        painter.setBrush(make_brush(self.style))
        self._draw(painter, self.local_rect())

    def shape(self) -> QPainterPath:
        rect = self.local_rect()
        path = self._build_path(rect)
        outline = _stroke_shape(path, float(self.style.get("strokeWidth", 4)))
        if _filled(self.style):
            return path.united(outline)
        return outline

    # -- 序列化
    def geometry_dict(self) -> dict:
        return {}

    def apply_geometry(self, geometry: dict, data: dict) -> None:
        width = max(1e-3, float(data.get("w", 1.0)))
        height = max(1e-3, float(data.get("h", 1.0)))
        self._rect = QRectF(0.0, 0.0, width, height)


class EllipseItem(ShapeItem):
    TYPE = "ellipse"
    LABEL = "椭圆"

    def _build_path(self, rect: QRectF) -> QPainterPath:
        path = QPainterPath()
        path.addEllipse(rect)
        return path

    def _draw(self, painter, rect: QRectF) -> None:
        painter.drawEllipse(rect)


class RoundRectItem(ShapeItem):
    TYPE = "roundrect"
    LABEL = "圆角矩形"

    def __init__(self, style: dict | None = None, radius: float = 12.0) -> None:
        super().__init__(style)
        self.radius = float(radius)

    def _build_path(self, rect: QRectF) -> QPainterPath:
        path = QPainterPath()
        radius = min(self.radius, rect.width() / 2.0, rect.height() / 2.0)
        path.addRoundedRect(rect, max(0.0, radius), max(0.0, radius))
        return path

    def _draw(self, painter, rect: QRectF) -> None:
        radius = min(self.radius, rect.width() / 2.0, rect.height() / 2.0)
        painter.drawRoundedRect(rect, max(0.0, radius), max(0.0, radius))

    def geometry_dict(self) -> dict:
        return {"radius": round(self.radius, 3)}

    def apply_geometry(self, geometry: dict, data: dict) -> None:
        self.radius = float(geometry.get("radius", 12.0))
        w = max(1e-3, float(data.get("w", 1.0)))
        h = max(1e-3, float(data.get("h", 1.0)))
        self._rect = QRectF(0.0, 0.0, w, h)


# ---------------------------------------------------------------- 线
def _remap_point(point: QPointF, old: QRectF, new: QRectF) -> QPointF:
    if old.width() > 1e-6:
        x = new.left() + (point.x() - old.left()) / old.width() * new.width()
    else:
        x = new.left()
    if old.height() > 1e-6:
        y = new.top() + (point.y() - old.top()) / old.height() * new.height()
    else:
        y = new.top()
    return QPointF(x, y)


class LineItem(AnnoItem):
    TYPE = "line"
    LABEL = "直线"

    def __init__(self, style: dict | None = None) -> None:
        super().__init__(style)
        self.p1 = QPointF(0.0, 0.0)
        self.p2 = QPointF(40.0, 40.0)
        self.refresh_origin()

    # -- 几何
    def local_rect(self) -> QRectF:
        return QRectF(self.p1, self.p2).normalized()

    def set_local_rect(self, rect: QRectF) -> None:
        old = self.local_rect()
        self.prepareGeometryChange()
        self.p1 = _remap_point(self.p1, old, rect)
        self.p2 = _remap_point(self.p2, old, rect)
        self.refresh_origin()

    def handle_names(self) -> tuple[str, ...]:
        return ("p1", "p2")

    def handle_points(self) -> dict[str, QPointF]:
        return {"p1": QPointF(self.p1), "p2": QPointF(self.p2)}

    def set_endpoint(self, name: str, local_point: QPointF) -> None:
        """拖动端点：只改一个点，另一个点视觉上保持不动。"""
        self.prepareGeometryChange()
        if name == "p1":
            self.p1 = QPointF(local_point)
        else:
            self.p2 = QPointF(local_point)
        # 归一化局部几何到 (0,0) 起点，并补偿位置
        rect = self.local_rect()
        before = self.mapToParent(rect.topLeft())
        self.p1 -= rect.topLeft()
        self.p2 -= rect.topLeft()
        after = self.mapToParent(QPointF(0.0, 0.0))
        self.moveBy(before.x() - after.x(), before.y() - after.y())
        self.refresh_origin()

    # -- 绘制
    def _points(self) -> tuple[QPointF, QPointF]:
        return self.p1, self.p2

    def paint(self, painter, option, widget=None) -> None:
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        pen = make_pen(self.style)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        p1, p2 = self._points()
        painter.drawLine(p1, p2)

    def shape(self) -> QPainterPath:
        p1, p2 = self._points()
        path = QPainterPath(p1)
        path.lineTo(p2)
        return _stroke_shape(path, float(self.style.get("strokeWidth", 4)))

    # -- 序列化
    def geometry_dict(self) -> dict:
        return {
            "p1": [round(self.p1.x(), 3), round(self.p1.y(), 3)],
            "p2": [round(self.p2.x(), 3), round(self.p2.y(), 3)],
        }

    def apply_geometry(self, geometry: dict, data: dict) -> None:
        p1 = geometry.get("p1", [0.0, 0.0])
        p2 = geometry.get("p2", [data.get("w", 1.0), data.get("h", 1.0)])
        self.p1 = QPointF(float(p1[0]), float(p1[1]))
        self.p2 = QPointF(float(p2[0]), float(p2[1]))


class ArrowItem(LineItem):
    TYPE = "arrow"
    LABEL = "箭头"

    def __init__(self, style: dict | None = None) -> None:
        super().__init__(style)
        self.head = "end"  # none | start | end | both

    @staticmethod
    def _head_length(length: float, width: float) -> float:
        """箭头长度：跟着线宽走，线太短时按比例收，免得箭头比线还长。"""
        size = max(10.0, width * 3.4)
        return max(4.0, min(size, length * 0.45))

    def _draw_head(self, painter, tip: QPointF, tail: QPointF, size: float, width: float) -> None:
        dx = tip.x() - tail.x()
        dy = tip.y() - tail.y()
        if math.hypot(dx, dy) < 1e-6:
            return
        angle = math.atan2(dy, dx)
        spread = math.radians(26.0)
        left = QPointF(
            tip.x() - size * math.cos(angle - spread),
            tip.y() - size * math.sin(angle - spread),
        )
        right = QPointF(
            tip.x() - size * math.cos(angle + spread),
            tip.y() - size * math.sin(angle + spread),
        )
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(make_pen(self.style).color())
        painter.drawPolygon(QPolygonF([tip, left, right]))
        painter.restore()

    def paint(self, painter, option, widget=None) -> None:
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        pen = make_pen(self.style)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        p1, p2 = self._points()
        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return
        ux, uy = dx / length, dy / length
        width = pen.widthF()
        size = self._head_length(length, width)

        # 关键：线杆止于箭头底部，而不是一路画到尖端。
        # 否则线条的圆头端帽会超出尖端 width/2，尖端就会鼓出一小块、发糊。
        shaft_start = QPointF(p1)
        shaft_end = QPointF(p2)
        inset = size * 0.86
        if self.head in ("end", "both"):
            shaft_end = QPointF(p2.x() - ux * inset, p2.y() - uy * inset)
        if self.head in ("start", "both"):
            shaft_start = QPointF(p1.x() + ux * inset, p1.y() + uy * inset)
        if math.hypot(shaft_end.x() - shaft_start.x(), shaft_end.y() - shaft_start.y()) > 1e-6:
            painter.drawLine(shaft_start, shaft_end)

        if self.head in ("end", "both"):
            self._draw_head(painter, p2, p1, size, width)
        if self.head in ("start", "both"):
            self._draw_head(painter, p1, p2, size, width)

    def geometry_dict(self) -> dict:
        data = super().geometry_dict()
        data["head"] = self.head
        return data

    def apply_geometry(self, geometry: dict, data: dict) -> None:
        super().apply_geometry(geometry, data)
        self.head = geometry.get("head", "end")
