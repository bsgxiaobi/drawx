"""量一遍所有工具栏图标在 22px 下的"墨迹"包围盒，检查视觉重心是否一致。

背景：弧形箭头（undo/redo）曾经只占外接矩形的上半部分，导致整个图标比旁边的
图标高 1~2px。改图标后跑一下这个脚本，能立刻看出谁没居中。

用法：.venv\\Scripts\\python.exe devtools/icon_metrics.py [size]
"""

from __future__ import annotations

import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from drawx.ui.icons import tool_icon  # noqa: E402

NAMES = [
    "select", "crop", "rect", "ellipse", "roundrect", "line", "arrow",
    "freehand", "highlight", "text", "mosaic", "blur",
    "import", "export", "delete", "copy_image",
    "image", "layers", "layer_add", "layer_dup", "move_up", "move_down",
    "undo", "redo",
]


def ink(name: str, size: int, scale: int = 8):
    image = tool_icon(name, size * scale).pixmap(size * scale, size * scale).toImage()
    xs: list[int] = []
    ys: list[int] = []
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 40:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    factor = float(scale)
    return (
        min(xs) / factor,
        min(ys) / factor,
        (max(xs) + 1) / factor,
        (max(ys) + 1) / factor,
    )


def main() -> int:
    app = QApplication([])  # noqa: F841
    size = int(sys.argv[1]) if len(sys.argv) > 1 else 22
    print(f"图标墨迹包围盒（{size}px，理想重心 = {size / 2:.1f}）")
    print(f"{'名称':<12}{'重心x':>7}{'重心y':>7}{'宽':>6}{'高':>6}   偏离")
    rows = []
    for name in NAMES:
        box = ink(name, size)
        if box is None:
            print(f"{name:<12}   （空图标！）")
            continue
        cx = (box[0] + box[2]) / 2.0
        cy = (box[1] + box[3]) / 2.0
        rows.append((name, cx, cy, box[2] - box[0], box[3] - box[1]))
    center = size / 2.0
    for name, cx, cy, width, height in rows:
        flag = ""
        if abs(cx - center) > 1.2 or abs(cy - center) > 1.2:
            flag = "  ← 偏心"
        print(f"{name:<12}{cx:7.2f}{cy:7.2f}{width:6.1f}{height:6.1f}{flag}")
    print(
        f"\n中位数 重心x={statistics.median(r[1] for r in rows):.2f} "
        f"重心y={statistics.median(r[2] for r in rows):.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
