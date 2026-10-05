"""裁剪工具：两种裁剪，都是**非破坏**的。

* **画布裁剪**（没有选中图片时）：框选决定"导出成图的范围"，只是文档上的一个矩形，
  随时可以改回来。
* **图片图层裁剪**（选中了一张图片时）：框选决定这张图片保留源图的哪一块
  （``ImageItem.src_rect``）。进入时图片会临时显示**整幅原图**，所以裁掉的部分
  随时能重新框回来；松手才提交，源位图一个像素都不会丢。

两种模式共用同一套"框 + 8 个控制点"的交互，区别只在坐标系：
画布模式用场景坐标，图片模式用**源图像素坐标**（经对象变换映射到屏幕）。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen

from ..const import COLOR_ACCENT, HIT_TOLERANCE
from ..items.image_item import ImageItem
from ..model.commands import DocPropCommand, ModifyCommand
from .base import Tool

HANDLE_NAMES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")


def crop_handle_point(rect: QRectF, name: str) -> QPointF:
    cx, cy = rect.center().x(), rect.center().y()
    return {
        "nw": QPointF(rect.left(), rect.top()),
        "n": QPointF(cx, rect.top()),
        "ne": QPointF(rect.right(), rect.top()),
        "e": QPointF(rect.right(), cy),
        "se": QPointF(rect.right(), rect.bottom()),
        "s": QPointF(cx, rect.bottom()),
        "sw": QPointF(rect.left(), rect.bottom()),
        "w": QPointF(rect.left(), cy),
    }[name]


def _distance(a: QPointF, b: QPointF) -> float:
    return math.hypot(a.x() - b.x(), a.y() - b.y())


class CropTool(Tool):
    name = "crop"
    label = "裁剪"
    hint = (
        "拖动即框出新范围；拖控制点微调；Alt+拖动整体移动。"
        "选中一张图片时裁的是这张图片（会显示整幅原图，随时可改回来），"
        "否则裁的是导出范围。都是非破坏的"
    )
    cursor = Qt.CursorShape.CrossCursor
    draws_overlay = True

    def __init__(self) -> None:
        super().__init__()
        self._item: ImageItem | None = None
        self._mode: str | None = None
        self._handle: str | None = None
        self._origin = QPointF()
        self._frame = QRectF()
        self._before_crop = QRectF()
        self._before_src = QRectF()
        self._before_snapshot: dict | None = None
        self._min_size = 8.0
        self._dragged = False

    def reset(self) -> None:
        # 中途切换工具时必须把图片从"整幅原图"状态恢复回来，否则用户会看到
        # 一张突然变大的图（而且没有撤销记录可以救）。
        if self._item is not None:
            self._item.end_crop(None)
        self._item = None
        self._mode = None
        self._handle = None
        self._dragged = False
        self._before_snapshot = None
        self._frame = QRectF()

    # ---------------------------------------------------------- 目标
    def image_target(self) -> ImageItem | None:
        """正在裁剪的图片；没在裁就取"单选的那张图片"。"""
        if self._item is not None:
            return self._item
        if self.view is None:
            return None
        selection = self.view.scene().selected_anno()
        if len(selection) == 1 and isinstance(selection[0], ImageItem):
            return selection[0]
        return None

    @property
    def image_mode(self) -> bool:
        return self._item is not None

    def frame_source(self) -> QRectF:
        """图片模式下当前框（源图像素坐标）。"""
        return QRectF(self._frame)

    def frame_local(self) -> QRectF:
        """图片模式下当前框（对象局部坐标，供视图画叠加层）。

        没在拖动时用的是图片当前的保留区域 —— 这样"选中图片 + 裁剪工具"一进去就能
        看到现有的裁剪框。拖动中 ``_frame`` 已经是源坐标，而全图模式下
        ``局部坐标 = 源坐标 × 显示尺度``，所以同一个换算成立。
        """
        item = self.image_target()
        if item is None:
            return QRectF()
        source = self._frame if self._item is not None else item.src_rect
        kx, ky = item.pixel_scale()
        return QRectF(
            source.x() * kx,
            source.y() * ky,
            source.width() * kx,
            source.height() * ky,
        )

    def frame_scene(self) -> QRectF:
        """画布模式下的框（场景坐标；没在拖动时就是当前导出范围）。"""
        if self._mode is None and self.view is not None:
            return QRectF(self.view.scene().doc.crop)
        return QRectF(self._frame)

    # ---------------------------------------------------------- 坐标换算
    def _to_source(self, item: ImageItem, scene_pos: QPointF) -> QPointF:
        local = item.mapFromScene(scene_pos)
        kx, ky = item.pixel_scale()
        return QPointF(local.x() / max(1e-6, kx), local.y() / max(1e-6, ky))

    def _view_points(self, view) -> dict[str, QPointF]:
        """当前框 8 个控制点在视口里的位置。"""
        transform = view.viewportTransform()
        item = self.image_target()
        frame = self.frame_local() if item is not None else self.frame_scene()
        points: dict[str, QPointF] = {}
        for name in HANDLE_NAMES:
            local = crop_handle_point(frame, name)
            scene = item.mapToScene(local) if item is not None else local
            points[name] = transform.map(scene)
        return points

    def hover_handle(self, view, view_pos: QPointF) -> str | None:
        """悬停到控制点时返回名字，供视图换成缩放光标。"""
        if self._mode is not None:
            return None
        return self._hit_handle(view, view_pos)

    def _hit_handle(self, view, view_pos: QPointF) -> str | None:
        tolerance = HIT_TOLERANCE / max(view.zoom(), 1e-6)
        best = None
        best_distance = tolerance
        for name, point in self._view_points(view).items():
            distance = _distance(point, view_pos)
            if distance <= best_distance:
                best_distance = distance
                best = name
        return best

    def overlay_polygon(self, view) -> list[QPointF]:
        """当前框四角的视口坐标（视图画叠加层用）。"""
        transform = view.viewportTransform()
        item = self.image_target()
        if item is not None:
            local = self.frame_local()
            corners = [
                QPointF(local.left(), local.top()),
                QPointF(local.right(), local.top()),
                QPointF(local.right(), local.bottom()),
                QPointF(local.left(), local.bottom()),
            ]
            return [transform.map(item.mapToScene(point)) for point in corners]
        frame = self.frame_scene()
        return [
            transform.map(QPointF(frame.left(), frame.top())),
            transform.map(QPointF(frame.right(), frame.top())),
            transform.map(QPointF(frame.right(), frame.bottom())),
            transform.map(QPointF(frame.left(), frame.bottom())),
        ]

    # ---------------------------------------------------------- 事件
    def mouse_press(self, view, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        view.finish_text_edit()
        scene_pos = self.scene_pos(view, event)
        self._origin = scene_pos
        self._handle = None
        self._dragged = False
        self._mode = None

        item = self.image_target()
        if item is not None and item.has_source():
            self._item = item
            self._before_snapshot = item.to_dict()
            self._before_src = QRectF(item.src_rect)
            item.begin_crop()  # 临时显示整幅原图，让"裁掉的部分"能重新框回来
            self._frame = QRectF(item.src_rect)
            handle = self._hit_handle(view, event.position())
            if handle:
                self._mode = "resize"
                self._handle = handle
            elif event.modifiers() & Qt.KeyboardModifier.AltModifier:
                self._mode = "move"
            else:
                # 默认就是"拖出新范围"。绝不能写成"在框内按下=移动"——初始框等于
                # 整幅图，那样用户永远框不出新范围（v0.1 踩过这个坑）。
                self._mode = "new"
            view.refresh()
            return True

        doc = view.scene().doc
        self._before_crop = QRectF(doc.crop)
        self._frame = QRectF(doc.crop)
        handle = self._hit_handle(view, event.position())
        if handle:
            self._mode = "resize"
            self._handle = handle
        elif event.modifiers() & Qt.KeyboardModifier.AltModifier:
            self._mode = "move"
        else:
            self._mode = "new"
        view.refresh()
        return True

    def mouse_move(self, view, event) -> bool:
        if self._mode is None:
            return False
        scene_pos = self.scene_pos(view, event)
        self._dragged = True
        if self._item is not None:
            self._move_image(view, scene_pos)
        else:
            self._move_canvas(view, scene_pos)
        view.refresh()
        return True

    def _move_canvas(self, view, scene_pos: QPointF) -> None:
        doc = view.scene().doc
        rect = QRectF(self._before_crop)
        if self._mode == "new":
            rect = QRectF(self._origin, scene_pos).normalized()
        elif self._mode == "move":
            rect.translate(scene_pos - self._origin)
        else:
            handle = self._handle or ""
            if "n" in handle:
                rect.setTop(scene_pos.y())
            if "s" in handle:
                rect.setBottom(scene_pos.y())
            if "w" in handle:
                rect.setLeft(scene_pos.x())
            if "e" in handle:
                rect.setRight(scene_pos.x())
            rect = rect.normalized()
            if rect.width() < self._min_size:
                rect.setWidth(self._min_size)
            if rect.height() < self._min_size:
                rect.setHeight(self._min_size)
        rect = rect.intersected(doc.canvas_rect())
        if rect.width() >= self._min_size and rect.height() >= self._min_size:
            self._frame = rect

    def _move_image(self, view, scene_pos: QPointF) -> None:
        item = self._item
        if item is None:
            return
        full = QRectF(0.0, 0.0, float(item.source.width()), float(item.source.height()))
        source_pos = self._to_source(item, scene_pos)
        # _origin 一直是场景坐标，按当前变换换算成源坐标，两种模式（新建/移动）共用
        source_origin = self._to_source(item, self._origin)
        rect = QRectF(self._before_src)
        if self._mode == "new":
            rect = QRectF(source_origin, source_pos).normalized()
        elif self._mode == "move":
            rect.translate(source_pos - source_origin)
        else:
            handle = self._handle or ""
            if "n" in handle:
                rect.setTop(source_pos.y())
            if "s" in handle:
                rect.setBottom(source_pos.y())
            if "w" in handle:
                rect.setLeft(source_pos.x())
            if "e" in handle:
                rect.setRight(source_pos.x())
            rect = rect.normalized()
            if rect.width() < self._min_size:
                rect.setWidth(self._min_size)
            if rect.height() < self._min_size:
                rect.setHeight(self._min_size)
        rect = rect.intersected(full)
        if rect.width() >= self._min_size and rect.height() >= self._min_size:
            self._frame = rect

    def mouse_release(self, view, event) -> bool:
        if self._mode is None:
            return False
        mode = self._mode
        item = self._item
        self._mode = None
        self._handle = None
        dragged = self._dragged
        self._dragged = False

        if item is not None:
            return self._release_image(view, item, dragged)
        return self._release_canvas(view, mode)

    def _release_canvas(self, view, mode: str) -> bool:
        doc = view.scene().doc
        after = QRectF(self._frame)
        self._frame = QRectF()
        if after != self._before_crop:
            doc.crop = after
            view.push_command(
                DocPropCommand(lambda r: view.set_crop(r), self._before_crop, after, "裁剪图片")
            )
        view.refresh()
        return True

    def _release_image(self, view, item: ImageItem, dragged: bool) -> bool:
        frame = QRectF(self._frame)
        before_src = QRectF(self._before_src)
        snapshot = self._before_snapshot
        self._item = None
        self._frame = QRectF()
        self._before_snapshot = None

        same = (
            abs(frame.x() - before_src.x()) < 0.5
            and abs(frame.y() - before_src.y()) < 0.5
            and abs(frame.width() - before_src.width()) < 0.5
            and abs(frame.height() - before_src.height()) < 0.5
        )
        if not dragged or same or frame.width() < self._min_size or frame.height() < self._min_size:
            # 只是点了一下、或者框没变：什么都不做，恢复显示状态
            item.end_crop(None)
            view.refresh()
            return True

        item.end_crop(frame)
        after = item.to_dict()
        if snapshot is not None and after != snapshot:
            view.push_command(
                ModifyCommand([item], [snapshot], [after], "裁剪图片图层")
            )
        view.refresh()
        return True

    def key_press(self, view, event) -> bool:
        if event.key() == Qt.Key.Key_Escape and self._item is not None:
            self._item.end_crop(None)
            self._item = None
            self._mode = None
            self._frame = QRectF()
            self._before_snapshot = None
            view.refresh()
            return True
        return False

    # ---------------------------------------------------------- 覆盖层
    def paint_overlay(self, view, painter) -> None:
        if self._mode is None:
            return
        # 画布裁剪时视图已经在画统一的框（drawForeground），这里只补"新框"的提示
        if self._item is None and self._mode == "new":
            return
        points = self.overlay_polygon(view)
        painter.setPen(QPen(QColor(COLOR_ACCENT), 1, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        path.closeSubpath()
        painter.drawPath(path)
