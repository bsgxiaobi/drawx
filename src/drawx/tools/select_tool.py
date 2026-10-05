"""选择工具：选中 / 多选 / 框选 / 移动 / 缩放 / 旋转。"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen

from ..const import COLOR_ACCENT
from ..items.base import anchor_point, set_local_rect_keep_anchor
from ..items.text import TextItem
from ..model.commands import ModifyCommand
from .base import Tool

_EPS = 1e-6


def _rect_from(origin: QPointF, point: QPointF, square: bool, from_center: bool) -> QRectF:
    dx = point.x() - origin.x()
    dy = point.y() - origin.y()
    if square:
        size = max(abs(dx), abs(dy))
        dx = math.copysign(size, dx) if dx else size
        dy = math.copysign(size, dy) if dy else size
    if from_center:
        return QRectF(
            origin.x() - abs(dx), origin.y() - abs(dy), abs(dx) * 2.0, abs(dy) * 2.0
        )
    return QRectF(origin, QPointF(origin.x() + dx, origin.y() + dy)).normalized()


class SelectTool(Tool):
    name = "select"
    label = "选择"
    hint = (
        "拖动移动，控制点缩放，顶部圆点旋转；拖动图片＝移动这张图片，"
        "Shift+拖动＝框选标注（图片请在图层里或直接点选）"
    )
    cursor = Qt.CursorShape.ArrowCursor
    draws_overlay = True

    def __init__(self) -> None:
        super().__init__()
        self._mode: str | None = None
        self._handle: str | None = None
        self._handle_item = None
        self._items: list = []
        self._before: dict = {}
        self._start_scene = QPointF()
        self._anchor_scene = QPointF()
        self._band: QRectF | None = None
        self._band_additive = False
        self._band_base: list = []
        self._rotate_center = QPointF()
        self._rotate_start = 0.0
        self._rotate0 = 0.0
        self._moved = False
        self._press_image = None

    def reset(self) -> None:
        self._mode = None
        self._handle = None
        self._handle_item = None
        self._items = []
        self._before = {}
        self._band = None
        self._band_base = []
        self._press_image = None

    # ---------------------------------------------------------- 按下
    def mouse_press(self, view, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        view.finish_text_edit()
        scene = view.scene()
        view_pos = event.position()
        scene_pos = self.scene_pos(view, event)
        modifiers = event.modifiers()
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

        # 1) 控制点优先（缩放 / 旋转）
        hit = view.handle_at(view_pos)
        if hit is not None:
            item, name = hit
            self._handle_item = item
            self._handle = name
            self._before = {item: item.to_dict()}
            if name == "rotate":
                self._mode = "rotate"
                center = item.mapToScene(item.local_rect().center())
                self._rotate_center = center
                self._rotate_start = math.degrees(
                    math.atan2(scene_pos.y() - center.y(), scene_pos.x() - center.x())
                )
                self._rotate0 = item.rotation()
            else:
                self._mode = "resize"
                self._anchor_scene = item.mapToScene(
                    anchor_point(item.local_rect(), name)
                )
            return True

        # 2) 标注命中（标注永远优先于图片，否则照片会把标注全挡住）
        item = view.anno_at(view_pos)
        self._press_image = None
        if item is None and not shift:
            # 3) 图片：直接拖动它。
            #    这一条是"多张现场照片拼成一张图"的主交互——拖进来就能拖走，
            #    不需要先去图层面板点一下。代价是"在照片上拖动"不再等于框选，
            #    所以框选留了 Shift+拖动（提示里也写了）。
            image = view.image_at(view_pos)
            if image is not None:
                if image not in scene.selected_anno():
                    scene.set_selection([image])
                item = image
                self._press_image = image
        if item is None:
            if not shift:
                scene.set_selection([])
            self._mode = "band"
            self._band_additive = shift
            self._band_base = scene.selected_anno() if shift else []
            self._start_scene = scene_pos
            self._band = QRectF(scene_pos, scene_pos)
            view.refresh()
            return True

        if modifiers & Qt.KeyboardModifier.ControlModifier:
            selection = list(scene.selected_anno())
            if item in selection:
                selection.remove(item)
            else:
                selection.append(item)
            scene.set_selection(selection)
        elif item not in scene.selected_anno():
            scene.set_selection([item])

        self._mode = "move"
        self._start_scene = scene_pos
        self._items = scene.selected_anno()
        self._before = {it: it.to_dict() for it in self._items}
        self._moved = False
        return True

    # ---------------------------------------------------------- 移动
    def mouse_move(self, view, event) -> bool:
        if self._mode is None:
            return False
        scene_pos = self.scene_pos(view, event)
        modifiers = event.modifiers()

        if self._mode == "band":
            self._band = QRectF(self._start_scene, scene_pos).normalized()
            view.refresh()
            return True

        if self._mode == "move":
            delta = scene_pos - self._start_scene
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                if abs(delta.x()) >= abs(delta.y()):
                    delta.setY(0.0)
                else:
                    delta.setX(0.0)
            for item in self._items:
                base = self._before[item]
                item.setPos(base["x"] + delta.x(), base["y"] + delta.y())
            self._moved = True
            return True

        if self._mode == "resize":
            self._do_resize(view, scene_pos, modifiers)
            return True

        if self._mode == "rotate":
            item = self._handle_item
            angle = math.degrees(
                math.atan2(
                    scene_pos.y() - self._rotate_center.y(),
                    scene_pos.x() - self._rotate_center.x(),
                )
            )
            value = self._rotate0 + (angle - self._rotate_start)
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                value = round(value / 15.0) * 15.0
            item.setRotation(value)
            return True
        return False

    def _do_resize(self, view, scene_pos: QPointF, modifiers) -> None:
        item = self._handle_item
        handle = self._handle or ""
        # 每次都从起始快照重算，避免误差累积
        item.apply_dict(self._before[item])

        if handle in ("p1", "p2"):
            local = item.mapFromScene(scene_pos)
            other = item.p2 if handle == "p1" else item.p1
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                local = _constrain_45(other, local)
            item.set_endpoint(handle, local)
            return

        base_rect = QRectF(item.local_rect())
        local = item.mapFromScene(scene_pos)
        rect = QRectF(base_rect)
        if handle in ("nw", "n", "ne"):
            rect.setTop(local.y())
        if handle in ("sw", "s", "se"):
            rect.setBottom(local.y())
        if handle in ("nw", "w", "sw"):
            rect.setLeft(local.x())
        if handle in ("ne", "e", "se"):
            rect.setRight(local.x())

        if modifiers & Qt.KeyboardModifier.ShiftModifier and handle in (
            "nw",
            "ne",
            "se",
            "sw",
        ):
            rect = _square(rect, base_rect, handle)
        rect = rect.normalized()
        if rect.width() < 1.0:
            rect.setWidth(1.0)
        if rect.height() < 1.0:
            rect.setHeight(1.0)

        set_local_rect_keep_anchor(item, QRectF(0.0, 0.0, rect.width(), rect.height()))
        # 让"对角锚点"保持不动
        anchor_after = item.mapToScene(anchor_point(item.local_rect(), handle))
        delta = self._anchor_scene - anchor_after
        item.moveBy(delta.x(), delta.y())

    # ---------------------------------------------------------- 松开
    def mouse_release(self, view, event) -> bool:
        scene = view.scene()
        mode = self._mode
        if mode == "band":
            rect = self._band
            self._band = None
            if rect is not None and rect.width() > 2 and rect.height() > 2:
                path = QPainterPath()
                path.addRect(rect)
                # 框选只收矢量标注：图片一张就铺满画布，把它框进来会让框选彻底没法用
                allowed = scene.selectable_annotations()
                found = [
                    it
                    for it in scene.items(
                        path, Qt.ItemSelectionMode.IntersectsItemShape
                    )
                    if it in allowed
                ]
                selection = list(self._band_base)
                for it in found:
                    if it not in selection:
                        selection.append(it)
                scene.set_selection(selection)
            elif self._press_image is not None:
                # 单击（拖动距离为 0）落在图片上：当成"选中这张图片"
                scene.set_selection([self._press_image])
            view.refresh()
            self.reset()
            return True

        if mode == "move":
            if not self._moved or not self._items:
                self.reset()
                return True
            items = list(self._items)
            label = "移动"
        elif mode in ("resize", "rotate") and self._handle_item is not None:
            items = [self._handle_item]
            label = "缩放" if mode == "resize" else "旋转"
        else:
            self.reset()
            return True

        old = [self._before[item] for item in items]
        new = [item.to_dict() for item in items]
        if old != new:
            view.push_command(ModifyCommand(items, old, new, f"{label}标注"))
        self.reset()
        return True

    # ---------------------------------------------------------- 双击
    def mouse_double_click(self, view, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        item = view.anno_at(event.position())
        if isinstance(item, TextItem):
            view.scene().set_selection([item])
            view.begin_text_edit(item)
            return True
        return False

    # ---------------------------------------------------------- 覆盖层
    def paint_overlay(self, view, painter) -> None:
        if self._band is None:
            return
        transform = view.viewportTransform()
        top_left = transform.map(self._band.topLeft())
        bottom_right = transform.map(self._band.bottomRight())
        rect = QRectF(top_left, bottom_right).normalized()
        painter.setPen(QPen(QColor(COLOR_ACCENT), 1, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(47, 124, 246, 36))
        painter.drawRect(rect)


def _constrain_45(origin: QPointF, point: QPointF) -> QPointF:
    dx = point.x() - origin.x()
    dy = point.y() - origin.y()
    angle = math.degrees(math.atan2(dy, dx))
    snapped = round(angle / 45.0) * 45.0
    length = math.hypot(dx, dy)
    radians = math.radians(snapped)
    return QPointF(
        origin.x() + length * math.cos(radians), origin.y() + length * math.sin(radians)
    )


def _square(rect: QRectF, base: QRectF, handle: str) -> QRectF:
    """角手柄 + Shift = 等比缩放。

    只负责算出尺寸；位置由 :func:`_do_resize` 里的锚点校正决定，
    所以这里返回一个"从原点起算"的矩形即可。
    """
    size = max(rect.width(), rect.height())
    if base.width() > _EPS and base.height() > _EPS:
        ratio = base.height() / base.width()
    else:
        ratio = 1.0
    return QRectF(0.0, 0.0, size, size * ratio)
