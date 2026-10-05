"""并排渲染几组弧形箭头参数，挑最好看的一组。

注意排版：每个格子只放一个图标，undo/redo 分开排。之前两个挤在同一格里，
64px 时直接叠在一起，看着像图标中间破了个洞 —— 白白误导了自己半天。

用法：python devtools/icon_variants.py [组名过滤]
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import drawx.ui.icons as icons  # noqa: E402
from drawx.const import COLOR_VIEW_BG  # noqa: E402

#: 每组只写"这次要试的差异"，其余继承 CURVED_ARROW。
#: 第一组是 v0.1 的老参数，留作对照（箭头偏小、朝内勾）。
VARIANTS = [
    ("v0.1 旧: h.16 sp32 end175", dict(pen=0.065, head=0.16, spread=32.0, bias=0.0,
                                       x=0.14, y=0.30, w=0.72, h=0.52, start=30.0, end=175.0)),
    ("当前 v0.2（推荐）", {}),
    ("更外偏 bias26", dict(bias=26.0)),
    ("更小头 head.18", dict(head=0.18)),
    ("更圆 h.66", dict(h=0.66, y=0.40)),
]
SIZES = [22, 32, 48, 64, 96]
LABEL_W = 250
CELL = 96


def main() -> int:
    app = QApplication([])  # noqa: F841
    filter_text = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    variants = [
        (label, overrides)
        for label, overrides in VARIANTS
        if filter_text in label.lower()
    ] or VARIANTS
    width = LABEL_W + CELL * (len(SIZES) + 1)
    height = CELL * len(variants) + 20
    canvas = QImage(width, height, QImage.Format.Format_ARGB32)
    canvas.fill(QColor(COLOR_VIEW_BG))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    base = dict(icons.CURVED_ARROW)
    for row, (label, overrides) in enumerate(variants):
        icons.CURVED_ARROW.clear()
        icons.CURVED_ARROW.update(base)
        icons.CURVED_ARROW.update(overrides)
        cfg = icons.CURVED_ARROW
        radius = icons.arc_local_radius(cfg, cfg["end"])
        deviation = __import__("math").degrees(cfg["head"] / radius) if radius else 0.0
        y = 10 + row * CELL
        painter.setPen(QColor("#9a9aa4"))
        painter.drawText(
            QRectF(8, y, LABEL_W - 12, CELL / 2),
            Qt.AlignmentFlag.AlignVCenter,
            label,
        )
        painter.setPen(QColor("#6f6f78"))
        painter.drawText(
            QRectF(8, y + CELL / 2 - 6, LABEL_W - 12, CELL / 2),
            Qt.AlignmentFlag.AlignVCenter,
            f"R={radius:.3f}  head/R={deviation:.0f}°  vs 张角 {cfg['spread']:.0f}°",
        )

        # 前几列：undo 的尺寸梯度
        for column, size in enumerate(SIZES):
            pixmap = icons.tool_icon("undo", max(size, 22)).pixmap(size, size)
            x = LABEL_W + column * CELL + (CELL - size) / 2.0
            painter.drawPixmap(int(x), int(y + (CELL - size) / 2.0), pixmap)

        # 最后一列：22px 下 undo / redo 并排（这才是工具栏里的真实尺寸）
        size = 22
        for index, name in enumerate(("undo", "redo")):
            pixmap = icons.tool_icon(name, 22).pixmap(size, size)
            x = LABEL_W + len(SIZES) * CELL + 6 + index * (size + 8)
            painter.drawPixmap(int(x), int(y + (CELL - size) / 2.0), pixmap)
    painter.end()
    icons.CURVED_ARROW.clear()
    icons.CURVED_ARROW.update(base)

    out = os.path.join(ROOT, "build", "gui", "icon_variants.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    canvas.save(out)
    print(out, canvas.width(), "x", canvas.height())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
