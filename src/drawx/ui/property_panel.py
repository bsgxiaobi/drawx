"""属性面板：上下文相关 —— 有选中对象就改对象，没有就改"新对象默认样式"。"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..const import PALETTE
from ..model.commands import ModifyCommand
from .icons import color_swatch

KEY_LABELS = {
    "stroke": "颜色",
    "strokeWidth": "线宽",
    "strokeStyle": "线型",
    "fill": "填充",
    "opacity": "不透明度",
    "fontSize": "字号",
    "bold": "粗体",
    "italic": "斜体",
    "head": "箭头",
    "block": "强度",
    "fontFamily": "字体",
}


class ColorPicker(QWidget):
    color_changed = Signal(str)

    def __init__(self, allow_transparent: bool = False, columns: int = 6, parent=None):
        super().__init__(parent)
        self._allow_transparent = allow_transparent
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        colors = list(PALETTE)
        if allow_transparent:
            colors = ["#00000000"] + colors
        for index, color in enumerate(colors):
            button = QToolButton(self)
            button.setFixedSize(22, 22)
            button.setIconSize(QSize(16, 16))
            button.setIcon(color_swatch(color, 16))
            button.setAutoRaise(True)
            button.setToolTip("无填充" if color == "#00000000" else color)
            button.clicked.connect(
                lambda _checked=False, c=color: self.color_changed.emit(c)
            )
            layout.addWidget(button, index // columns, index % columns)

        self._more = QPushButton("更多…", self)
        self._more.setFixedHeight(22)
        self._more.clicked.connect(self._pick_custom)
        layout.addWidget(self._more, (len(colors)) // columns + 1, 0, 1, columns)

    def _pick_custom(self) -> None:
        current = QColor(self._custom or "#ff3b30")
        color = QColorDialog.getColor(
            current, self, "选择颜色", QColorDialog.ColorDialogOption.ShowAlphaChannel
        )
        if color.isValid():
            self._custom = color.name(QColor.NameFormat.HexArgb)
            self.color_changed.emit(self._custom)

    _custom: str | None = None


def _set_preview(label: QLabel, color: str) -> None:
    qcolor = QColor(color)
    if qcolor.alpha() == 0:
        label.setStyleSheet(
            "border:1px solid #8a8a92; background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #3c3c42, stop:0.45 #3c3c42, stop:0.5 #ff5f56, stop:0.55 #ff5f56,"
            "stop:1 #3c3c42);"
        )
    else:
        label.setStyleSheet(
            f"border:1px solid #20202a; background:{qcolor.name(QColor.NameFormat.HexArgb)};"
        )


class PropertyPanel(QWidget):
    def __init__(self, view, parent=None) -> None:
        super().__init__(parent)
        self.view = view
        self._loading = False
        self._dragging = False
        self._image_drag_before: dict = {}
        self._build()
        scene = view.scene()
        scene.selection_changed.connect(self.sync)
        view.tool_changed.connect(lambda _name: self.sync())
        self.sync()

    # ---------------------------------------------------------- 构建
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # --- 描边 / 文字颜色
        self.stroke_group = QGroupBox("颜色")
        stroke_layout = QVBoxLayout(self.stroke_group)
        row = QHBoxLayout()
        self.stroke_preview = QLabel()
        self.stroke_preview.setFixedSize(24, 24)
        row.addWidget(self.stroke_preview)
        row.addWidget(QLabel("描边 / 文字"))
        row.addStretch(1)
        stroke_layout.addLayout(row)
        self.stroke_picker = ColorPicker()
        self.stroke_picker.color_changed.connect(
            lambda color: self._apply("stroke", color)
        )
        stroke_layout.addWidget(self.stroke_picker)
        layout.addWidget(self.stroke_group)

        # --- 线型与线宽
        self.shape_group = QGroupBox("线条")
        shape_layout = QGridLayout(self.shape_group)
        shape_layout.addWidget(QLabel("线宽"), 0, 0)
        self.width_slider = QSlider(Qt.Orientation.Horizontal)
        self.width_slider.setRange(1, 40)
        self.width_slider.valueChanged.connect(self._on_width_changed)
        shape_layout.addWidget(self.width_slider, 0, 1)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 40)
        self.width_spin.valueChanged.connect(self._on_width_changed)
        shape_layout.addWidget(self.width_spin, 0, 2)
        shape_layout.addWidget(QLabel("线型"), 1, 0)
        self.style_combo = QComboBox()
        self.style_combo.addItem("实线", "solid")
        self.style_combo.addItem("虚线", "dash")
        self.style_combo.addItem("点线", "dot")
        self.style_combo.currentIndexChanged.connect(
            lambda _i: self._apply("strokeStyle", self.style_combo.currentData())
        )
        shape_layout.addWidget(self.style_combo, 1, 1, 1, 2)
        layout.addWidget(self.shape_group)

        # --- 填充
        self.fill_group = QGroupBox("填充")
        fill_layout = QVBoxLayout(self.fill_group)
        fill_row = QHBoxLayout()
        self.fill_preview = QLabel()
        self.fill_preview.setFixedSize(24, 24)
        fill_row.addWidget(self.fill_preview)
        fill_layout.addLayout(fill_row)
        self.fill_picker = ColorPicker(allow_transparent=True)
        self.fill_picker.color_changed.connect(lambda color: self._apply("fill", color))
        fill_layout.addWidget(self.fill_picker)
        layout.addWidget(self.fill_group)

        # --- 不透明度
        self.opacity_group = QGroupBox("不透明度")
        opacity_layout = QHBoxLayout(self.opacity_group)
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(5, 100)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        opacity_layout.addWidget(self.opacity_slider)
        self.opacity_label = QLabel("100%")
        self.opacity_label.setFixedWidth(44)
        opacity_layout.addWidget(self.opacity_label)
        layout.addWidget(self.opacity_group)

        # --- 文字
        self.text_group = QGroupBox("文字")
        text_layout = QGridLayout(self.text_group)
        text_layout.addWidget(QLabel("字号"), 0, 0)
        self.font_slider = QSlider(Qt.Orientation.Horizontal)
        self.font_slider.setRange(8, 96)
        self.font_slider.valueChanged.connect(self._on_font_changed)
        text_layout.addWidget(self.font_slider, 0, 1)
        self.font_spin = QSpinBox()
        self.font_spin.setRange(8, 96)
        self.font_spin.valueChanged.connect(self._on_font_changed)
        text_layout.addWidget(self.font_spin, 0, 2)
        self.bold_check = QCheckBox("粗体")
        self.bold_check.toggled.connect(lambda v: self._apply("bold", bool(v)))
        text_layout.addWidget(self.bold_check, 1, 0, 1, 2)
        self.italic_check = QCheckBox("斜体")
        self.italic_check.toggled.connect(lambda v: self._apply("italic", bool(v)))
        text_layout.addWidget(self.italic_check, 1, 2)
        layout.addWidget(self.text_group)

        # --- 箭头
        self.arrow_group = QGroupBox("箭头")
        arrow_layout = QHBoxLayout(self.arrow_group)
        self.head_combo = QComboBox()
        self.head_combo.addItem("终点箭头", "end")
        self.head_combo.addItem("起点箭头", "start")
        self.head_combo.addItem("两端箭头", "both")
        self.head_combo.addItem("无箭头", "none")
        self.head_combo.currentIndexChanged.connect(
            lambda _i: self._apply("head", self.head_combo.currentData())
        )
        arrow_layout.addWidget(self.head_combo)
        layout.addWidget(self.arrow_group)

        # --- 马赛克 / 模糊
        self.patch_group = QGroupBox("强度")
        patch_layout = QHBoxLayout(self.patch_group)
        self.block_slider = QSlider(Qt.Orientation.Horizontal)
        self.block_slider.setRange(2, 60)
        self.block_slider.valueChanged.connect(self._on_block_changed)
        patch_layout.addWidget(self.block_slider)
        self.block_label = QLabel("12")
        self.block_label.setFixedWidth(34)
        patch_layout.addWidget(self.block_label)
        layout.addWidget(self.patch_group)

        # --- 图片图层（选中图片时才显示）
        self.image_group = QGroupBox("图片图层")
        image_layout = QGridLayout(self.image_group)
        self.image_info = QLabel("—")
        self.image_info.setWordWrap(True)
        self.image_info.setStyleSheet("color:#a0a0a8;")
        image_layout.addWidget(self.image_info, 0, 0, 1, 3)
        image_layout.addWidget(QLabel("不透明度"), 1, 0)
        self.image_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.image_opacity_slider.setRange(0, 100)
        self.image_opacity_slider.valueChanged.connect(self._on_image_opacity_changed)
        self.image_opacity_slider.sliderPressed.connect(self._on_image_opacity_pressed)
        self.image_opacity_slider.sliderReleased.connect(self._on_image_opacity_released)
        image_layout.addWidget(self.image_opacity_slider, 1, 1)
        self.image_opacity_label = QLabel("100%")
        self.image_opacity_label.setFixedWidth(42)
        image_layout.addWidget(self.image_opacity_label, 1, 2)
        self.btn_reset_crop = QPushButton("重置裁剪")
        self.btn_reset_crop.setToolTip("把这张图片恢复成完整原图（非破坏裁剪随时可回来）")
        self.btn_reset_crop.clicked.connect(self._reset_image_crop)
        image_layout.addWidget(self.btn_reset_crop, 2, 0, 1, 2)
        self.btn_original_size = QPushButton("原始大小")
        self.btn_original_size.setToolTip("按 1 源像素 = 1 画布单位显示（仍是矢量缩放，不损失原图）")
        self.btn_original_size.clicked.connect(self._image_original_size)
        image_layout.addWidget(self.btn_original_size, 2, 2)
        layout.addWidget(self.image_group)

        layout.addStretch(1)

        for slider in (
            self.width_slider,
            self.opacity_slider,
            self.font_slider,
            self.block_slider,
        ):
            slider.sliderPressed.connect(self._on_slider_pressed)
            slider.sliderReleased.connect(self._on_slider_released)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(container)
        scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        outer.addWidget(scroll)

    # ---------------------------------------------------------- 拖拽状态
    def _on_slider_pressed(self) -> None:
        self._dragging = True

    def _on_slider_released(self) -> None:
        self._dragging = False
        self.sync()

    # ---------------------------------------------------------- 图片图层
    def image_items(self) -> list:
        return [
            item
            for item in self.view.scene().selected_anno()
            if getattr(item, "TYPE", "") == "image"
        ]

    def _image_layers(self) -> list:
        scene = self.view.scene()
        layers: list = []
        for item in self.image_items():
            layer = scene.layer_of(item)
            if layer is not None and layer not in layers:
                layers.append(layer)
        return layers

    def _sync_image_group(self, items: list) -> None:
        images = [item for item in items if getattr(item, "TYPE", "") == "image"]
        self.image_group.setVisible(bool(images))
        if not images:
            return
        single = images[0] if len(images) == 1 else None
        if single is not None:
            natural = single.natural_size()
            rect = single.local_rect()
            text = f"原图 {natural[0]}×{natural[1]}"
            if not single.has_source():
                text = "原图缺失（工程文件里没有这张位图）"
            else:
                text += f"　显示 {rect.width():.0f}×{rect.height():.0f}"
                if (
                    abs(single.src_rect.width() - natural[0]) > 0.5
                    or abs(single.src_rect.height() - natural[1]) > 0.5
                ):
                    text += (
                        f"\n已裁剪保留 {single.src_rect.width():.0f}×"
                        f"{single.src_rect.height():.0f}"
                    )
            self.image_info.setText(text)
        else:
            self.image_info.setText(f"已选中 {len(images)} 张图片")
        self.btn_reset_crop.setEnabled(single is not None and single.has_source())
        self.btn_original_size.setEnabled(single is not None and single.has_source())

        layers = self._image_layers()
        if not self._dragging:
            opacity = int(round(float(layers[0].opacity) * 100)) if layers else 100
            self.image_opacity_slider.setValue(max(0, min(100, opacity)))
            self.image_opacity_label.setText(f"{opacity}%")
        self.image_opacity_slider.setEnabled(bool(layers))

    def _on_image_opacity_pressed(self) -> None:
        self._dragging = True
        self._image_drag_before = {
            layer: float(layer.opacity) for layer in self._image_layers()
        }

    def _on_image_opacity_changed(self, value: int) -> None:
        self.image_opacity_label.setText(f"{value}%")
        layers = self._image_layers()
        if not layers:
            return
        target = value / 100.0
        if self._dragging:
            # 拖动过程中直接改模型做实时预览，松手时才落一条可撤销命令
            if not self._image_drag_before:
                self._image_drag_before = {layer: float(layer.opacity) for layer in layers}
            scene = self.view.scene()
            for layer in layers:
                layer.opacity = target
                scene.apply_layer_state(layer)
            return
        self._push_layer_opacity(layers, target, None)

    def _on_image_opacity_released(self) -> None:
        self._dragging = False
        before = self._image_drag_before or {}
        self._image_drag_before = {}
        layers = self._image_layers()
        if not layers:
            return
        target = self.image_opacity_slider.value() / 100.0
        self._push_layer_opacity(layers, target, before)

    def _push_layer_opacity(self, layers: list, target: float, before: dict | None) -> None:
        from ..model.commands import CompoundCommand, LayerPropCommand

        scene = self.view.scene()
        commands = []
        for layer in layers:
            old = float(before.get(layer, layer.opacity)) if before else float(layer.opacity)
            if abs(old - target) < 1e-6:
                continue
            commands.append(
                LayerPropCommand(scene, layer, "opacity", old, target, "图层不透明度")
            )
        if not commands:
            return
        self.view.push_command(
            commands[0] if len(commands) == 1 else CompoundCommand(commands, "图层不透明度")
        )

    def _reset_image_crop(self) -> None:
        images = self.image_items()
        if len(images) != 1:
            return
        item = images[0]
        if not item.has_source():
            return
        from ..model.commands import ModifyCommand

        before = item.to_dict()
        item.reset_crop()
        after = item.to_dict()
        if before == after:
            return
        self.view.push_command(ModifyCommand([item], [before], [after], "重置图片裁剪"))
        self.sync()

    def _image_original_size(self) -> None:
        images = self.image_items()
        if len(images) != 1:
            return
        item = images[0]
        if not item.has_source():
            return
        from ..model.commands import ModifyCommand

        before = item.to_dict()
        item.set_display_scale(1.0, 1.0)
        after = item.to_dict()
        if before == after:
            return
        self.view.push_command(ModifyCommand([item], [before], [after], "图片原始大小"))
        self.sync()

    # ---------------------------------------------------------- 同步
    def _set_widgets(self, style: dict, items: list) -> None:
        self._loading = True
        try:
            stroke = str(style.get("stroke", "#FF3B30"))
            _set_preview(self.stroke_preview, stroke)

            width = int(round(float(style.get("strokeWidth", 4))))
            self.width_slider.setValue(max(1, min(40, width)))
            self.width_spin.setValue(max(1, min(40, width)))

            index = self.style_combo.findData(str(style.get("strokeStyle", "solid")))
            self.style_combo.setCurrentIndex(max(0, index))

            fill = str(style.get("fill", "#00000000"))
            _set_preview(self.fill_preview, fill)

            opacity = int(round(float(style.get("opacity", 1.0)) * 100))
            opacity = max(5, min(100, opacity))
            self.opacity_slider.setValue(opacity)
            self.opacity_label.setText(f"{opacity}%")

            font_size = int(round(float(style.get("fontSize", 20))))
            font_size = max(8, min(96, font_size))
            self.font_slider.setValue(font_size)
            self.font_spin.setValue(font_size)
            self.bold_check.setChecked(bool(style.get("bold", False)))
            self.italic_check.setChecked(bool(style.get("italic", False)))

            if items:
                first = items[0]
                head_index = self.head_combo.findData(getattr(first, "head", "end"))
                self.head_combo.setCurrentIndex(max(0, head_index))
                block = int(round(float(getattr(first, "block", 12.0))))
                block = max(2, min(60, block))
                self.block_slider.setValue(block)
                self.block_label.setText(str(block))
        finally:
            self._loading = False

    def sync(self) -> None:
        # 正在拖滑块时不要回写控件，否则会和用户的手打架
        if self._dragging:
            return
        items = self.view.scene().selected_anno()
        style = dict(self.view.default_style)
        if items:
            style.update(items[0].style)
        self._set_widgets(style, items)

        types = {item.TYPE for item in items}
        # 图片对象没有描边/填充/文字这些样式，把它们从"上下文判断"里剔掉，
        # 否则选中一张照片时面板会亮着一堆改了也没用的控件。
        styles = types - {"image"}
        has_selection = bool(items)
        has_image = "image" in types
        only_text = has_selection and styles == {"text"}
        has_text = (not has_selection) or "text" in styles
        has_line = (not has_selection) or bool(styles & {"line", "arrow", "freehand", "highlight"})
        has_shape = (not has_selection) or bool(styles & {"rect", "ellipse", "roundrect"})
        has_arrow = (not has_selection) or "arrow" in styles
        has_patch = (not has_selection) or bool(styles & {"mosaic", "blur"})

        self.stroke_group.setTitle("文字颜色" if only_text else "颜色")
        self.stroke_group.setEnabled(not has_image or bool(styles))
        self.text_group.setEnabled(has_text)
        self.shape_group.setEnabled(has_line or has_shape)
        self.fill_group.setEnabled(has_shape)
        # 图片的不透明度统一放在"图片图层"组里（改的是图层不透明度，一条命令）
        self.opacity_group.setEnabled(not has_image or bool(styles))
        self.arrow_group.setEnabled(has_arrow)
        self.patch_group.setEnabled(has_patch)
        self._sync_image_group(items)

    # ---------------------------------------------------------- 应用
    def _on_width_changed(self, value: int) -> None:
        self._apply("strokeWidth", float(value), merge=True)

    def _on_opacity_changed(self, value: int) -> None:
        self.opacity_label.setText(f"{value}%")
        self._apply("opacity", value / 100.0, merge=True)

    def _on_font_changed(self, value: int) -> None:
        self._apply("fontSize", float(value), merge=True)

    def _on_block_changed(self, value: int) -> None:
        self.block_label.setText(str(value))
        self._apply("block", float(value), merge=True)

    def _set_item_value(self, item, key: str, value) -> None:
        if key == "head":
            item.head = value
            item.update()
        elif key == "block":
            item.block = float(value)
            item.update()
        else:
            item.set_style_value(key, value)

    def _apply(self, key: str, value, merge: bool = False) -> None:
        if self._loading:
            return
        self.view.default_style[key] = value
        # 记下"用户显式设过这个键"，工具自带的偏好默认值就不再覆盖它
        self.view.user_style_keys.add(key)
        items = self.view.scene().selected_anno()
        if not items:
            self.sync()
            return

        old = [item.to_dict() for item in items]
        for item in items:
            self._set_item_value(item, key, value)
        new = [item.to_dict() for item in items]
        if old == new:
            return
        self.view.push_command(
            ModifyCommand(
                items,
                old,
                new,
                f"修改{KEY_LABELS.get(key, key)}",
                mergeable=merge,
                merge_key=(key, tuple(id(item) for item in items)),
            )
        )
        self._set_widgets(dict(items[0].style), items)
