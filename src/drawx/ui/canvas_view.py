"""画布视图。

这是整个编辑器的交互中枢，承担三件事：

1. **视图控制**：以鼠标为锚点的缩放、空格/中键平移、适应窗口。
2. **绘制分层**：背景位图在 ``drawBackground``，编辑态装饰（选择框、控制点、
   裁剪框、橡皮筋）在 ``drawForeground``。因为导出走的是 QGraphicsScene 渲染，
   编辑态装饰天然不会混进导出图里。
3. **事件分发**：把鼠标/键盘事件交给当前工具，工具不处理时才走默认逻辑。
"""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QFrame, QGraphicsView

from ..const import (
    COLOR_ACCENT,
    COLOR_CANVAS_EDGE,
    COLOR_DIM,
    COLOR_HANDLE,
    COLOR_VIEW_BG,
    HANDLE_SIZE,
    HIT_TOLERANCE,
    IMAGE_SUFFIXES,
    MAX_ZOOM,
    MIN_ZOOM,
    PROJECT_EXT,
    ROTATE_HANDLE_DIST,
)
from ..items.base import DEFAULT_STYLE, TEXT_STYLE_KEYS
from ..items.text import TextItem
from ..model.commands import (
    AddItemsCommand,
    CompoundCommand,
    ModifyCommand,
    RemoveItemsCommand,
    RemoveLayerCommand,
)
from ..tools import TOOL_KEYS, build_tools


def _distance(a: QPointF, b: QPointF) -> float:
    return math.hypot(a.x() - b.x(), a.y() - b.y())


def dropped_files(mime) -> list[str]:
    """从拖放数据里挑出能处理的本地文件（图片 / .drawx）。

    路径统一用 Path 规整过：QUrl.toLocalFile() 在 Windows 上给的是正斜杠，
    直接存下来会让"当前文件路径"和别处不一致。
    """
    if mime is None or not mime.hasUrls():
        return []
    paths: list[str] = []
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = str(Path(url.toLocalFile()))
        suffix = Path(path).suffix.lower()
        if suffix in IMAGE_SUFFIXES or suffix == PROJECT_EXT:
            paths.append(path)
    return paths


#: 悬停到控制点时的光标形状 —— 让用户一眼知道"这里能拖"
HANDLE_CURSORS = {
    "nw": Qt.CursorShape.SizeFDiagCursor,
    "se": Qt.CursorShape.SizeFDiagCursor,
    "ne": Qt.CursorShape.SizeBDiagCursor,
    "sw": Qt.CursorShape.SizeBDiagCursor,
    "n": Qt.CursorShape.SizeVerCursor,
    "s": Qt.CursorShape.SizeVerCursor,
    "e": Qt.CursorShape.SizeHorCursor,
    "w": Qt.CursorShape.SizeHorCursor,
    "p1": Qt.CursorShape.PointingHandCursor,
    "p2": Qt.CursorShape.PointingHandCursor,
    "rotate": Qt.CursorShape.CrossCursor,
}


