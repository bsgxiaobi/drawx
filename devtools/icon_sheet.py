"""把工具栏图标排成一张对照图，方便肉眼验收（改图标必看）。

用法：python devtools/icon_sheet.py [输出路径]
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

from drawx.const import COLOR_VIEW_BG  # noqa: E402
from drawx.ui.icons import tool_icon  # noqa: E402

ROWS = [
    ("undo", [16, 22, 32, 48, 64]),
    ("redo", [16, 22, 32, 48, 64]),
    ("copy_image", [16, 22, 32, 48, 64]),
    ("import", [22, 32]),
    ("export", [22, 32]),
    ("delete", [22, 32]),
    ("crop", [22, 32]),
    ("arrow", [22, 32]),
]

CELL = 76


def main() -> int:
    app = QApplication([])  # noqa: F841
    width = CELL * max(len(sizes) for _name, sizes in ROWS) + 20
    height = CELL * len(ROWS) + 20
    canvas = QImage(width, height, QImage.Format.Format_ARGB32)
    canvas.fill(QColor(COLOR_VIEW_BG))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    for row, (name, sizes) in enumerate(ROWS):
        for column, size in enumerate(sizes):
            icon = tool_icon(name, max(size, 22))
            pixmap = icon.pixmap(size, size)
            x = 10 + column * CELL + (CELL - size) / 2.0
            y = 10 + row * CELL + (CELL - size) / 2.0
            painter.drawPixmap(int(x), int(y), pixmap)
            painter.setPen(QColor("#8a8a92"))
            painter.drawText(
                QRectF(10 + column * CELL, 10 + row * CELL + CELL - 15, CELL, 14),
                Qt.AlignmentFlag.AlignHCenter,
                f"{name} {size}",
            )
    painter.end()

    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "smoke", "icon_sheet.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    canvas.save(out)
    print(out, canvas.width(), "x", canvas.height())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
