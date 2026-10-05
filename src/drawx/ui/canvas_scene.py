"""画布场景：持有文档、撤销栈、图层与全部对象。

场景是**图层结构的唯一执行者**：谁在哪个图层、绘制顺序是什么、锁定图层能不能选，
全部在这里落地。视图与工具只调用这里的方法，不直接碰 ``doc.layers``。
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Signal
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene

from ..const import UNDO_LIMIT
from ..items.base import new_id
from ..items.factory import create_item
from ..model.document import Document
from ..model.layers import Layer, new_layer_id


class CanvasScene(QGraphicsScene):
    """场景里存放的是**各图层的对象**，画布底色由视图的 drawBackground 绘制。"""

    selection_changed = Signal()
    content_changed = Signal()
    #: 图层结构或自身属性变化（增删/排序/改名）——面板重建
    layers_changed = Signal()
    #: 单个图层的显隐/锁定/不透明度变化——面板只更新那一行
    layer_state_changed = Signal(object)
    #: 某个图层里的对象变化——面板只更新那一行
    layer_content_changed = Signal(object)
    text_edit_started = Signal(object)
    text_edit_finished = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.doc = Document()
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(UNDO_LIMIT)
        self.setSceneRect(QRectF(0.0, 0.0, 1280.0, 800.0))
        # Qt 内建选中信号 -> 我们的信号，视图据此重绘选择框
        self.selectionChanged.connect(self.selection_changed)
        # 撤销/重做会把快照里的旧 z 写回来，必须立刻按图层顺序重排一次，
        # 否则"撤销一次移动"可能顺手把对象搬到别的图层上面去。
        self.undo_stack.indexChanged.connect(self._on_stack_index_changed)

    def _on_stack_index_changed(self, _index: int) -> None:
        self.reflow_z()
        self.refresh_scene_rect()

    # ============================================================== 图层
    def layers(self) -> list[Layer]:
        return list(self.doc.layers)

    def layer_of(self, item) -> Layer | None:
        for layer in self.doc.layers:
            if item in layer.items:
                return layer
        return None

    def layer_by_id(self, layer_id: str | None) -> Layer | None:
        return self.doc.layer_by_id(layer_id)

    def active_layer(self) -> Layer | None:
        """当前活动图层；活动图层被删或被锁时自动退到最上面的可用标注图层。"""
        layer = self.doc.layer_by_id(self.doc.active_layer_id)
        if layer is not None:
            return layer
        return None

    def default_annotation_layer(self) -> Layer:
        return self.doc.default_annotation_layer()

    def set_active_layer(self, layer: Layer | None, sync_selection: bool = True) -> None:
        layer_id = layer.id if layer is not None else None
        changed = self.doc.active_layer_id != layer_id
        self.doc.active_layer_id = layer_id
        if layer is not None and sync_selection:
            picked = [item for item in layer.items if item.isSelected()]
            if not picked and layer.items:
                self.set_selection([layer.items[0]])
        if changed:
            self.layers_changed.emit()

    def add_layer(self, layer: Layer, index: int | None = None) -> None:
        """把图层接进文档（对象一并入场）。不推命令，命令层负责调用。"""
        if index is None:
            index = 0
        index = max(0, min(len(self.doc.layers), int(index)))
        self.doc.layers.insert(index, layer)
        if self.doc.layer_by_id(self.doc.active_layer_id) is None:
            self.doc.active_layer_id = layer.id
        self.apply_layer_state(layer)
        for item in layer.items:
            if item.scene() is not self:
                self.addItem(item)
        self.reflow_z()
        self.refresh_scene_rect()
        self.layers_changed.emit()
        self.content_changed.emit()

    def remove_layer(self, layer: Layer) -> None:
        """把图层摘出文档（对象留在内存里，撤销时原样放回）。"""
        if layer not in self.doc.layers:
            return
        self._deselect_quietly(layer.items)
        for item in layer.items:
            if item.scene() is self:
                self.removeItem(item)
        self.doc.layers.remove(layer)
        if self.doc.active_layer_id == layer.id:
            self.doc.active_layer_id = (
                self.doc.layers[0].id if self.doc.layers else None
            )
        self.reflow_z()
        self.refresh_scene_rect()
        self.layers_changed.emit()
        self.content_changed.emit()

    def move_layer(self, layer: Layer, index: int) -> None:
        """调整图层顺序（index 是目标行号，0 = 最顶层）。"""
        if layer not in self.doc.layers:
            return
        index = max(0, min(len(self.doc.layers) - 1, int(index)))
        self.doc.layers.remove(layer)
        self.doc.layers.insert(index, layer)
        self.reflow_z()
        self.layers_changed.emit()
        self.content_changed.emit()

    def layer_index(self, layer: Layer) -> int:
        try:
            return self.doc.layers.index(layer)
        except ValueError:
            return -1

    def clone_layer(self, layer: Layer) -> Layer:
        """复制一个图层（对象也复制一份，图片图层共用同一份原图，不额外占内存）。"""
        copy = Layer(
            id=new_layer_id(layer.kind),
            name=self.unique_layer_name(f"{layer.name} 副本"),
            kind=layer.kind,
            visible=layer.visible,
            locked=False,
            opacity=layer.opacity,
            extra=dict(layer.extra),
        )
        for item in layer.items:
            data = item.to_dict()
            data["id"] = new_id()
            clone = create_item(data)
            if clone is None:
                continue
            source = getattr(item, "source", None)
            if source is not None:
                clone.source = source
                clone.asset_id = f"img-{clone.id}"
            clone.moveBy(12.0, 12.0)
            clone._own_visible = getattr(item, "_own_visible", True)
            copy.items.append(clone)
        copy.thumb = layer.thumb
        return copy

    def unique_layer_name(self, name: str) -> str:
        used = {layer.name for layer in self.doc.layers}
        if name not in used:
            return name
        index = 2
        while f"{name} ({index})" in used:
            index += 1
        return f"{name} ({index})"

    # ---------------------------------------------------------- 图层状态
    def apply_layer_state(self, layer: Layer | None = None) -> None:
        """把图层的 显隐 / 锁定 / 不透明度 落到它承载的对象上。

        只传一个图层时走轻量信号：拖不透明度滑块会连发几十次，整棵树重建会明显卡顿。
        """
        targets = [layer] if layer is not None else self.doc.layers
        for target in targets:
            for item in target.items:
                item.setVisible(bool(target.visible) and bool(getattr(item, "_own_visible", True)))
                item.setFlag(
                    QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, not target.locked
                )
                item.set_layer_opacity(target.opacity)
        if layer is None:
            self.layers_changed.emit()
        else:
            self.layer_state_changed.emit(layer)

    def is_locked(self, item) -> bool:
        layer = self.layer_of(item)
        return bool(layer is not None and layer.locked)

    # ============================================================== 对象集合
    def anno_items(self) -> list:
        """按**绘制顺序**（底层在前）返回全部对象。"""
        result: list = []
        for layer in reversed(self.doc.layers):
            result.extend(layer.items)
        return result

    def annotation_items(self) -> list:
        return [item for item in self.anno_items() if getattr(item, "TYPE", "") != "image"]

    def selectable_anno(self) -> list:
        """可以被点选/框选的对象（锁定图层里的排除掉）。"""
        return [
            item
            for item in self.anno_items()
            if not self.is_locked(item) and item.isVisible()
        ]

    def selectable_annotations(self) -> list:
        """只含矢量标注（不含图片图层）。

        文字标注、矩形这些是"编辑对象"；图片图层更像"底稿"，一张就铺满整个画布。
        所以框选 / 全选只针对标注，图片请在图层里选或在画布上直接点选拖动。
        """
        return [
            item
            for item in self.selectable_anno()
            if getattr(item, "TYPE", "") != "image"
        ]

    def selectable_images(self) -> list:
        return [
            item
            for item in self.selectable_anno()
            if getattr(item, "TYPE", "") == "image"
        ]

    def create_item(self, data: dict, assets: dict | None = None):
        return create_item(data, assets)

    def add_anno(self, item, layer: Layer | None = None) -> None:
        if self.layer_of(item) is not None:
            return
        target = layer if layer is not None else self.default_annotation_layer()
        target.items.append(item)
        item.set_layer_opacity(target.opacity)
        item.setVisible(bool(target.visible) and bool(getattr(item, "_own_visible", True)))
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, not target.locked)
        if item.scene() is not self:
            self.addItem(item)
        self.reflow_z()
        self.refresh_scene_rect()
        self.layer_content_changed.emit(target)
        self.content_changed.emit()

    def remove_anno(self, item) -> None:
        layer = self.layer_of(item)
        if layer is None:
            return
        layer.items.remove(item)
        if item.scene() is self:
            self.removeItem(item)
        self.reflow_z()
        self.refresh_scene_rect()
        self.layer_content_changed.emit(layer)
        self.content_changed.emit()

    def clear_anno(self) -> None:
        """清空所有图层里的对象，但保留图层本身。"""
        for layer in self.doc.layers:
            for item in list(layer.items):
                if item.scene() is self:
                    self.removeItem(item)
            layer.items = []
        self.reflow_z()
        self.refresh_scene_rect()
        self.layers_changed.emit()
        self.content_changed.emit()

    def clear_layers(self) -> None:
        """连图层一起清空（新建/打开文档时用）。"""
        self.clearSelection()
        for layer in list(self.doc.layers):
            for item in list(layer.items):
                if item.scene() is self:
                    self.removeItem(item)
            layer.items = []
        self.doc.layers = []
        self.doc.active_layer_id = None
        self.refresh_scene_rect()
        self.layers_changed.emit()
        self.content_changed.emit()

    def adopt_document(self, doc, layers: list) -> None:
        """整体接管一份刚读进来的文档（打开工程用）。"""
        self.clear_layers()
        doc.layers = list(layers)
        self.doc = doc
        for layer in doc.layers:
            for item in layer.items:
                if item.scene() is not self:
                    self.addItem(item)
        if doc.active_layer_id is None and doc.layers:
            doc.active_layer_id = doc.layers[0].id
        self.apply_layer_state()
        self.reflow_z()
        self.refresh_scene_rect()
        self.layers_changed.emit()
        self.content_changed.emit()

    def next_z(self) -> float:
        items = self.anno_items()
        if not items:
            return 1.0
        return max(item.zValue() for item in items) + 1.0

    def reflow_z(self) -> None:
        """按图层顺序 + 图层内顺序重新分配 z（1, 2, 3 …）。

        z 是**派生值**：只有图层顺序与图层内追加顺序是真相。这样任何快照里的
        旧 z 都不会造成"对象偷偷换层"。
        """
        z = 0.0
        for layer in reversed(self.doc.layers):
            for item in layer.items:
                z += 1.0
                if abs(item.zValue() - z) > 1e-9:
                    item.setZValue(z)

    def backdrop_signature(self, z_limit: float) -> tuple:
        """``z_limit`` 以下所有图片图层的几何/状态指纹，用于马赛克采样缓存。"""
        parts: list = []
        for layer in reversed(self.doc.layers):
            for item in layer.items:
                if getattr(item, "TYPE", "") != "image":
                    continue
                if item.zValue() >= z_limit or not item.isVisible():
                    continue
                rect = item.local_rect()
                src = item.src_rect
                parts.append(
                    (
                        id(item),
                        round(layer.opacity, 3),
                        round(item.pos().x(), 1),
                        round(item.pos().y(), 1),
                        round(rect.width(), 2),
                        round(rect.height(), 2),
                        round(item.rotation(), 2),
                        round(src.x(), 1),
                        round(src.y(), 1),
                        round(src.width(), 1),
                        round(src.height(), 1),
                    )
                )
        return tuple(parts)

    # ============================================================== 选中
    def selected_anno(self) -> list:
        return [
            item
            for layer in self.doc.layers
            for item in layer.items
            if item.isSelected()
        ]

    def set_selection(self, items) -> None:
        wanted = list(items or [])
        for item in self.anno_items():
            item.setSelected(item in wanted)
        self.selection_changed.emit()

    def select_all(self) -> None:
        self.set_selection(self.selectable_annotations())

    def _deselect_quietly(self, items) -> None:
        for item in items:
            if item.isSelected():
                item.setSelected(False)

    # ============================================================== 其他
    def refresh_scene_rect(self) -> None:
        rect = self.doc.canvas_rect()
        extra = self.itemsBoundingRect()
        if not extra.isNull():
            rect = rect.united(extra)
        self.setSceneRect(rect.adjusted(-80.0, -80.0, 80.0, 80.0))

    def canvas_bounds(self) -> QRectF:
        """所有可见对象 + 画布的外接矩形（"适应内容"用）。"""
        rect = self.itemsBoundingRect()
        return rect

    def mark_modified(self) -> None:
        self.doc.modified = True
        self.content_changed.emit()