class CanvasView(QGraphicsView):
    zoom_changed = Signal(float)
    cursor_moved = Signal(QPointF)
    tool_changed = Signal(str)

    def __init__(self, scene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setBackgroundBrush(QColor(COLOR_VIEW_BG))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.default_style: dict = dict(DEFAULT_STYLE)
        self.default_style.update(TEXT_STYLE_KEYS)
        #: 用户在属性面板里显式改过的样式键。工具的"偏好默认值"不能覆盖这些，
        #: 例如高亮笔默认半透明，但用户手动调过不透明度后就要听用户的。
        self.user_style_keys: set[str] = set()

        self._zoom = 1.0
        self._tools = build_tools()
        self._tool = self._tools["select"]
        self._tool.activate(self)
        self.viewport().setCursor(self._tool.cursor)

        self._panning = False
        self._pan_origin = QPointF()
        self._space_down = False
        self._fit_pending = False
        self._edit_item = None
        self._edit_is_new = False
        self._edit_before: dict | None = None

    # ============================================================== 基础
    @property
    def tool(self):
        return self._tool

    def tools(self) -> dict:
        return self._tools

    def zoom(self) -> float:
        return self._zoom

    def refresh(self) -> None:
        self.viewport().update()

    def to_scene(self, point: QPointF) -> QPointF:
        transform, ok = self.viewportTransform().inverted()
        if not ok:
            return self.mapToScene(point.toPoint())
        return transform.map(point)

    def push_command(self, command) -> None:
        self.scene().undo_stack.push(command)
        self.scene().mark_modified()
        self.refresh()

    # ============================================================== 工具
    def set_tool(self, name: str) -> None:
        tool = self._tools.get(name)
        if tool is None or tool is self._tool:
            return
        self.finish_text_edit()
        self._tool.deactivate()
        self._tool = tool
        self._tool.activate(self)
        self.viewport().setCursor(tool.cursor)
        self.tool_changed.emit(name)
        self.refresh()

    # ============================================================== 缩放平移
    def zoom_by(self, factor: float, under_mouse: bool = True) -> None:
        # 以真实变换为准：_zoom 缓存一旦和它不一致，缩放就会算错甚至完全不动
        current = self.transform().m11()
        if abs(current - self._zoom) > 1e-9:
            self._zoom = current
        target = max(MIN_ZOOM, min(MAX_ZOOM, current * factor))
        if abs(target - current) < 1e-9:
            return
        old_anchor = self.transformationAnchor()
        old_resize = self.resizeAnchor()
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
            if under_mouse
            else QGraphicsView.ViewportAnchor.AnchorViewCenter
        )
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.scale(target / current, target / current)
        self.setTransformationAnchor(old_anchor)
        self.setResizeAnchor(old_resize)
        self._zoom = self.transform().m11()
        self.zoom_changed.emit(self._zoom)

    def zoom_reset(self) -> None:
        self._zoom = 1.0
        self.setTransform(QTransform())
        self.centerOn(self.scene().doc.canvas_rect().center())
        self.zoom_changed.emit(self._zoom)

    def fit_to_window(self) -> None:
        rect = self.scene().doc.canvas_rect()
        if rect.isEmpty():
            return
        # 窗口还没布局完时视口只有几十像素，这时候算出来的缩放是垃圾值
        # （曾经因此让"空白画布"整个缩成一个点）。宁可先不缩放，等真正显示出来再算。
        viewport = self.viewport().rect()
        if viewport.width() < 60 or viewport.height() < 60:
            # 记一笔，等视口真正有尺寸了（resizeEvent）再补上
            self._fit_pending = True
            return
        self._fit_pending = False
        margin = max(rect.width(), rect.height()) * 0.03
        self.fitInView(
            rect.adjusted(-margin, -margin, margin, margin),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        self._zoom = self.transform().m11()
        self.zoom_changed.emit(self._zoom)

    # ============================================================== 命中
    def anno_at(self, view_pos: QPointF):
        """命中**矢量标注**：形状精确命中 + "封闭图形内部 + 容差"，取 z 更高的那个。

        合并成一次判断很重要：如果先做精确命中再退回容差，那么"空心矩形压在照片上"
        时点矩形内部会命中照片（照片的形状覆盖了那个像素），用户会觉得"选不中矩形"。

        容差按视口像素折算，因此缩小画布时细线也抓得住。
        **图片图层与锁定图层都不参与**：图片用 :meth:`image_at`，锁定的对象刻意点不动。
        """
        anno = self.scene().selectable_annotations()
        if not anno:
            return None
        scene_pos = self.to_scene(view_pos)
        tolerance = HIT_TOLERANCE / max(self.zoom(), 1e-6)

        precise = None
        for item in self.items(view_pos.toPoint()):
            if item in anno and (precise is None or item.zValue() > precise.zValue()):
                precise = item

        loose = None
        for item in sorted(anno, key=lambda i: i.zValue(), reverse=True):
            if not getattr(item, "CLOSED_SHAPE", False):
                continue
            local = item.mapFromScene(scene_pos)
            rect = item.local_rect()
            rect = rect.adjusted(-tolerance, -tolerance, tolerance, tolerance)
            if rect.contains(local):
                loose = item
                break

        if precise is None:
            return loose
        if loose is None:
            return precise
        return precise if precise.zValue() >= loose.zValue() else loose

    def image_at(self, view_pos: QPointF):
        """命中图片图层里的图片（从最上面一张往下找）。"""
        images = self.scene().selectable_images()
        if not images:
            return None
        for item in self.items(view_pos.toPoint()):
            if item in images:
                return item
        scene_pos = self.to_scene(view_pos)
        for item in sorted(images, key=lambda i: i.zValue(), reverse=True):
            if item.local_rect().contains(item.mapFromScene(scene_pos)):
                return item
        return None

    def _rotate_handle_view(self, item, transform: QTransform) -> QPointF | None:
        rect = item.local_rect()
        center = transform.map(item.mapToScene(rect.center()))
        top = transform.map(
            item.mapToScene(QPointF(rect.center().x(), rect.top()))
        )
        vector = top - center
        length = math.hypot(vector.x(), vector.y())
        if length < 1e-6:
            return None
        return top + QPointF(
            vector.x() / length * ROTATE_HANDLE_DIST,
            vector.y() / length * ROTATE_HANDLE_DIST,
        )

    def handle_at(self, view_pos: QPointF):
        """返回 (对象, 控制点名) 或 None。只有单选时才提供控制点。"""
        selection = self.scene().selected_anno()
        if len(selection) != 1:
            return None
        item = selection[0]
        if isinstance(item, TextItem) and item.editing:
            return None
        transform = self.viewportTransform()

        rotate = self._rotate_handle_view(item, transform)
        if rotate is not None and _distance(rotate, view_pos) <= HANDLE_SIZE:
            return (item, "rotate")

        best = None
        best_distance = float(HANDLE_SIZE)
        for name, local_point in item.handle_points().items():
            point = transform.map(item.mapToScene(local_point))
            distance = _distance(point, view_pos)
            if distance <= best_distance:
                best_distance = distance
                best = (item, name)
        return best

    # ============================================================== 文字编辑
    def begin_text_edit(self, item, is_new: bool = False) -> None:
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self._edit_item = item
        self._edit_is_new = is_new
        self._edit_before = item.to_dict()
        item.begin_edit()
        self.scene().text_edit_started.emit(item)
        self.refresh()

    def finish_text_edit(self, cancel: bool = False) -> None:
        item = self._edit_item
        if item is None:
            return
        self._edit_item = None
        before = self._edit_before
        self._edit_before = None
        is_new = self._edit_is_new
        self._edit_is_new = False

        text = item.toPlainText().strip() if isinstance(item, TextItem) else ""
        if is_new:
            if not text:
                self.scene().remove_anno(item)
            else:
                item.end_edit()
                self.push_command(
                    AddItemsCommand(
                        self.scene(), [item.to_dict()], "添加文字", adopt=[item]
                    )
                )
        else:
            item.end_edit()
            if cancel and before is not None:
                item.apply_dict(before)
            elif before is not None:
                after = item.to_dict()
                if after != before:
                    self.push_command(ModifyCommand([item], [before], [after], "修改文字"))
        self.scene().text_edit_finished.emit(item)
        self.refresh()

    # ============================================================== 命令封装
    def commit_new_item(self, item) -> None:
        self.push_command(
            AddItemsCommand(self.scene(), [item.to_dict()], "添加标注", adopt=[item])
        )
        self.scene().set_selection([item])

    def delete_selected(self) -> None:
        items = self.scene().selected_anno()
        if items:
            self.delete_items(items)

    def delete_items(self, items) -> None:
        """删除对象；图片图层里的图片走"删图层"，这样撤销能把整个图层原样带回来。"""
        scene = self.scene()
        layers: list = []
        for item in items:
            layer = scene.layer_of(item)
            if layer is not None and layer.is_image and layer not in layers:
                layers.append(layer)
        plain = [item for item in items if scene.layer_of(item) not in layers]
        if not layers:
            self.push_command(RemoveItemsCommand(scene, plain))
            return
        commands: list = [RemoveLayerCommand(scene, layer) for layer in layers]
        if plain:
            commands.append(RemoveItemsCommand(scene, plain))
        if len(commands) == 1:
            self.push_command(commands[0])
        else:
            self.push_command(CompoundCommand(commands, "删除图层与标注"))

    def set_crop(self, rect: QRectF) -> None:
        doc = self.scene().doc
        doc.crop = QRectF(rect)
        doc.clamp_crop()
        self.scene().refresh_scene_rect()
        self.refresh()

    def nudge_selected(self, dx: float, dy: float) -> None:
        items = self.scene().selected_anno()
        if not items:
            return
        old = [item.to_dict() for item in items]
        for item in items:
            item.moveBy(dx, dy)
        new = [item.to_dict() for item in items]
        self.push_command(
            ModifyCommand(
                items,
                old,
                new,
                "微调位置",
                mergeable=True,
                merge_key=("nudge", tuple(id(i) for i in items)),
            )
        )

    # ============================================================== 事件
    def mousePressEvent(self, event) -> None:
        if self._edit_item is not None:
            if self.itemAt(event.position().toPoint()) is self._edit_item:
                super().mousePressEvent(event)
                return
            self.finish_text_edit()

        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and self._space_down
        ):
            self._panning = True
            self._pan_origin = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        if self._tool.mouse_press(self, event):
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        position = event.position()
        self.cursor_moved.emit(self.to_scene(position))

        if self._panning:
            delta = position - self._pan_origin
            self._pan_origin = position
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            return

        if self._edit_item is not None:
            super().mouseMoveEvent(event)
            return

        if self._tool.mouse_move(self, event):
            return
        self._update_hover_cursor(position)
        super().mouseMoveEvent(event)

    def _update_hover_cursor(self, position: QPointF) -> None:
        """没按住键时，根据悬停位置切换光标。"""
        if self._space_down:
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            return
        if self._tool.name == "select":
            hit = self.handle_at(position)
            shape = HANDLE_CURSORS.get(hit[1]) if hit else self._tool.cursor
        elif self._tool.name == "crop":
            name = self._tool.hover_handle(self, position)
            shape = HANDLE_CURSORS.get(name) if name else self._tool.cursor
        else:
            shape = self._tool.cursor
        if self.viewport().cursor().shape() != shape:
            self.viewport().setCursor(shape)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit_pending:
            self.fit_to_window()

    def leaveEvent(self, event) -> None:
        self.viewport().setCursor(self._tool.cursor)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._panning:
            self._panning = False
            self.viewport().setCursor(
                Qt.CursorShape.OpenHandCursor
                if self._space_down
                else self._tool.cursor
            )
            return
        if self._edit_item is not None:
            super().mouseReleaseEvent(event)
            return
        if self._tool.mouse_release(self, event):
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._edit_item is None and self._tool.mouse_double_click(self, event):
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.zoom_by(1.0015**delta, under_mouse=True)
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:
        if self._edit_item is not None:
            super().keyPressEvent(event)
            return

        key = event.key()
        modifiers = event.modifiers()

        if key == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_down = True
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            return

        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
            return

        if key == Qt.Key.Key_Escape:
            # 先给工具一次机会：图片裁剪正开着"整幅原图"，Esc 应该先退出裁剪
            if self._tool.key_press(self, event):
                return
            self.scene().set_selection([])
            self.refresh()
            return

        if key in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
        ) and self.scene().selected_anno():
            step = 10.0 if modifiers & Qt.KeyboardModifier.ShiftModifier else 1.0
            dx = {Qt.Key.Key_Left: -step, Qt.Key.Key_Right: step}.get(key, 0.0)
            dy = {Qt.Key.Key_Up: -step, Qt.Key.Key_Down: step}.get(key, 0.0)
            self.nudge_selected(dx, dy)
            return

        if not (modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
            name = TOOL_KEYS.get(event.text().lower())
            if name:
                self.set_tool(name)
                return

        if self._tool.key_press(self, event):
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_down = False
            self.viewport().setCursor(self._tool.cursor)
            return
        super().keyReleaseEvent(event)

    # ============================================================== 拖放
    # 注意：QGraphicsView 的 viewport 默认 acceptDrops=True，拖放事件会被它
    # 接走并转给 QGraphicsScene（场景不处理就到此为止），主窗口根本收不到 ——
    # 这就是"文件拖不进窗口"的原因。所以必须在视图这一层自己处理。
    def dragEnterEvent(self, event) -> None:
        paths = dropped_files(event.mimeData())
        if paths:
            event.acceptProposedAction()
            window = self.window()
            if hasattr(window, "statusBar"):
                window.statusBar().showMessage(
                    f"松开即可导入：{Path(paths[0]).name}", 4000
                )
            return
        # 明确拒绝：不能落到默认逻辑去，否则 QGraphicsScene 会把 .txt 之类也收下
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if dropped_files(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        paths = dropped_files(event.mimeData())
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        handler = getattr(self.window(), "handle_dropped_paths", None)
        if callable(handler):
            handler(paths)

    # ============================================================== 绘制
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        painter.resetTransform()
        painter.fillRect(self.viewport().rect(), QColor(COLOR_VIEW_BG))
        painter.restore()

        # 画布只是一张底色纸：图片图层是场景图元，由 QGraphicsScene 按 z 顺序画出来。
        doc = self.scene().doc
        canvas = doc.canvas_rect()
        painter.fillRect(canvas, QColor(doc.bg_color))
        painter.setPen(QPen(QColor(COLOR_CANVAS_EDGE), 0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(canvas)

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        transform = self.viewportTransform()
        self._draw_crop(painter, transform)
        self._draw_selection(painter, transform)
        self._tool.paint_overlay(self, painter)
        painter.restore()

    # ---------------------------------------------------------- 裁剪框
    def _crop_tool(self):
        return self._tool if self._tool.name == "crop" else None

    def _draw_crop(self, painter: QPainter, transform: QTransform) -> None:
        """画导出范围 / 图片裁剪框。

        两种模式都可能是**旋转过的四边形**（图片图层可以旋转），所以统一按多边形画，
        并把"框外变暗"实现成"视口矩形减去框"的路径运算 —— 这样斜的框也不会露馅。
        """
        doc = self.scene().doc
        tool = self._crop_tool()
        item = tool.image_target() if tool is not None else None

        if item is not None:
            points = tool.overlay_polygon(self)
            self._dim_outside(painter, points)
            self._draw_frame_polygon(painter, points, active=True)
            self._draw_handle_boxes(painter, tool._view_points(self).values())
            return

        frame = tool.frame_scene() if tool is not None else QRectF(doc.crop)
        active = tool is not None
        view_rect = QRectF(
            transform.map(frame.topLeft()), transform.map(frame.bottomRight())
        ).normalized()

        if doc.is_cropped and active:
            viewport_rect = QRectF(self.viewport().rect())
            dim = QColor(*COLOR_DIM)
            for box in (
                QRectF(
                    viewport_rect.left(),
                    viewport_rect.top(),
                    viewport_rect.width(),
                    view_rect.top() - viewport_rect.top(),
                ),
                QRectF(
                    viewport_rect.left(),
                    view_rect.bottom(),
                    viewport_rect.width(),
                    viewport_rect.bottom() - view_rect.bottom(),
                ),
                QRectF(
                    viewport_rect.left(),
                    view_rect.top(),
                    view_rect.left() - viewport_rect.left(),
                    view_rect.height(),
                ),
                QRectF(
                    view_rect.right(),
                    view_rect.top(),
                    viewport_rect.right() - view_rect.right(),
                    view_rect.height(),
                ),
            ):
                painter.fillRect(box, dim)

        self._draw_frame_rect(painter, view_rect, active)
        if active and tool is not None:
            self._draw_handle_boxes(painter, tool._view_points(self).values())

    def _dim_outside(self, painter: QPainter, points: list[QPointF]) -> None:
        outer = QPainterPath()
        outer.addRect(QRectF(self.viewport().rect()))
        inner = QPainterPath(QPointF(points[0]))
        for point in points[1:]:
            inner.lineTo(QPointF(point))
        inner.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(*COLOR_DIM))
        painter.drawPath(outer.subtracted(inner))
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_frame_rect(self, painter: QPainter, view_rect: QRectF, active: bool) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if active:
            painter.setPen(QPen(QColor(COLOR_ACCENT), 2, Qt.PenStyle.SolidLine))
            painter.drawRect(view_rect)
            return
        # 非裁剪模式下也要能看清"导出范围"。
        # 单色线在白底或深底上总有一种看不见，所以用"黑色实线 + 白色虚线"叠画，
        # 任何背景上都清晰（这是截图工具里常见的做法）。
        painter.setPen(QPen(QColor(20, 20, 24, 170), 1, Qt.PenStyle.SolidLine))
        painter.drawRect(view_rect)
        painter.setPen(QPen(QColor(255, 255, 255, 220), 1, Qt.PenStyle.DashLine))
        painter.drawRect(view_rect)

    def _draw_frame_polygon(self, painter: QPainter, points: list[QPointF], active: bool) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath(QPointF(points[0]))
        for point in points[1:]:
            path.lineTo(QPointF(point))
        path.closeSubpath()
        if active:
            painter.setPen(QPen(QColor(COLOR_ACCENT), 2, Qt.PenStyle.SolidLine))
            painter.drawPath(path)
            return
        painter.setPen(QPen(QColor(20, 20, 24, 170), 1, Qt.PenStyle.SolidLine))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(255, 255, 255, 220), 1, Qt.PenStyle.DashLine))
        painter.drawPath(path)

    def _draw_handle_boxes(self, painter: QPainter, points) -> None:
        half = HANDLE_SIZE / 2.0
        accent = QColor(COLOR_ACCENT)
        handle_fill = QColor(COLOR_HANDLE)
        for point in points:
            box = QRectF(point.x() - half, point.y() - half, HANDLE_SIZE, HANDLE_SIZE)
            painter.setBrush(handle_fill)
            painter.setPen(QPen(accent, 1))
            painter.drawRect(box)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_selection(self, painter: QPainter, transform: QTransform) -> None:
        selection = self.scene().selected_anno()
        if not selection:
            return
        accent = QColor(COLOR_ACCENT)
        handle_fill = QColor(COLOR_HANDLE)
        # 裁剪图片时，裁剪框自己就是唯一的参照物；再叠一层选中框会让用户
        # 分不清"哪个框才是裁剪范围"（实测真的会看错），所以把选中框让开。
        crop_target = None
        crop_tool = self._crop_tool()
        if crop_tool is not None:
            crop_target = crop_tool.image_target()

        for item in selection:
            if item is self._edit_item or item is crop_target:
                continue
            local = item.local_rect()
            corners = [
                item.mapToScene(local.topLeft()),
                item.mapToScene(local.topRight()),
                item.mapToScene(local.bottomRight()),
                item.mapToScene(local.bottomLeft()),
            ]
            polygon = [transform.map(point) for point in corners]
            painter.setPen(QPen(accent, 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for index in range(4):
                painter.drawLine(polygon[index], polygon[(index + 1) % 4])

        if len(selection) != 1:
            return

        item = selection[0]
        if item is self._edit_item or item is crop_target:
            return
        half = HANDLE_SIZE / 2.0
        for _name, local_point in item.handle_points().items():
            point = transform.map(item.mapToScene(local_point))
            box = QRectF(point.x() - half, point.y() - half, HANDLE_SIZE, HANDLE_SIZE)
            painter.setBrush(handle_fill)
            painter.setPen(QPen(accent, 1))
            painter.drawRect(box)

        rotate = self._rotate_handle_view(item, transform)
        if rotate is not None:
            painter.setPen(QPen(accent, 1))
            painter.drawLine(
                transform.map(item.mapToScene(QPointF(item.local_rect().center().x(), item.local_rect().top()))),
                rotate,
            )
            painter.setBrush(handle_fill)
            painter.drawEllipse(rotate, half, half)
