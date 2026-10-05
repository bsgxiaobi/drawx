"""对话框：导出设置，以及所有标准提示框的统一入口。

**为什么提示框要包一层**：Qt 自己造的标准按钮文案来自 `qtbase_zh_CN.qm`，
装了翻译才是中文。虽然 `app.install_translations()` 已经装了，但打包（PyInstaller
onefile）时 `.qm` 有可能没被一起带进去，那时按钮又会变回 `Save / Discard / Cancel`。
所以**我们自己弹的框一律再显式写一遍中文文案**，不依赖打包行为；
顺便把"另存为确认"的措辞从 Qt 的「丢弃」改成国内更通用的「不保存」。
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

FORMATS = [
    ("PNG（无损，支持透明）", ".png"),
    ("JPEG（体积小，白底）", ".jpg"),
    ("WebP（体积最小）", ".webp"),
    ("BMP（无压缩）", ".bmp"),
]

SCALES = [("1x（原始尺寸）", 1.0), ("2x（2 倍清晰）", 2.0), ("3x", 3.0), ("4x", 4.0)]

#: 标准按钮的中文文案（比 Qt 自带翻译更贴合国内习惯：Discard 用"不保存"）
BUTTON_TEXTS = {
    QMessageBox.StandardButton.Ok: "确定",
    QMessageBox.StandardButton.Save: "保存",
    QMessageBox.StandardButton.Discard: "不保存",
    QMessageBox.StandardButton.Cancel: "取消",
    QMessageBox.StandardButton.Yes: "是",
    QMessageBox.StandardButton.No: "否",
    QMessageBox.StandardButton.Close: "关闭",
    QMessageBox.StandardButton.Apply: "应用",
    QMessageBox.StandardButton.Reset: "重置",
    QMessageBox.StandardButton.Help: "帮助",
}


def localize_buttons(box: QMessageBox) -> QMessageBox:
    """把提示框上的标准按钮改写成中文，返回同一个 box 便于链式调用。"""
    for button in box.buttons():
        text = BUTTON_TEXTS.get(box.standardButton(button))
        if text:
            button.setText(text)
    return box


def message_box(
    parent,
    title: str,
    text: str,
    icon: QMessageBox.Icon = QMessageBox.Icon.Information,
    buttons=QMessageBox.StandardButton.Ok,
    default=None,
) -> QMessageBox:
    """造一个中文按钮的提示框（**不** exec，调用方自己决定怎么显示）。"""
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(buttons)
    if default is not None:
        box.setDefaultButton(default)
    return localize_buttons(box)


def info(parent, title: str, text: str) -> None:
    message_box(parent, title, text, QMessageBox.Icon.Information).exec()


def warn(parent, title: str, text: str) -> None:
    message_box(parent, title, text, QMessageBox.Icon.Warning).exec()


def error(parent, title: str, text: str) -> None:
    message_box(parent, title, text, QMessageBox.Icon.Critical).exec()


def about(parent, title: str, text: str) -> None:
    from .appicon import app_icon

    box = message_box(parent, title, text, QMessageBox.Icon.Information)
    box.setIconPixmap(app_icon().pixmap(64, 64))
    box.exec()


def ask_save_changes(
    parent, title: str, text: str
) -> QMessageBox.StandardButton:
    """「有未保存的修改，要先保存吗？」——按钮固定是 保存 / 不保存 / 取消。"""
    buttons = (
        QMessageBox.StandardButton.Save
        | QMessageBox.StandardButton.Discard
        | QMessageBox.StandardButton.Cancel
    )
    box = message_box(
        parent,
        title,
        text,
        QMessageBox.Icon.Question,
        buttons,
        QMessageBox.StandardButton.Save,
    )
    box.exec()
    clicked = box.clickedButton()
    return box.standardButton(clicked) if clicked is not None else QMessageBox.StandardButton.Cancel


def ask_text(parent, title: str, label: str, text: str = "") -> tuple[str, bool]:
    """单行文本输入（确定 / 取消）。默认值作为初始文本。"""
    dialog = QInputDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    dialog.setTextValue(text)
    dialog.setOkButtonText("确定")
    dialog.setCancelButtonText("取消")
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return dialog.textValue(), bool(accepted)


def ask_int(
    parent, title: str, label: str, value: int, minimum: int, maximum: int
) -> tuple[int, bool]:
    """整数输入（确定 / 取消）。"""
    dialog = QInputDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    dialog.setInputMode(QInputDialog.InputMode.IntInput)
    dialog.setIntRange(minimum, maximum)
    dialog.setIntValue(value)
    dialog.setOkButtonText("确定")
    dialog.setCancelButtonText("取消")
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return dialog.intValue(), bool(accepted)


#: 画布尺寸的预设比例（宽:高）。"自由" 表示宽高各填各的。
CANVAS_RATIOS = [
    ("自由", None),
    ("1:1", (1.0, 1.0)),
    ("4:3", (4.0, 3.0)),
    ("3:4", (3.0, 4.0)),
    ("16:9", (16.0, 9.0)),
    ("9:16", (9.0, 16.0)),
]


class CanvasSizeDialog(QDialog):
    """画布大小：**一个**框里同时设宽高，还能选预设比例。

    以前是连弹两次 `QInputDialog`（先宽后高），既慢又容易填错；改成一次设完。

    选比例时的换算规则（刻意做成"看得懂"而不是"聪明"）：

    * 选中比例的那一刻：**宽度保持不变，高度按比例换算**
      （1280×800 选 16:9 → 1280×720；选 9:16 → 1280×2276）
    * 锁定期间改任何一边，另一边自动跟随（改高 1920 且锁着 9:16 → 1080×1920）
    * 想要横竖互换（1280×800 → 800×1280）按「交换宽高」，它还会顺手把
      4:3↔3:4、16:9↔9:16 的比例按钮对上

    "宽不变"是刻意的：它是一句能被验证的规则，比"根据朝向智能挑基准边"好懂得多。
    """

    def __init__(self, width: int, height: int, parent=None, content_rect=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("画布大小")
        self._syncing = False
        self._ratio: tuple[float, float] | None = None
        self._content_rect = content_rect

        self.width_spin = QSpinBox()
        self.height_spin = QSpinBox()
        for spin in (self.width_spin, self.height_spin):
            spin.setRange(1, 20000)
            spin.setSuffix(" px")
            spin.setAccelerated(True)
        self.width_spin.setValue(max(1, int(width)))
        self.height_spin.setValue(max(1, int(height)))
        self.width_spin.valueChanged.connect(self._on_width_changed)
        self.height_spin.valueChanged.connect(self._on_height_changed)

        # 比例：一排可选按钮，比下拉框少一次点击
        self.ratio_buttons: dict[str, QPushButton] = {}
        self.ratio_group = QButtonGroup(self)
        self.ratio_group.setExclusive(True)
        ratio_row = QHBoxLayout()
        ratio_row.setSpacing(4)
        for label, ratio in CANVAS_RATIOS:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.setToolTip(
                "宽高各自填" if ratio is None else f"锁定 {label}：改一边另一边自动换算"
            )
            button.clicked.connect(
                lambda _checked=False, r=ratio: self.set_ratio(r)
            )
            self.ratio_group.addButton(button)
            self.ratio_buttons[label] = button
            ratio_row.addWidget(button)
        self.ratio_buttons["自由"].setChecked(True)

        self.swap_button = QPushButton("交换宽高")
        self.swap_button.setToolTip("横竖互换（例如 1280×800 → 800×1280）")
        self.swap_button.clicked.connect(self.swap)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#9a9aa4;")
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color:#e0a33a;")
        self.warning.setVisible(False)

        form = QFormLayout()
        form.addRow("宽度", self.width_spin)
        form.addRow("高度", self.height_spin)

        ratio_label = QLabel("比例")
        swap_row = QHBoxLayout()
        swap_row.addWidget(ratio_label)
        swap_row.addStretch(1)
        swap_row.addWidget(self.swap_button)
        ratio_row.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(swap_row)
        layout.addLayout(ratio_row)
        layout.addWidget(self.hint)
        layout.addWidget(self.warning)
        layout.addWidget(buttons)
        self._update_hint()
        self.width_spin.setFocus()
        self.width_spin.selectAll()

    # ---------------------------------------------------------- 比例
    def set_ratio(self, ratio: tuple[float, float] | None) -> None:
        """选中某个比例并**立刻按规则换算**一次，用户不用再手动改另一边。"""
        self._ratio = ratio
        for label, value in CANVAS_RATIOS:
            self.ratio_buttons[label].setChecked(value == ratio)
        if ratio is None:
            self._update_hint()
            return
        self._recompute(from_width=True, force=True)

    def swap(self) -> None:
        """横竖互换；如果当前比例在列表里有镜像（4:3↔3:4、16:9↔9:16）也跟着切。"""
        width, height = self.width_spin.value(), self.height_spin.value()
        self._syncing = True
        try:
            self.width_spin.setValue(height)
            self.height_spin.setValue(width)
        finally:
            self._syncing = False
        if self._ratio is not None:
            mirrored = (self._ratio[1], self._ratio[0])
            if any(value == mirrored for _label, value in CANVAS_RATIOS):
                self._ratio = mirrored
            else:
                self._ratio = None
            for label, value in CANVAS_RATIOS:
                self.ratio_buttons[label].setChecked(value == self._ratio)
        self._update_hint()

    def _recompute(self, from_width: bool, force: bool = False) -> None:
        """按锁定的比例换算另一边。``from_width`` 表示用户刚改的是宽度。"""
        if self._ratio is None:
            self._update_hint()
            return
        rw, rh = self._ratio
        if force:
            # 刚选中比例：宽不变、高按比例（见类文档里那句"宽不变"的规则）
            from_width = True
        self._syncing = True
        try:
            if from_width:
                height = max(1, int(round(self.width_spin.value() * rh / rw)))
                self.height_spin.setValue(min(20000, height))
            else:
                width = max(1, int(round(self.height_spin.value() * rw / rh)))
                self.width_spin.setValue(min(20000, width))
        finally:
            self._syncing = False
        self._update_hint()

    def _on_width_changed(self, _value: int) -> None:
        if self._syncing:
            return
        self._recompute(from_width=True)

    def _on_height_changed(self, _value: int) -> None:
        if self._syncing:
            return
        self._recompute(from_width=False)

    # ---------------------------------------------------------- 结果
    def size(self) -> tuple[int, int]:
        return int(self.width_spin.value()), int(self.height_spin.value())

    def _update_hint(self) -> None:
        width, height = self.size()
        megapixels = width * height / 1_000_000.0
        if self._ratio is None:
            ratio_text = "自由"
        else:
            rw, rh = self._ratio
            g = math.gcd(int(round(rw)), int(round(rh))) or 1
            ratio_text = f"{int(round(rw)) // g}:{int(round(rh)) // g}"
        self.hint.setText(
            f"{width} × {height} 像素　比例 {ratio_text}　约 {megapixels:.2f} MP"
        )
        if self._content_rect is None:
            return
        content = self._content_rect
        outside = (
            content.right() > width + 0.5
            or content.bottom() > height + 0.5
            or content.left() < -0.5
            or content.top() < -0.5
        )
        self.warning.setVisible(bool(outside))
        if outside:
            self.warning.setText(
                "提示：新画布装不下现有内容（内容外框 "
                f"{content.width():.0f}×{content.height():.0f}），"
                "可以用「画布 → 画布适应内容」把内容收进来。"
            )


class ExportDialog(QDialog):
    def __init__(self, doc, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("导出图片")
        self.doc = doc

        self.format_combo = QComboBox()
        for label, suffix in FORMATS:
            self.format_combo.addItem(label, suffix)
        self.format_combo.setCurrentIndex(0)
        self.format_combo.currentIndexChanged.connect(self._update_size)

        self.scale_combo = QComboBox()
        for label, value in SCALES:
            self.scale_combo.addItem(label, value)
        self.scale_combo.currentIndexChanged.connect(self._update_size)

        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(40, 100)
        self.quality_slider.setValue(92)
        self.quality_label = QLabel("92")
        self.quality_slider.valueChanged.connect(
            lambda v: self.quality_label.setText(str(v))
        )
        quality_row = QHBoxLayout()
        quality_row.addWidget(self.quality_slider)
        quality_row.addWidget(self.quality_label)

        self.size_label = QLabel()
        self.size_label.setStyleSheet("color:#8a8a92;")

        form = QFormLayout()
        form.addRow("格式", self.format_combo)
        form.addRow("倍率", self.scale_combo)
        form.addRow("质量", quality_row)
        form.addRow("导出尺寸", self.size_label)

        hint = QLabel(
            "矢量重绘：2x/4x 导出时文字与线条依然锐利，不是插值放大。\n"
            "导出范围 = 当前裁剪框。"
        )
        hint.setStyleSheet("color:#8a8a92;")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("选择保存位置…")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)
        self._update_size()

    def _update_size(self) -> None:
        scale = float(self.scale_combo.currentData() or 1.0)
        crop = self.doc.crop
        width = int(round(crop.width() * scale))
        height = int(round(crop.height() * scale))
        self.size_label.setText(f"{width} × {height} 像素")

    def suffix(self) -> str:
        return str(self.format_combo.currentData())

    def scale(self) -> float:
        return float(self.scale_combo.currentData() or 1.0)

    def quality(self) -> int:
        return int(self.quality_slider.value())
