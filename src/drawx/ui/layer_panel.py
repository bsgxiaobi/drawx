"""图层面板。

一行一个图层，**从上到下就是绘制顺序的从高到低**（与 ``Document.layers`` 完全一致，
不做任何反序换算）。每行三个格子：

* 名称格：缩略图 + 名字（双击改名）
* 眼睛格：单击切换显示 / 隐藏
* 锁格：单击切换锁定 / 解锁（锁定后画布上点不动这个图层，防误操作）

面板是**纯命令层**：所有修改都走 ``view.push_command``，所以图层增删排序、
改名、显隐、锁定、不透明度全部可撤销 —— 这一点和属性面板保持一致。
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QSlider,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..model.commands import AddLayerCommand, LayerPropCommand, MoveLayerCommand, RemoveLayerCommand
from ..model.layers import KIND_ANNOTATION, KIND_IMAGE, Layer, new_layer_id
from .dialogs import ask_text
from .icons import tool_icon

KIND_LABELS = {KIND_IMAGE: "图片图层", KIND_ANNOTATION: "标注图层"}

#: 图层行的角色（把 Layer 对象挂在 item 上）
LAYER_ROLE = Qt.ItemDataRole.UserRole + 1


class _LayerTree(QTreeWidget):
    """支持拖动排序的树；拖动只上报"从哪一行拖到哪一行"，实际排序由命令完成。"""

    row_dropped = Signal(int, int)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt 接口
        source = self.currentItem()
        from_row = self.indexOfTopLevelItem(source) if source is not None else -1
        index = self.indexAt(event.position().toPoint())
        position = self.dropIndicatorPosition()
        if index.isValid():
            to_row = index.row()
            if position == QAbstractItemView.DropIndicatorPosition.BelowItem:
                to_row += 1
        else:
            to_row = self.topLevelItemCount()
        # 目标是"移除源行之后"的下标，与 CanvasScene.move_layer 的语义一致
        if from_row >= 0 and from_row < to_row:
            to_row -= 1
        # 不让 Qt 自己搬行：面板收到信号后会用命令重建，避免两套顺序打架
        event.setDropAction(Qt.DropAction.IgnoreAction)
        event.accept()
        if from_row >= 0 and 0 <= to_row < max(1, self.topLevelItemCount()) and to_row != from_row:
            self.row_dropped.emit(from_row, to_row)


class LayerPanel(QWidget):
    #: 面板要求主窗口弹出"导入图片"对话框（创建图片图层需要文件对话框）
    request_import_image = Signal()

    def __init__(self, view, parent=None) -> None:
        super().__init__(parent)
        self.view = view
        self.scene = view.scene()
        self._loading = False
        self._dragging = False
        self._build()
        self.scene.layers_changed.connect(self.rebuild)
        self.scene.layer_state_changed.connect(self._on_layer_state_changed)
        self.scene.layer_content_changed.connect(self._on_layer_content_changed)
        self.scene.selection_changed.connect(self._on_scene_selection_changed)
        self.rebuild()

    # ============================================================== 构建
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        buttons = QHBoxLayout()
        buttons.setSpacing(3)
        self.btn_add_image = self._tool_button("layer_add", "新建图片图层（导入图片）", self.request_import_image.emit)
        self.btn_add_anno = self._tool_button("layers", "新建标注图层", self.add_annotation_layer)
        self.btn_duplicate = self._tool_button("layer_dup", "复制图层 (Ctrl+J)", self.duplicate_layer)
        self.btn_delete = self._tool_button("delete", "删除图层", self.delete_layer)
        self.btn_up = self._tool_button("move_up", "上移一层", lambda: self.move_layer(-1))
        self.btn_down = self._tool_button("move_down", "下移一层", lambda: self.move_layer(1))
        for button in (
            self.btn_add_image,
            self.btn_add_anno,
            self.btn_duplicate,
            self.btn_delete,
            self.btn_up,
            self.btn_down,
        ):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.tree = _LayerTree(self)
        self.tree.setColumnCount(3)
        self.tree.header().setVisible(False)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setIconSize(QSize(30, 22))
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, 28)
        self.tree.setColumnWidth(2, 28)
        self.tree.itemSelectionChanged.connect(self._on_row_changed)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.customContextMenuRequested.connect(self._show_menu)
        self.tree.row_dropped.connect(self._on_row_dropped)
        layout.addWidget(self.tree, 1)

        opacity_row = QHBoxLayout()
        opacity_row.setSpacing(6)
        opacity_row.addWidget(QLabel("不透明度"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self.opacity_slider.sliderPressed.connect(lambda: setattr(self, "_dragging", True))
        self.opacity_slider.sliderReleased.connect(self._on_opacity_released)
        opacity_row.addWidget(self.opacity_slider, 1)
        self.opacity_label = QLabel("100%")
        self.opacity_label.setFixedWidth(42)
        opacity_row.addWidget(self.opacity_label)
        layout.addLayout(opacity_row)
        self.setMinimumHeight(180)

    def _tool_button(self, icon_name: str, tip: str, slot) -> QToolButton:
        button = QToolButton(self)
        button.setIcon(tool_icon(icon_name))
        button.setIconSize(QSize(18, 18))
        button.setAutoRaise(True)
        button.setToolTip(tip)
        button.clicked.connect(lambda _checked=False: slot())
        return button

    # ============================================================== 刷新
    def current_layer(self) -> Layer | None:
        item = self.tree.currentItem()
        if item is None:
            return None
        layer = item.data(0, LAYER_ROLE)
        return layer if isinstance(layer, Layer) else None

    def rebuild(self) -> None:
        """按文档里的图层顺序重建整棵树（顶层在最上面）。"""
        self._loading = True
        try:
            active = self.scene.active_layer()
            self.tree.clear()
            for layer in self.scene.layers():
                self.tree.addTopLevelItem(self._make_item(layer))
            if active is not None:
                for row in range(self.tree.topLevelItemCount()):
                    item = self.tree.topLevelItem(row)
                    if item.data(0, LAYER_ROLE) is active:
                        item.setSelected(True)
                        self.tree.setCurrentItem(item)
                        break
            self._sync_opacity(active)
            self._update_buttons()
        finally:
            self._loading = False

    def _make_item(self, layer: Layer) -> QTreeWidgetItem:
        item = QTreeWidgetItem()
        item.setData(0, LAYER_ROLE, layer)
        item.setText(0, layer.name)
        item.setIcon(0, self._thumbnail(layer))
        tooltip = f"{KIND_LABELS.get(layer.kind, layer.kind)}「{layer.name}」"
        if layer.is_image:
            image_item = layer.image_item()
            if image_item is not None:
                natural = image_item.natural_size()
                tooltip += (
                    f"\n原图 {natural[0]}×{natural[1]}"
                    f"　源图保留区 {image_item.src_rect.width():.0f}×"
                    f"{image_item.src_rect.height():.0f}"
                )
                if image_item.source_name:
                    tooltip += f"\n来源：{image_item.source_name}"
        else:
            tooltip += f"\n{len(layer.items)} 个标注对象"
        tooltip += f"\n不透明度 {round(layer.opacity * 100)}%"
        item.setToolTip(0, tooltip)
        item.setIcon(1, tool_icon("eye" if layer.visible else "eye_off"))
        item.setToolTip(1, "显示 / 隐藏")
        item.setIcon(2, tool_icon("lock" if layer.locked else "unlock"))
        item.setToolTip(2, "锁定 / 解锁（锁定后画布上选不中、拖不动它；面板里的操作照常）")
        if not layer.visible:
            item.setForeground(0, Qt.GlobalColor.gray)
        return item

    def _thumbnail(self, layer: Layer) -> QPixmap:
        """行缩略图：图片图层用真实像素，标注图层用类型图标。"""
        if layer.is_image:
            image_item = layer.image_item()
            source = getattr(image_item, "source", None) if image_item is not None else None
            if source is not None and not source.isNull():
                if layer.thumb is None:
                    layer.thumb = QPixmap.fromImage(
                        source.scaled(
                            30,
                            24,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                return layer.thumb
        return tool_icon("layers" if not layer.is_image else "image").pixmap(24, 24)

    def _sync_opacity(self, layer: Layer | None) -> None:
        if self._dragging:
            return
        if layer is None:
            self.opacity_slider.setEnabled(False)
            self.opacity_label.setText("—")
            return
        # 锁定只挡"画布上的交互"（选不中、拖不动），面板里的显式操作照常可用
        self.opacity_slider.setEnabled(True)
        value = int(round(float(layer.opacity) * 100))
        self.opacity_slider.setValue(max(0, min(100, value)))
        self.opacity_label.setText(f"{value}%")

    def _update_buttons(self) -> None:
        layer = self.current_layer()
        has = layer is not None
        self.btn_duplicate.setEnabled(has)
        self.btn_delete.setEnabled(has)
        index = self.scene.layer_index(layer) if has else -1
        self.btn_up.setEnabled(has and index > 0)
        self.btn_down.setEnabled(has and 0 <= index < len(self.scene.layers()) - 1)

    def _row_of(self, layer: Layer) -> QTreeWidgetItem | None:
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            if item.data(0, LAYER_ROLE) is layer:
                return item
        return None

    def _on_layer_state_changed(self, layer) -> None:
        """显隐/锁定/不透明度变了：只刷新这一行，不重建整棵树。"""
        item = self._row_of(layer) if isinstance(layer, Layer) else None
        if item is None:
            return
        self._loading = True
        try:
            fresh = self._make_item(layer)
            item.setIcon(1, fresh.icon(1))
            item.setIcon(2, fresh.icon(2))
            item.setToolTip(0, fresh.toolTip(0))
            item.setForeground(0, fresh.foreground(0))
            if layer is self.current_layer():
                self._sync_opacity(layer)
                self._update_buttons()
        finally:
            self._loading = False

    def _on_layer_content_changed(self, layer) -> None:
        """图层里的对象变了：只刷新那一行（缩略图/对象数都靠 tooltip）。"""
        item = self._row_of(layer) if isinstance(layer, Layer) else None
        if item is None:
            return
        self._loading = True
        try:
            fresh = self._make_item(layer)
            item.setIcon(0, fresh.icon(0))
            item.setToolTip(0, fresh.toolTip(0))
        finally:
            self._loading = False

    # ============================================================== 交互
    def _on_row_changed(self) -> None:
        if self._loading:
            return
        layer = self.current_layer()
        self._sync_opacity(layer)
        self._update_buttons()
        if layer is not None and self.scene.active_layer() is not layer:
            self.scene.set_active_layer(layer, sync_selection=True)

    def _on_scene_selection_changed(self) -> None:
        """画布上选中了什么，就把那个图层设为活动图层（像 PS 一样）。"""
        selection = self.scene.selected_anno()
        if not selection:
            return
        layer = self.scene.layer_of(selection[0])
        if layer is None or self.scene.active_layer() is layer:
            return
        self._loading = True
        try:
            self.scene.doc.active_layer_id = layer.id
            for row in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(row)
                if item.data(0, LAYER_ROLE) is layer:
                    item.setSelected(True)
                    self.tree.setCurrentItem(item)
                    break
            self._sync_opacity(layer)
            self._update_buttons()
        finally:
            self._loading = False

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        layer = item.data(0, LAYER_ROLE)
        if not isinstance(layer, Layer):
            return
        if column == 1:
            self.toggle_visible(layer)
        elif column == 2:
            self.toggle_locked(layer)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        layer = item.data(0, LAYER_ROLE)
        if isinstance(layer, Layer) and column == 0:
            self.rename_layer(layer)

    def _on_row_dropped(self, from_row: int, to_row: int) -> None:
        layers = self.scene.layers()
        if not (0 <= from_row < len(layers)):
            return
        layer = layers[from_row]
        if to_row == from_row:
            return
        self.view.push_command(MoveLayerCommand(self.scene, layer, to_row))
        self.scene.set_active_layer(layer, sync_selection=False)

    def _show_menu(self, position) -> None:
        item = self.tree.itemAt(position)
        layer = item.data(0, LAYER_ROLE) if item is not None else None
        menu = QMenu(self)
        if isinstance(layer, Layer):
            menu.addAction("重命名…", lambda: self.rename_layer(layer))
            menu.addAction("复制图层", lambda: self.duplicate_layer(layer))
            menu.addSeparator()
            menu.addAction("显示" if not layer.visible else "隐藏", lambda: self.toggle_visible(layer))
            menu.addAction("解锁" if layer.locked else "锁定", lambda: self.toggle_locked(layer))
            menu.addSeparator()
            menu.addAction("上移一层", lambda: self.move_layer(-1, layer))
            menu.addAction("下移一层", lambda: self.move_layer(1, layer))
            menu.addAction("置顶", lambda: self.move_to(0, layer))
            menu.addAction("置底", lambda: self.move_to(len(self.scene.layers()) - 1, layer))
            menu.addSeparator()
            if layer.is_image:
                menu.addAction("重置图片裁剪", lambda: self.reset_image_crop(layer))
            menu.addAction("删除图层", lambda: self.delete_layer(layer))
        else:
            menu.addAction("新建标注图层", self.add_annotation_layer)
            menu.addAction("新建图片图层…", lambda: self.request_import_image.emit())
        menu.exec(self.tree.viewport().mapToGlobal(position))

    # ============================================================== 操作
    def add_annotation_layer(self) -> None:
        layer = Layer(id=new_layer_id(KIND_ANNOTATION), name=self.scene.unique_layer_name("标注图层"))
        self.view.push_command(AddLayerCommand(self.scene, layer, 0, "新建标注图层"))
        self.scene.set_active_layer(layer, sync_selection=False)

    def duplicate_layer(self, layer: Layer | None = None) -> None:
        layer = layer or self.current_layer()
        if layer is None:
            return
        clone = self.scene.clone_layer(layer)
        index = max(0, self.scene.layer_index(layer))
        self.view.push_command(AddLayerCommand(self.scene, clone, index, "复制图层"))
        self.scene.set_active_layer(clone, sync_selection=False)

    def delete_layer(self, layer: Layer | None = None) -> None:
        layer = layer or self.current_layer()
        if layer is None:
            return
        self.view.push_command(RemoveLayerCommand(self.scene, layer))
        active = self.scene.active_layer()
        if active is not None:
            self.scene.set_active_layer(active, sync_selection=False)

    def move_layer(self, offset: int, layer: Layer | None = None) -> None:
        layer = layer or self.current_layer()
        if layer is None:
            return
        index = self.scene.layer_index(layer)
        target = index + offset
        if index < 0 or not (0 <= target < len(self.scene.layers())):
            return
        self.view.push_command(MoveLayerCommand(self.scene, layer, target))
        self.scene.set_active_layer(layer, sync_selection=False)

    def move_to(self, index: int, layer: Layer | None = None) -> None:
        layer = layer or self.current_layer()
        if layer is None:
            return
        index = max(0, min(len(self.scene.layers()) - 1, index))
        if index == self.scene.layer_index(layer):
            return
        self.view.push_command(MoveLayerCommand(self.scene, layer, index))
        self.scene.set_active_layer(layer, sync_selection=False)

    def toggle_visible(self, layer: Layer | None = None) -> None:
        layer = layer or self.current_layer()
        if layer is None:
            return
        self.view.push_command(
            LayerPropCommand(
                self.scene,
                layer,
                "visible",
                layer.visible,
                not layer.visible,
                "隐藏图层" if layer.visible else "显示图层",
            )
        )

    def toggle_locked(self, layer: Layer | None = None) -> None:
        layer = layer or self.current_layer()
        if layer is None:
            return
        if not layer.visible and not layer.locked:
            # 隐藏着的图层被锁定看不出来，先让它可见更符合直觉
            self.toggle_visible(layer)
        self.view.push_command(
            LayerPropCommand(
                self.scene,
                layer,
                "locked",
                layer.locked,
                not layer.locked,
                "锁定图层" if not layer.locked else "解锁图层",
            )
        )

    def rename_layer(self, layer: Layer | None = None) -> None:
        layer = layer or self.current_layer()
        if layer is None:
            return
        name, ok = ask_text(self, "重命名图层", "图层名称：", layer.name)
        name = (name or "").strip()
        if not ok or not name or name == layer.name:
            return
        self.view.push_command(
            LayerPropCommand(self.scene, layer, "name", layer.name, name, "重命名图层")
        )

    def reset_image_crop(self, layer: Layer | None = None) -> None:
        layer = layer or self.current_layer()
        if layer is None or not layer.is_image:
            return
        item = layer.image_item()
        if item is None or not item.has_source():
            return
        before = item.to_dict()
        item.reset_crop()
        after = item.to_dict()
        if before == after:
            return
        from ..model.commands import ModifyCommand

        self.view.push_command(ModifyCommand([item], [before], [after], "重置图片裁剪"))

    def _on_opacity_changed(self, value: int) -> None:
        self.opacity_label.setText(f"{value}%")
        if self._loading:
            return
        layer = self.current_layer()
        if layer is None:
            return
        target = value / 100.0
        if abs(float(layer.opacity) - target) < 1e-6:
            return
        self.view.push_command(
            LayerPropCommand(
                self.scene,
                layer,
                "opacity",
                float(layer.opacity),
                target,
                "图层不透明度",
            )
        )

    def _on_opacity_released(self) -> None:
        self._dragging = False
        self._sync_opacity(self.current_layer())
