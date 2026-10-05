"""箭头渲染专项测试：像素级验证"尖端不露出线帽"，并生成一张对比图。

运行：.venv\\Scripts\\python.exe tests\\arrow_test.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402

from drawx.app import create_application  # noqa: E402
from drawx.items.shapes import ArrowItem  # noqa: E402
from drawx.model.document import Document  # noqa: E402
from drawx.render.exporter import render_document  # noqa: E402
from drawx.ui.canvas_scene import CanvasScene  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def check(condition: bool, ok_message: str, fail_message: str = "") -> None:
    RESULTS.append((bool(condition), ok_message if condition else (fail_message or ok_message)))
    print(("  PASS  " if condition else "  FAIL  ") + (ok_message if condition else (fail_message or ok_message)))


def make_scene(width: int, height: int) -> CanvasScene:
    scene = CanvasScene()
    doc = Document()
    doc.set_canvas(width, height)
    scene.doc = doc
    return scene


def add_arrow(scene, p1, p2, width=4.0, head="end", color="#ff3b30"):
    item = ArrowItem({"stroke": color, "strokeWidth": width})
    item.p1 = QPointF(0.0, 0.0)
    item.p2 = QPointF(p2[0] - p1[0], p2[1] - p1[1])
    item.head = head
    item.setPos(p1[0], p1[1])
    item.refresh_origin()
    item.setZValue(scene.next_z())
    scene.add_anno(item)
    return item


def _is_ink(color: QColor) -> bool:
    """非白即算墨迹（红色 #ff3b30 的 red 通道是 255，不能只看 red）。"""
    return color.red() < 245 or color.green() < 245 or color.blue() < 245


def ink_columns(image, row_range=None) -> tuple[int, int]:
    """返回非白像素的最左、最右列号。"""
    leftmost, rightmost = None, None
    ys = range(row_range[0], row_range[1]) if row_range else range(image.height())
    for y in ys:
        for x in range(image.width()):
            if _is_ink(image.pixelColor(x, y)):
                if leftmost is None or x < leftmost:
                    leftmost = x
                if rightmost is None or x > rightmost:
                    rightmost = x
    return (leftmost if leftmost is not None else -1, rightmost if rightmost is not None else -1)


def vertical_extent(image, column: int) -> int:
    ys = [y for y in range(image.height()) if _is_ink(image.pixelColor(column, y))]
    return (max(ys) - min(ys) + 1) if ys else 0


def main() -> int:
    app = create_application([])  # noqa: F841

    print("\n[1] 水平箭头：尖端不能有像素超出去（线帽问题）")
    for width in (2.0, 4.0, 12.0, 24.0):
        scene = make_scene(400, 160)
        tip_x = 300.0
        add_arrow(scene, (100.0, 80.0), (tip_x, 80.0), width=width, head="end")
        image = render_document(scene.doc, scene, scale=1.0)
        left, right = ink_columns(image)
        # 允许 1 像素抗锯齿余量
        check(
            right <= tip_x + 1,
            f"线宽 {width:.0f}：最右墨迹 x={right}（尖端 {tip_x:.0f}，允许 ≤{tip_x + 1:.0f}）",
            f"线宽 {width:.0f}：最右墨迹 x={right} 超出尖端 {tip_x:.0f}（线帽戳出来了）",
        )
        # 起点没有箭头，圆头端帽会往左伸出半个线宽，这是正常的
        check(
            left >= 100 - width / 2 - 1,
            f"线宽 {width:.0f}：最左墨迹 x={left}（起点 100，圆头端帽 ≤{100 - width / 2:.0f}）",
        )

    print("\n[2] 箭头确实比线杆宽（不然就是画了个尖头细线）")
    scene = make_scene(400, 160)
    add_arrow(scene, (100.0, 80.0), (300.0, 80.0), width=6.0, head="end")
    image = render_document(scene.doc, scene, scale=1.0)
    shaft = vertical_extent(image, 200)      # 线杆中部
    head = vertical_extent(image, 288)       # 接近尖端
    check(
        head > shaft * 1.4,
        f"箭头根部高度 {head}px 明显大于线杆 {shaft}px",
        f"箭头太窄：根部 {head}px vs 线杆 {shaft}px",
    )

    print("\n[3] 无箭头时线杆应画到端点")
    scene = make_scene(400, 160)
    add_arrow(scene, (100.0, 80.0), (300.0, 80.0), width=4.0, head="none")
    image = render_document(scene.doc, scene, scale=1.0)
    _left, right = ink_columns(image)
    check(
        300 <= right <= 303,
        f"head=none：最右墨迹 x={right}（端点 300 + 圆头线帽 2）",
    )

    print("\n[4] 两端箭头 / 起点箭头")
    scene = make_scene(400, 160)
    add_arrow(scene, (100.0, 80.0), (300.0, 80.0), width=6.0, head="both")
    image = render_document(scene.doc, scene, scale=1.0)
    left, right = ink_columns(image)
    check(right <= 301, f"两端箭头：右端 x={right} 未超出")
    check(left >= 99, f"两端箭头：左端 x={left} 未超出")

    print("\n[5] 极短箭头不能画崩")
    for length in (6.0, 14.0, 30.0):
        scene = make_scene(200, 120)
        add_arrow(scene, (60.0, 60.0), (60.0 + length, 60.0), width=10.0, head="end")
        image = render_document(scene.doc, scene, scale=1.0)
        left, right = ink_columns(image)
        check(
            0 <= left and right <= 60 + length + 1,
            f"长度 {length:.0f}：墨迹范围 {left}~{right}（端点 {60 + length:.0f}）",
            f"长度 {length:.0f}：墨迹范围 {left}~{right} 异常",
        )

    print("\n[6] 生成对比图（含用户截图里的那种浅角度箭头）")
    out_dir = ROOT / "build" / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    scene = make_scene(560, 420)
    samples = [
        ((40, 60), (520, 380), 5.0, "end"),      # 浅角度长箭头（对应用户反馈）
        ((40, 120), (520, 120), 5.0, "end"),     # 水平
        ((40, 200), (520, 360), 16.0, "end"),    # 粗箭头
        ((40, 330), (520, 330), 4.0, "both"),    # 两端
        ((300, 380), (520, 300), 3.0, "end"),    # 细箭头
        ((60, 380), (280, 385), 22.0, "end"),    # 很粗的短箭头
    ]
    for index, (start, end, width, head) in enumerate(samples):
        add_arrow(scene, start, end, width=width, head=head)

    sheet = render_document(scene.doc, scene, scale=1.0)
    path = out_dir / "arrow_sheet.png"
    sheet.save(str(path))
    check(path.exists(), f"对比图已生成 -> {path}")

    # 放大尖端，确认没有凸起
    tip_scene = make_scene(400, 160)
    add_arrow(tip_scene, (60.0, 80.0), (340.0, 80.0), width=14.0, head="end")
    zoom = render_document(tip_scene.doc, tip_scene, scale=4.0)
    zoom_path = out_dir / "arrow_tip_zoom.png"
    zoom.save(str(zoom_path))
    check(zoom_path.exists(), f"尖端放大图已生成 -> {zoom_path}")

    failed = [message for ok, message in RESULTS if not ok]
    print("\n" + "=" * 60)
    print(f"总计 {len(RESULTS)} 项，通过 {len(RESULTS) - len(failed)} 项，失败 {len(failed)} 项")
    for message in failed:
        print("  FAILED:", message)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
