"""空白画布渲染回归测试。

背景：`fit_to_window()` 曾经在窗口还没布局完时被调用，算出的缩放是垃圾值，
而 `_zoom` 又被 clamp 到 MIN_ZOOM，两者从此不一致 —— 结果是**双击 exe 的默认
空白画布缩成一个几十像素的小点，用户根本看不见画布**。这个测试守住它。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402

from drawx.app import create_application  # noqa: E402
from drawx.ui.main_window import MainWindow  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def check(condition: bool, message: str) -> None:
    RESULTS.append((bool(condition), message))
    print(("  PASS  " if condition else "  FAIL  ") + message)


def dominant_colors(image, step: int = 13) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            name = image.pixelColor(x, y).name()
            counts[name] = counts.get(name, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:4]


def count_color(image, target: QColor, tolerance: int = 40, step: int = 2) -> int:
    found = 0
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            color = image.pixelColor(x, y)
            if (
                abs(color.red() - target.red()) <= tolerance
                and abs(color.green() - target.green()) <= tolerance
                and abs(color.blue() - target.blue()) <= tolerance
            ):
                found += 1
    return found


def main() -> int:
    app = create_application([])
    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    for _ in range(6):
        app.processEvents()

    view = window.view
    scene = window.scene
    doc = scene.doc

    print("\n[1] 缩放值必须和真实变换一致，且在合理范围内")
    real = view.transform().m11()
    print(f"  真实缩放 = {real:.4f}  记录缩放 = {view.zoom():.4f}  状态栏 = {window.status_zoom.text()}")
    check(abs(real - view.zoom()) < 1e-6, f"记录值({view.zoom():.4f})与真实变换({real:.4f})一致")
    check(0.2 <= real <= 3.0, f"空白画布初始缩放合理（{real:.3f}，期望 0.2~3.0）")

    print("\n[2] 空白画布必须真的画出白色画布")
    image = view.grab().toImage()
    colors = dominant_colors(image)
    print("  视图主要颜色:", colors)
    check(
        colors[0][0] == "#ffffff",
        f"视图主色是白色画布（实际主色 {colors[0][0]}）",
    )
    white_ratio = colors[0][1] / max(1, sum(count for _n, count in colors))
    check(white_ratio > 0.5, f"白色占比 {white_ratio:.0%}（画布应占大部分视口）")

    print("\n[3] 空白画布上画的箭头必须可见")
    item = scene.create_item({"type": "arrow"})
    item.p1 = QPointF(0.0, 0.0)
    item.p2 = QPointF(500.0, -300.0)
    item.setPos(200.0, 600.0)
    item.refresh_origin()
    item.setZValue(scene.next_z())
    scene.add_anno(item)
    scene.set_selection([])
    for _ in range(3):
        app.processEvents()
    image = view.grab().toImage()
    red = count_color(image, QColor("#ff3b30"))
    print(f"  红色像素采样数 = {red}")
    check(red > 30, f"箭头在空白画布上可见（红色采样 {red}）")

    print("\n[4] 缩放/复位后记录值始终跟随真实变换")
    for factor in (1.25, 1.25, 1 / 1.25, 1 / 1.25):
        view.zoom_by(factor, under_mouse=False)
        if abs(view.transform().m11() - view.zoom()) > 1e-6:
            break
    check(
        abs(view.transform().m11() - view.zoom()) < 1e-6,
        f"连续缩放后一致（真实 {view.transform().m11():.4f} vs 记录 {view.zoom():.4f}）",
    )
    view.zoom_reset()
    check(abs(view.transform().m11() - 1.0) < 1e-6, "实际大小 = 100%")
    view.fit_to_window()
    for _ in range(3):
        app.processEvents()
    check(
        abs(view.transform().m11() - view.zoom()) < 1e-6 and 0.2 <= view.zoom() <= 3.0,
        f"适应窗口后缩放合理（{view.zoom():.3f}）",
    )

    print("\n[5] 导入图片后同样正常")
    from PySide6.QtGui import QImage, QPainter

    background = QImage(900, 600, QImage.Format.Format_RGB32)
    background.fill(QColor("#eef2f7"))
    painter = QPainter(background)
    painter.fillRect(100, 100, 300, 200, QColor("#88b04b"))
    painter.end()
    window.add_image_layer(background)
    for _ in range(3):
        app.processEvents()
    check(
        abs(view.transform().m11() - view.zoom()) < 1e-6,
        f"导入图片后一致（{view.zoom():.3f}）",
    )
    image = view.grab().toImage()
    green = count_color(image, QColor("#88b04b"), tolerance=30)
    check(green > 20, f"背景图渲染可见（绿色采样 {green}）")

    out_dir = ROOT / "build" / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    view.grab().save(str(out_dir / "blank_canvas_fixed.png"))
    check(True, f"截图已保存 -> {out_dir / 'blank_canvas_fixed.png'}")

    failed = [message for ok, message in RESULTS if not ok]
    print("\n" + "=" * 60)
    print(f"总计 {len(RESULTS)} 项，通过 {len(RESULTS) - len(failed)} 项，失败 {len(failed)} 项")
    for message in failed:
        print("  FAILED:", message)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
