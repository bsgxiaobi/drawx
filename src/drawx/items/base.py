"""标注对象基类。

三条契约，所有标注对象都必须满足：

1. **局部几何契约**：``local_rect()`` 返回对象在自身局部坐标系里占据的矩形；
   ``set_local_rect(r)`` 表示"让几何正好占据当前局部坐标系里的矩形 r"（可以带偏移，
   调用方负责用 :func:`set_local_rect_keep_anchor` 把位置修正回去）。对象原点
   ``pos()`` 始终是局部坐标 (0,0) 在父坐标中的位置，旋转绕 ``transformOriginPoint``。
2. **序列化契约**：``to_dict()`` / ``apply_dict()`` 必须无损往返，撤销栈完全建立在这上面。
3. **绘制契约**：``paint()`` 只画内容。选中框、控制点、参考线一律由视图的
   ``drawForeground()`` 绘制 —— 这样导出时天然不会带上编辑态装饰。
"""

from __future__ import annotations

import uuid

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject


# ------------------------------------------------------------------ 工具函数
def new_id() -> str:
    return uuid.uuid4().hex[:12]


DEFAULT_STYLE: dict = {
    "stroke": "#FF3B30",
    "strokeWidth": 4,
    "strokeStyle": "solid",  # solid | dash | dot
    "fill": "#00000000",  # 全透明 = 无填充
    "opacity": 1.0,
}

TEXT_STYLE_KEYS = {
    "fontFamily": "Microsoft YaHei",
    "fontSize": 20,
    "bold": False,
    "italic": False,
    "bgFill": "#00000000",
}

HANDLE_NAMES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")

# 手柄 -> 缩放时应保持不动的对角/对边锚点（局部坐标，按给定矩形计算）
_ANCHOR_EDGES = {
    "nw": ("right", "bottom"),
    "n": ("center_x", "bottom"),
    "ne": ("left", "bottom"),
    "e": ("left", "center_y"),
    "se": ("left", "top"),
    "s": ("center_x", "top"),
    "sw": ("right", "top"),
    "w": ("right", "center_y"),
}


def make_pen(style: dict, scale: float = 1.0) -> QPen:
    pen = QPen(QColor(style.get("stroke", "#FF3B30")))
    pen.setWidthF(max(0.05, float(style.get("strokeWidth", 4)) * scale))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    stroke_style = style.get("strokeStyle", "solid")
    if stroke_style == "dash":
        pen.setDashPattern([3.0, 2.0])
    elif stroke_style == "dot":
        pen.setDashPattern([0.5, 1.6])
    return pen


def make_brush(style: dict) -> QBrush:
    color = QColor(style.get("fill", "#00000000"))
    if color.alpha() == 0:
        return QBrush(Qt.BrushStyle.NoBrush)
    return QBrush(color)


def anchor_point(rect: QRectF, handle: str) -> QPointF:
    """给定矩形与正在拖动的控制点，返回该矩形上应保持不动的点。"""
    ex, ey = _ANCHOR_EDGES.get(handle, ("left", "top"))
    x = {
        "left": rect.left(),
        "right": rect.right(),
        "center_x": rect.center().x(),
    }[ex]
    y = {
        "top": rect.top(),
        "bottom": rect.bottom(),
        "center_y": rect.center().y(),
    }[ey]
    return QPointF(x, y)


