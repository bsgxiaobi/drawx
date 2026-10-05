"""绘制类工具：矩形/椭圆/直线/箭头/画笔/高亮/马赛克/模糊/文字。"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt

from ..items.base import set_local_rect_keep_anchor
from ..items.factory import ITEM_TYPES
from ..items.text import TextItem
from .base import Tool


def _rect_from(origin: QPointF, point: QPointF, square: bool, from_center: bool) -> QRectF:
    dx = point.x() - origin.x()
    dy = point.y() - origin.y()
    if square:
        size = max(abs(dx), abs(dy))
        dx = size if dx >= 0 else -size
        dy = size if dy >= 0 else -size
    if from_center:
        return QRectF(
            origin.x() - abs(dx), origin.y() - abs(dy), abs(dx) * 2.0, abs(dy) * 2.0
        )
    return QRectF(origin, QPointF(origin.x() + dx, origin.y() + dy)).normalized()


class _CreateTool(Tool):
    """"按下-拖动-松开"创建对象这一类工具的公共骨架。

    拖动过程中对象就已经在场景里（所见即所得预览），松开时提交一条撤销命令
    并**沿用同一个对象**（adopt），所以既不会闪一下，也不会多分配一个对象。
    """

    type_name = "rect"
    cursor = Qt.CursorShape.CrossCursor
    #: 本工具偏好的默认样式；只有当用户没有在属性面板里显式改过这个键时才生效
    #: （比如高亮笔天然应该是半透明的，但不能覆盖用户手动调过的不透明度）
    default_overrides: dict = {}

    def __init__(self) -> None:
        super().__init__()
        self._item = None
        self._origin = QPointF()
        self._min_size = 3.0
        self._is_new = True

    def reset(self) -> None:
        self._item = None

    # ---------------------------------------------------------- 公共
    def _make_item(self, view, scene_pos: QPointF):
        cls = ITEM_TYPES[self.type_name]
        style = dict(view.default_style)
        for key, value in self.default_overrides.items():
            if key not in view.user_style_keys:
                style[key] = value
        item = cls(style)
        item.setZValue(view.scene().next_z())
        item.setPos(scene_pos)
        view.scene().add_anno(item)
        return item

    def _cancel(self, view) -> None:
        if self._item is not None:
            view.scene().remove_anno(self._item)
        self._item = None

    def _commit(self, view) -> None:
        item = self._item
        self._item = None
        if item is not None:
            view.commit_new_item(item)

    def _too_small(self) -> bool:
        rect = self._item.local_rect()
        return (
            rect.width() < self._min_size
            and rect.height() < self._min_size
            and self.type_name not in ("line", "arrow", "freehand", "highlight")
        )

    def mouse_press(self, view, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        view.finish_text_edit()
        scene_pos = self.scene_pos(view, event)
        self._origin = scene_pos
        self._item = self._make_item(view, scene_pos)
        self._is_new = True
        self.on_press(view, event, scene_pos)
        return True

    def mouse_move(self, view, event) -> bool:
        if self._item is None:
            return True
        self.on_move(view, event, self.scene_pos(view, event))
        return True

    def mouse_release(self, view, event) -> bool:
        if self._item is None:
            return False
        if self._too_small():
            self._cancel(view)
        else:
            self.on_release(view, event)
            self._commit(view)
        return True

    # ---------------------------------------------------------- 子类钩子
    def on_press(self, view, event, scene_pos: QPointF) -> None:
        pass

    def on_move(self, view, event, scene_pos: QPointF) -> None:
        pass

    def on_release(self, view, event) -> None:
        pass


class ShapeTool(_CreateTool):
    """矩形 / 椭圆 / 圆角矩形。"""

    LABELS = {
        "rect": ("矩形", "拖动绘制矩形；Shift 正方形，Alt 从中心"),
        "ellipse": ("椭圆", "拖动绘制椭圆；Shift 正圆，Alt 从中心"),
        "roundrect": ("圆角矩形", "拖动绘制圆角矩形；Shift 正方形"),
    }

    def __init__(self, type_name: str) -> None:
        super().__init__()
        self.type_name = type_name
        self.name = type_name
        self.label, self.hint = self.LABELS[type_name]

    def on_press(self, view, event, scene_pos: QPointF) -> None:
        self._item.set_local_rect(QRectF(0.0, 0.0, 1.0, 1.0))

    def on_move(self, view, event, scene_pos: QPointF) -> None:
        origin = self._item.pos()
        rect = _rect_from(
            origin,
            scene_pos,
            bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
            bool(event.modifiers() & Qt.KeyboardModifier.AltModifier),
        )
        local = rect.translated(-origin.x(), -origin.y())
        set_local_rect_keep_anchor(self._item, local)


class LineTool(_CreateTool):
    """直线 / 箭头。"""

    LABELS = {
        "line": ("直线", "拖动画线；Shift 锁定 45° 倍数"),
        "arrow": ("箭头", "拖动画箭头；Shift 锁定 45° 倍数"),
    }

    def __init__(self, type_name: str) -> None:
        super().__init__()
        self.type_name = type_name
        self.name = type_name
        self.label, self.hint = self.LABELS[type_name]

    def on_press(self, view, event, scene_pos: QPointF) -> None:
        self._item.p1 = QPointF(0.0, 0.0)
        self._item.p2 = QPointF(1.0, 1.0)
        self._item.refresh_origin()

    def on_move(self, view, event, scene_pos: QPointF) -> None:
        item = self._item
        local = item.mapFromScene(scene_pos)
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            local = _constrain_angle(item.p1, local)
        item.set_endpoint("p2", local)


class FreehandTool(_CreateTool):
    """画笔 / 高亮笔：把鼠标轨迹点收集成折线对象。"""

    LABELS = {
        "freehand": ("画笔", "按住拖动自由绘制"),
        "highlight": ("高亮", "按住拖动涂抹高亮"),
    }

    def __init__(self, type_name: str) -> None:
        super().__init__()
        self.type_name = type_name
        self.name = type_name
        self.label, self.hint = self.LABELS[type_name]
        self.default_overrides = (
            {"opacity": 0.38} if type_name == "highlight" else {}
        )
        self._scene_points: list[QPointF] = []
        self._min_size = 1.0

    def on_press(self, view, event, scene_pos: QPointF) -> None:
        self._scene_points = [QPointF(scene_pos)]

    def on_move(self, view, event, scene_pos: QPointF) -> None:
        last = self._scene_points[-1] if self._scene_points else None
        if last is not None:
            # 抽稀：视口 2 像素以内不记点，避免折线过密
            scale = view.zoom()
            if abs(scene_pos.x() - last.x()) * scale < 2.0 and abs(
                scene_pos.y() - last.y()
            ) * scale < 2.0:
                return
        self._scene_points.append(QPointF(scene_pos))
        self._item.set_scene_points(self._scene_points)

    def _too_small(self) -> bool:
        return len(self._scene_points) < 2

    def on_release(self, view, event) -> None:
        if len(self._scene_points) == 1:
            self._scene_points.append(QPointF(self._scene_points[0]))


class PatchTool(_CreateTool):
    """马赛克 / 模糊区域。"""

    LABELS = {
        "mosaic": ("马赛克", "框选要打码的区域，之后可随时移动或改强度"),
        "blur": ("模糊", "框选要模糊的区域，之后可随时移动或改强度"),
    }

    def __init__(self, type_name: str) -> None:
        super().__init__()
        self.type_name = type_name
        self.name = type_name
        self.label, self.hint = self.LABELS[type_name]
        self._min_size = 4.0

    def on_press(self, view, event, scene_pos: QPointF) -> None:
        if "block" in view.default_style:
            self._item.block = float(view.default_style["block"])
        self._item.set_local_rect(QRectF(0.0, 0.0, 2.0, 2.0))

    def on_move(self, view, event, scene_pos: QPointF) -> None:
        origin = self._item.pos()
        rect = _rect_from(origin, scene_pos, False, False)
        local = rect.translated(-origin.x(), -origin.y())
        set_local_rect_keep_anchor(self._item, local)


class TextTool(Tool):
    name = "text"
    label = "文字"
    hint = "单击落点后直接输入；Esc 结束，空文字自动丢弃"
    cursor = Qt.CursorShape.IBeamCursor

    def mouse_press(self, view, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        view.finish_text_edit()
        scene_pos = self.scene_pos(view, event)
        style = dict(view.default_style)
        item = TextItem(style)
        item.setZValue(view.scene().next_z())
        item.setPos(scene_pos)
        view.scene().add_anno(item)
        view.begin_text_edit(item, is_new=True)
        return True


def _constrain_angle(origin: QPointF, point: QPointF) -> QPointF:
    import math

    dx = point.x() - origin.x()
    dy = point.y() - origin.y()
    angle = math.degrees(math.atan2(dy, dx))
    snapped = round(angle / 45.0) * 45.0
    length = math.hypot(dx, dy)
    radians = math.radians(snapped)
    return QPointF(
        origin.x() + length * math.cos(radians), origin.y() + length * math.sin(radians)
    )
