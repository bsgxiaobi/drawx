"""自由笔画与高亮笔。"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainterPath, QPen

from .base import AnnoItem, make_pen
from .shapes import _stroke_shape


class FreehandItem(AnnoItem):
    TYPE = "freehand"
    LABEL = "画笔"

    def __init__(self, style: dict | None = None) -> None:
        super().__init__(style)
        self.points: list[QPointF] = [QPointF(0.0, 0.0), QPointF(1.0, 1.0)]
        self.refresh_origin()

    # ---------------------------------------------------------- 几何
    def _bbox(self) -> QRectF:
        if not self.points:
            return QRectF(0.0, 0.0, 1.0, 1.0)
        xs = [p.x() for p in self.points]
        ys = [p.y() for p in self.points]
        return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def local_rect(self) -> QRectF:
        rect = self._bbox()
        # 退化成一条水平/垂直线时给一点厚度，控制点才抓得住
        if rect.width() < 1.0:
            rect.adjust(-0.5, 0.0, 0.5, 0.0)
        if rect.height() < 1.0:
            rect.adjust(0.0, -0.5, 0.0, 0.5)
        return rect

    def set_local_rect(self, rect: QRectF) -> None:
        old = self._bbox()
        self.prepareGeometryChange()
        self.points = [_remap(p, old, rect) for p in self.points]
        self.refresh_origin()

    def set_scene_points(self, scene_points: list[QPointF]) -> None:
        """直接把场景坐标点集写成对象几何（绘制过程中实时预览用）。"""
        if not scene_points:
            return
        xs = [p.x() for p in scene_points]
        ys = [p.y() for p in scene_points]
        ox, oy = min(xs), min(ys)
        self.prepareGeometryChange()
        self.points = [QPointF(p.x() - ox, p.y() - oy) for p in scene_points]
        self.setPos(ox, oy)
        self.refresh_origin()

    @classmethod
    def from_scene_points(cls, scene_points: list[QPointF], style: dict | None = None):
        """用场景坐标点集创建对象：局部点集以包围盒左上角为原点。"""
        item = cls(style)
        item.set_scene_points(scene_points)
        return item

    # ---------------------------------------------------------- 绘制
    def _path(self) -> QPainterPath:
        pts = self.points
        path = QPainterPath()
        if not pts:
            return path
        if len(pts) == 1:
            path.addEllipse(pts[0], 0.6, 0.6)
            return path
        path.moveTo(pts[0])
        if len(pts) == 2:
            path.lineTo(pts[1])
            return path
        # 用相邻点中点 + 二次贝塞尔做平滑，避免折线锯齿
        for i in range(1, len(pts) - 1):
            mid = QPointF(
                (pts[i].x() + pts[i + 1].x()) / 2.0,
                (pts[i].y() + pts[i + 1].y()) / 2.0,
            )
            path.quadTo(pts[i], mid)
        path.lineTo(pts[-1])
        return path

    def _pen(self) -> QPen:
        pen = make_pen(self.style)
        if len(self.points) <= 2:
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        return pen

    def paint(self, painter, option, widget=None) -> None:
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        pen = self._pen()
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path = self._path()
        if len(self.points) == 1:
            painter.setBrush(pen.color())
            painter.drawEllipse(path.boundingRect())
        else:
            painter.drawPath(path)

    def shape(self) -> QPainterPath:
        return _stroke_shape(self._path(), float(self.style.get("strokeWidth", 4)))

    # ---------------------------------------------------------- 序列化
    def geometry_dict(self) -> dict:
        return {
            "points": [
                [round(p.x(), 2), round(p.y(), 2)] for p in self.points
            ]
        }

    def apply_geometry(self, geometry: dict, data: dict) -> None:
        pts = geometry.get("points") or [[0.0, 0.0], [1.0, 1.0]]
        self.points = [QPointF(float(p[0]), float(p[1])) for p in pts]


class HighlightItem(FreehandItem):
    """高亮笔：半透明粗线，压在文字上仍能看清内容。"""

    TYPE = "highlight"
    LABEL = "高亮"

    def __init__(self, style: dict | None = None) -> None:
        merged = {
            "stroke": "#FFD60A",
            "strokeWidth": 18,
            "strokeStyle": "solid",
            "fill": "#00000000",
            "opacity": 0.38,
        }
        merged.update(style or {})
        super().__init__(merged)
        self.refresh_origin()


def _remap(point: QPointF, old: QRectF, new: QRectF) -> QPointF:
    if old.width() > 1e-6:
        x = new.left() + (point.x() - old.left()) / old.width() * new.width()
    else:
        x = new.left()
    if old.height() > 1e-6:
        y = new.top() + (point.y() - old.top()) / old.height() * new.height()
    else:
        y = new.top()
    return QPointF(x, y)