# ------------------------------------------------------------------ 混入
class AnnoMixin:
    """与 QGraphicsObject / QGraphicsTextItem 都能组合的标注对象混入。"""

    TYPE = "base"
    LABEL = "标注"
    #: 封闭图形（矩形/椭圆/文字/马赛克…）：未填充时也允许点内部选中。
    #: 线条、自由笔画为 False，只按描边命中，避免斜线把整个包围盒都吃掉。
    CLOSED_SHAPE = False

    # ---------------------------------------------------------- 初始化
    def _anno_init(self, style: dict | None = None) -> None:
        self.id: str = new_id()
        self.style: dict = dict(DEFAULT_STYLE)
        self.style.update(style or {})
        #: 所属图层的不透明度系数。对象自身的不透明度是 0~100 的滑块，图层是另一个
        #: 0~1 的乘数，必须分开存：否则改图层不透明度会把对象自己的值冲掉。
        self._layer_opacity: float = 1.0
        #: 对象自己的显隐（与图层显隐相乘才是最终可见性）
        self._own_visible: bool = True
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.apply_style()

    # ---------------------------------------------------------- 样式
    def apply_style(self) -> None:
        opacity = float(self.style.get("opacity", 1.0)) * float(
            getattr(self, "_layer_opacity", 1.0)
        )
        self.setOpacity(max(0.0, min(1.0, opacity)))
        self.update()

    def set_layer_opacity(self, value: float) -> None:
        self._layer_opacity = max(0.0, min(1.0, float(value)))
        self.apply_style()

    def set_style_value(self, key: str, value) -> None:
        self.style[key] = value
        self.apply_style()
        if key in ("strokeWidth", "strokeStyle"):
            self.prepareGeometryChange()
            self.refresh_origin()

    # ---------------------------------------------------------- 几何契约
    def local_rect(self) -> QRectF:  # pragma: no cover - 由子类实现
        raise NotImplementedError

    def set_local_rect(self, rect: QRectF) -> None:  # pragma: no cover
        raise NotImplementedError

    def content_margin(self) -> float:
        return float(self.style.get("strokeWidth", 4)) / 2.0 + 2.0

    def boundingRect(self) -> QRectF:
        m = self.content_margin()
        return self.local_rect().adjusted(-m, -m, m, m)

    def refresh_origin(self) -> None:
        """把旋转中心更新为当前几何中心。"""
        self.setTransformOriginPoint(self.local_rect().center())

    def scene_rect(self) -> QRectF:
        """对象在场景中的外接矩形（含旋转）。"""
        return self.mapToScene(self.local_rect()).boundingRect()

    # ---------------------------------------------------------- 控制点
    def handle_points(self) -> dict[str, QPointF]:
        """返回 名称 -> 局部坐标 的控制点表。"""
        r = self.local_rect()
        cx, cy = r.center().x(), r.center().y()
        return {
            "nw": QPointF(r.left(), r.top()),
            "n": QPointF(cx, r.top()),
            "ne": QPointF(r.right(), r.top()),
            "e": QPointF(r.right(), cy),
            "se": QPointF(r.right(), r.bottom()),
            "s": QPointF(cx, r.bottom()),
            "sw": QPointF(r.left(), r.bottom()),
            "w": QPointF(r.left(), cy),
        }

    def handle_names(self) -> tuple[str, ...]:
        return HANDLE_NAMES

    # ---------------------------------------------------------- 序列化
    def to_dict(self) -> dict:
        r = self.local_rect()
        return {
            "id": self.id,
            "type": self.TYPE,
            "x": round(self.pos().x(), 3),
            "y": round(self.pos().y(), 3),
            "w": round(r.width(), 3),
            "h": round(r.height(), 3),
            "rotation": round(self.rotation(), 3),
            "z": round(self.zValue(), 3),
            "visible": bool(getattr(self, "_own_visible", True)),
            "style": dict(self.style),
            "geometry": self.geometry_dict(),
        }

    def apply_dict(self, data: dict) -> None:
        self.id = data.get("id", self.id)
        self.style = dict(DEFAULT_STYLE)
        self.style.update(data.get("style", {}))
        self.apply_geometry(data.get("geometry", {}), data)
        self.setPos(float(data.get("x", 0.0)), float(data.get("y", 0.0)))
        self.setRotation(float(data.get("rotation", 0.0)))
        self.setZValue(float(data.get("z", 0.0)))
        # 对象自己的显隐和"图层被隐藏"是两件事：这里只记录自己的那份，
        # 最终是否可见由图层状态决定（见 CanvasScene.apply_layer_state）。
        self._own_visible = bool(data.get("visible", True))
        self.setVisible(self._own_visible)
        self.refresh_origin()
        self.apply_style()

    def geometry_dict(self) -> dict:
        return {}

    def apply_geometry(self, geometry: dict, data: dict) -> None:
        """重建局部几何；data 里带有 w/h 供使用。"""

    def apply_assets(self, assets: dict | None) -> None:
        """把工程文件里的位图资源挂到对象上（只有图片对象需要）。"""

    # 供撤销命令生成标签
    def label(self) -> str:
        return self.LABEL


class AnnoItem(AnnoMixin, QGraphicsObject):
    """普通标注对象的 Qt 基类。

    注意基类顺序：``AnnoMixin`` 必须在前面。``QGraphicsItem`` 里
    ``boundingRect()`` / ``paint()`` 是纯虚函数，如果它排在混入之前，
    Python 会解析到那个纯虚实现并抛 NotImplementedError。
    """

    TYPE = "base"
    LABEL = "标注"

    def __init__(self, style: dict | None = None, parent=None) -> None:
        QGraphicsObject.__init__(self, parent)
        self._anno_init(style)


# ------------------------------------------------------------------ 通用操作
def set_local_rect_keep_anchor(item: AnnoMixin, rect: QRectF) -> None:
    """把几何改为 ``rect``（局部坐标），同时平移对象使 ``rect`` 左上角视觉位置不变。

    这样 ``set_local_rect`` 的实现只需要关心尺寸，不必操心 pos 的补偿，
    并且旋转状态下的补偿也是正确的（走 mapToParent）。
    """
    before = item.mapToParent(rect.topLeft())
    item.set_local_rect(QRectF(0.0, 0.0, rect.width(), rect.height()))
    after = item.mapToParent(QPointF(0.0, 0.0))
    item.moveBy(before.x() - after.x(), before.y() - after.y())
    item.refresh_origin()
