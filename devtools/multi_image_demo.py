"""造一个"多张现场照片拼成一张完整图"的示例工程，用来做多图功能的实测。

用法：
    .venv\\Scripts\\python.exe devtools\\multi_image_demo.py            # 生成示例工程与导出图
    .venv\\Scripts\\python.exe devtools\\multi_image_demo.py --gui      # 生成后直接打开窗口（人工/GUI 实测）

产物：
    build/gui/site_1.png … site_4.png   四张假的"现场照片"
    build/gui/multi_site.drawx          拼好的工程文件（4 个图片图层 + 1 个标注图层）
    build/gui/multi_site.png            导出成图（验证拼合结果）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402

OUT = ROOT / "build" / "gui"


def make_photo(index: int, width: int, height: int, base: str, label: str) -> QImage:
    """造一张"像是现场照片"的图：底色 + 现场编号 + 一块特征色 + 一行文字。"""
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(base))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    painter.fillRect(0, 0, width, max(34, height // 12), QColor("#1f3b57"))
    painter.setPen(QColor("#ffffff"))
    font = QFont("Microsoft YaHei", 13)
    painter.setFont(font)
    painter.drawText(14, max(24, height // 12 - 10), label)

    painter.setPen(QColor("#2c3e50"))
    font.setPointSize(10)
    painter.setFont(font)
    painter.drawText(16, height - 22, f"现场记录 {index}  {width}×{height}")

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#c0392b") if index % 2 else QColor("#27866a"))
    painter.drawRect(
        int(width * 0.12), int(height * 0.35), int(width * 0.34), int(height * 0.22)
    )
    painter.setBrush(QColor("#d9a441"))
    painter.drawEllipse(
        QRectF(width * 0.62, height * 0.42, width * 0.22, width * 0.22)
    )
    painter.setPen(QColor("#7f8c8d"))
    painter.drawLine(10, int(height * 0.86), width - 10, int(height * 0.86))
    painter.end()
    return image


def build(gui: bool = False) -> int:
    from drawx.app import create_application
    from drawx.render.exporter import save_image
    from drawx.ui.main_window import MainWindow

    OUT.mkdir(parents=True, exist_ok=True)
    # 必须先有 QGuiApplication：QFont / QPainter 画文字都依赖它（否则 QFont 直接崩）
    app = create_application([])
    photos = [
        make_photo(1, 640, 480, "#eef3f8", "现场照片 1 - 入口"),
        make_photo(2, 480, 640, "#f7f1ea", "现场照片 2 - 配电箱"),
        make_photo(3, 800, 450, "#eef7f0", "现场照片 3 - 顶棚"),
        make_photo(4, 520, 520, "#f6eef7", "现场照片 4 - 地面"),
    ]
    paths: list[str] = []
    for index, image in enumerate(photos, start=1):
        path = OUT / f"site_{index}.png"
        image.save(str(path))
        paths.append(str(path))
    print("照片已生成：", ", ".join(Path(p).name for p in paths))

    window = MainWindow()
    window.resize(1500, 940)
    window.show()
    for _ in range(4):
        app.processEvents()

    window.add_image_layers(paths)
    for _ in range(3):
        app.processEvents()
    window.arrange_image_layers(columns=2, gap=20.0)
    for _ in range(3):
        app.processEvents()

    # 在最上面的标注图层里加一点标注，模拟"编辑成一张完整的现场图"
    from drawx.items.base import set_local_rect_keep_anchor
    from drawx.items.shapes import ArrowItem
    from drawx.items.text import TextItem

    scene = window.scene
    doc = scene.doc
    label = TextItem({"stroke": "#c0392b", "fontSize": 22, "bold": True})
    label.setPlainText("现场整体示意：4 张照片已拼合")
    label.apply_text_style()
    label.setPos(24.0, max(4.0, doc.canvas_h - 60.0))
    scene.add_anno(label)

    arrow = ArrowItem({"stroke": "#ff9500", "strokeWidth": 5})
    arrow.p1 = __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(0, 0)
    arrow.p2 = __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(230, 40)
    # 从第 1 张的右边缘指向第 2 张的左边缘（网格是 20 间距、单元格 800×640）
    arrow.setPos(750.0, 280.0)
    arrow.refresh_origin()
    set_local_rect_keep_anchor(arrow, QRectF(0, 0, 230, 40))
    scene.add_anno(arrow)
    scene.set_selection([])
    for _ in range(3):
        app.processEvents()

    project = OUT / "multi_site.drawx"
    doc.file_path = str(project)
    window.save_project()
    export = OUT / "multi_site.png"
    save_image(window.view.grab().toImage(), str(OUT / "multi_site_window.png"))
    from drawx.render.exporter import render_document

    doc.reset_crop()
    save_image(render_document(doc, scene, scale=1.0), str(export))
    print(
        f"工程已保存：{project.name}　画布 {doc.canvas_w}×{doc.canvas_h}　"
        f"图层 {len(doc.layers)}（图片 {len(doc.image_layers())}）"
    )
    print(f"导出成图：{export}")

    if not gui:
        window.scene.doc.modified = False
        window.close()
        app.processEvents()
        return 0
    print("窗口已打开，可用 devtools/screen_agent.py 操控（Ctrl+C 结束）")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(build(gui="--gui" in sys.argv))
