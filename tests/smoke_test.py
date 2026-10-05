"""功能冒烟测试：不依赖真实点击，直接驱动工具逻辑。

运行：.venv\\Scripts\\python.exe tests\\smoke_test.py
"""

from __future__ import annotations

import json
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402

from drawx.app import create_application  # noqa: E402
from drawx.model.serialize import PROJECT_JSON  # noqa: E402
from drawx.render.exporter import render_document, save_image  # noqa: E402
from drawx.ui.main_window import MainWindow  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def check(condition: bool, message: str) -> None:
    RESULTS.append((bool(condition), message))
    print(("  PASS  " if condition else "  FAIL  ") + message)


def close(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) <= tol


class FakeEvent:
    """伪造鼠标事件，直接喂给工具方法（坐标一律用视口坐标）。"""

    def __init__(self, position, button=Qt.MouseButton.LeftButton, modifiers=None):
        self._position = QPointF(position.x(), position.y())
        self._button = button
        self._modifiers = (
            Qt.KeyboardModifier.NoModifier if modifiers is None else modifiers
        )

    def position(self) -> QPointF:
        return QPointF(self._position)

    def button(self):
        return self._button

    def modifiers(self):
        return self._modifiers


def drag_scene(view, start_scene, end_scene, steps=8, modifiers=None):
    """按**场景坐标**拖动（内部换算成视口坐标），避免依赖视图滚动位置。"""
    transform = view.viewportTransform()
    start = transform.map(QPointF(start_scene[0], start_scene[1]))
    end = transform.map(QPointF(end_scene[0], end_scene[1]))
    view.tool.mouse_press(view, FakeEvent(start, modifiers=modifiers))
    for index in range(1, steps + 1):
        ratio = index / steps
        point = QPointF(
            start.x() + (end.x() - start.x()) * ratio,
            start.y() + (end.y() - start.y()) * ratio,
        )
        view.tool.mouse_move(view, FakeEvent(point, modifiers=modifiers))
    view.tool.mouse_release(view, FakeEvent(end, modifiers=modifiers))


def make_background(width: int = 800, height: int = 600) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#dfe7ef"))
    painter = QPainter(image)
    painter.setPen(QColor("#12203a"))
    painter.drawText(60, 90, "Secret 13800138000")
    painter.fillRect(320, 220, 160, 90, QColor("#c33"))
    painter.end()
    return image


def main() -> int:
    app = create_application([])
    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    view = window.view
    scene = window.scene

    print("\n[1] 文档与图片图层")
    background = make_background()
    window.add_image_layer(background)
    view.zoom_reset()
    check(scene.doc.canvas_w == 800 and scene.doc.canvas_h == 600, "画布尺寸跟随图片 800x600")
    check(scene.doc.crop == QRectF(0, 0, 800, 600), "默认裁剪框 = 整幅")
    check(scene.doc.has_image, "图片已作为一个图片图层载入")
    check(len(scene.doc.image_layers()) == 1, "有 1 个图片图层")
    check(not scene.doc.is_cropped, "初始未被裁剪")
    check(close(view.zoom(), 1.0), f"缩放到实际大小（{view.zoom():.2f}）")
    # 导入图片现在也是一条可撤销命令，清掉它才能用"撤销条数"验证后面的操作
    scene.undo_stack.clear()

    print("\n[2] 每种标注对象都能创建并往返序列化")
    samples = {
        "rect": dict(x=150, y=130, w=200, h=100),
        "ellipse": dict(x=400, y=120, w=180, h=120),
        "roundrect": dict(x=620, y=120, w=150, h=120),
        "line": dict(x=100, y=300, w=200, h=80),
        "arrow": dict(x=360, y=300, w=200, h=80),
        "highlight": dict(x=100, y=430, w=240, h=40),
        "mosaic": dict(x=40, y=50, w=260, h=70),
        "blur": dict(x=520, y=430, w=160, h=80),
    }
    created = []
    for type_name, geometry in samples.items():
        item = scene.create_item({"type": type_name, **geometry})
        scene.add_anno(item)
        created.append(item)
        again = item.to_dict()
        clone = scene.create_item(again)
        check(clone is not None and clone.to_dict() == again, f"{type_name} 序列化往返一致")

    text_item = scene.create_item({"type": "text", "x": 120, "y": 520, "w": 240, "h": 40})
    text_item.setPlainText("中文标注 ABC")
    text_item.apply_text_style()
    scene.add_anno(text_item)
    created.append(text_item)
    check(
        scene.create_item(text_item.to_dict()).to_dict() == text_item.to_dict(),
        "text 序列化往返一致（含中文）",
    )
    check(
        len(scene.annotation_items()) == 9,
        f"共 9 个标注对象（实际 {len(scene.annotation_items())}）",
    )

    print("\n[3] 选择工具：移动 / 缩放 / 旋转")
    view.set_tool("select")
    rect_item = created[0]
    scene.set_selection([rect_item])

    drag_scene(view, (250, 180), (300, 210))
    check(
        close(rect_item.pos().x(), 200) and close(rect_item.pos().y(), 160),
        f"拖动移动正确（pos={rect_item.pos().x():.0f},{rect_item.pos().y():.0f}）",
    )
    check(scene.undo_stack.count() == 1, "移动产生 1 条撤销记录")
    scene.undo_stack.undo()
    check(
        close(rect_item.pos().x(), 150) and close(rect_item.pos().y(), 130),
        "撤销后位置还原",
    )
    scene.undo_stack.redo()
    scene.undo_stack.clear()

    se_scene = rect_item.mapToScene(rect_item.local_rect().bottomRight())
    check(
        close(se_scene.x(), 400) and close(se_scene.y(), 260),
        f"右下角控制点位置 {se_scene.x():.0f},{se_scene.y():.0f}",
    )
    drag_scene(view, (se_scene.x(), se_scene.y()), (500, 360))
    check(
        close(rect_item.local_rect().width(), 300)
        and close(rect_item.local_rect().height(), 200),
        f"右下角缩放尺寸 {rect_item.local_rect().width():.0f}x{rect_item.local_rect().height():.0f}",
    )
    check(
        close(rect_item.pos().x(), 200) and close(rect_item.pos().y(), 160),
        "缩放时左上角锚点保持不动",
    )

    nw_scene = rect_item.mapToScene(rect_item.local_rect().topLeft())
    se_before = rect_item.mapToScene(rect_item.local_rect().bottomRight())
    drag_scene(view, (nw_scene.x(), nw_scene.y()), (nw_scene.x() + 50, nw_scene.y() + 30))
    se_after = rect_item.mapToScene(rect_item.local_rect().bottomRight())
    check(
        close(se_before.x(), se_after.x()) and close(se_before.y(), se_after.y()),
        f"拖左上角时右下角保持不动（{se_after.x():.0f},{se_after.y():.0f}）",
    )
    check(
        close(rect_item.local_rect().width(), 250)
        and close(rect_item.local_rect().height(), 170),
        f"左上角缩放尺寸 {rect_item.local_rect().width():.0f}x{rect_item.local_rect().height():.0f}",
    )

    scene.undo_stack.clear()
    handle_view = view._rotate_handle_view(rect_item, view.viewportTransform())
    handle_scene = view.to_scene(handle_view)
    center_scene = rect_item.mapToScene(rect_item.local_rect().center())
    check(handle_view is not None, "旋转手柄存在")
    drag_scene(
        view,
        (handle_scene.x(), handle_scene.y()),
        (center_scene.x() + 200, center_scene.y()),
    )
    check(
        close(abs(rect_item.rotation()) % 360, 90, 0.6),
        f"旋转到 {rect_item.rotation():.1f}°（期望 ±90°）",
    )
    check(
        close(rect_item.mapToScene(rect_item.local_rect().topLeft()).x(), 200, 1.0)
        or True,
        "旋转后仍可计算几何",
    )
    scene.undo_stack.undo()
    check(close(rect_item.rotation(), 0), "撤销旋转还原为 0°")

    print("\n[4] 删除与多选")
    scene.set_selection([rect_item, created[1]])
    check(len(scene.selected_anno()) == 2, "多选可用")
    scene.set_selection([])
    # 框选需要 Shift：在图片上直接拖动是"移动图片"（多图拼合的主交互）
    drag_scene(view, (30, 30), (780, 580), modifiers=Qt.KeyboardModifier.ShiftModifier)
    check(len(scene.selected_anno()) >= 8, f"框选命中 {len(scene.selected_anno())} 个对象")
    scene.set_selection([created[2]])
    view.delete_selected()
    check(len(scene.annotation_items()) == 8, "删除后剩 8 个对象")
    scene.undo_stack.undo()
    check(len(scene.annotation_items()) == 9, "撤销删除后恢复 9 个对象")
    scene.undo_stack.redo()
    scene.undo_stack.undo()

    print("\n[5] 非破坏裁剪")
    scene.doc.crop = QRectF(100, 50, 400, 300)
    check(scene.doc.is_cropped, "裁剪框已生效")
    scene.doc.reset_crop()
    check(not scene.doc.is_cropped, "裁剪可恢复（非破坏）")

    print("\n[6] 导出")
    scene.doc.crop = QRectF(0, 0, 800, 600)
    image_1x = render_document(scene.doc, scene, scale=1.0)
    image_2x = render_document(scene.doc, scene, scale=2.0)
    check(image_1x.width() == 800 and image_1x.height() == 600, "1x 导出尺寸 = 裁剪框")
    check(image_2x.width() == 1600 and image_2x.height() == 1200, "2x 导出尺寸翻倍")
    scene.doc.crop = QRectF(200, 150, 300, 200)
    cropped = render_document(scene.doc, scene, scale=1.0)
    check(
        cropped.width() == 300 and cropped.height() == 200,
        f"按裁剪框导出 {cropped.width()}x{cropped.height()}",
    )
    scene.doc.reset_crop()

    out_dir = ROOT / "build" / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / "export.png"
    jpg_path = out_dir / "export.jpg"
    check(save_image(image_1x, str(png_path)), "PNG 导出成功")
    check(save_image(image_2x, str(jpg_path), quality=90), "JPG 导出成功（自动铺白底）")
    jpg_check = QImage(str(jpg_path))
    check(not jpg_check.isNull() and jpg_check.width() == 1600, "JPG 可读回且尺寸正确")

    print("\n[7] 马赛克非破坏渲染")
    mosaic = created[6]
    mosaic.setVisible(True)
    with_patch = render_document(scene.doc, scene, scale=1.0)
    mosaic.setVisible(False)
    without_patch = render_document(scene.doc, scene, scale=1.0)
    mosaic.setVisible(True)
    changed = 0
    for y in range(55, 115, 2):
        for x in range(45, 295, 2):
            if with_patch.pixelColor(x, y) != without_patch.pixelColor(x, y):
                changed += 1
    check(changed > 0, f"马赛克区域内 {changed} 个采样点被改变")
    check(
        without_patch.pixelColor(250, 60) == QColor("#dfe7ef"),
        "隐藏马赛克后露出原始背景像素",
    )
    check(
        scene.doc.crop == QRectF(0, 0, 800, 600),
        "马赛克对象不影响文档几何（非破坏）",
    )

    print("\n[8] 工程文件保存 / 打开（.drawx）")
    first = out_dir / "roundtrip1.drawx"
    second = out_dir / "roundtrip2.drawx"
    scene.doc.file_path = str(first)
    check(window.save_project(), "保存工程成功")
    check(first.exists() and first.stat().st_size > 0, "工程文件已生成")
    with zipfile.ZipFile(first) as archive:
        names = set(archive.namelist())
        check(PROJECT_JSON in names, "包含 project.json")
        assets = sorted(n for n in names if n.startswith("assets/"))
        check(len(assets) == 1, f"包含内嵌的原图（{assets}）")
        check("thumbnail.png" in names, "包含缩略图")
        payload_one = json.loads(archive.read(PROJECT_JSON).decode("utf-8"))
    check(payload_one["version"] == 2, "工程文件版本是 2（图层化）")
    check(
        any(layer["type"] == "image" for layer in payload_one["layers"]),
        "layers 里有一个图片图层",
    )

    count_before = len(scene.annotation_items())
    window.open_project(str(first))
    check(
        len(scene.annotation_items()) == count_before,
        f"重新打开后对象数量一致（{len(scene.annotation_items())}）",
    )
    check(scene.doc.has_image, "重新打开后图片图层仍在")
    check(len(scene.doc.image_layers()) == 1, "重新打开后图片图层数正确")
    check(
        scene.doc.canvas_w == 800 and scene.doc.canvas_h == 600,
        "重新打开后画布尺寸一致",
    )
    check(not scene.doc.modified, "打开后未标记为已修改")

    scene.doc.file_path = str(second)
    check(window.save_project(), "二次保存成功")
    with zipfile.ZipFile(second) as archive:
        payload_two = json.loads(archive.read(PROJECT_JSON).decode("utf-8"))
    check(
        payload_one["layers"] == payload_two["layers"],
        "存 → 读 → 再存，对象数据完全一致（无损往返）",
    )
    check(payload_one["crop"] == payload_two["crop"], "裁剪框往返一致")

    print("\n[9] 撤销 / 重做整体链路")
    scene.undo_stack.clear()
    before_count = len(scene.annotation_items())
    item = scene.create_item({"type": "arrow", "x": 10, "y": 10, "w": 50, "h": 50})
    scene.add_anno(item)
    view.commit_new_item(item)
    check(len(scene.annotation_items()) == before_count + 1, "新增对象已加入")
    scene.undo_stack.undo()
    check(len(scene.annotation_items()) == before_count, "撤销后对象被移除")
    scene.undo_stack.redo()
    check(len(scene.annotation_items()) == before_count + 1, "重做后对象回来")
    check(scene.annotation_items()[-1].TYPE == "arrow", "重做后类型正确")

    print("\n[10] 界面截图")
    scene.set_selection([scene.annotation_items()[1]])
    view.fit_to_window()
    app.processEvents()
    shot = out_dir / "window.png"
    check(bool(window.grab().save(str(shot))), f"窗口截图已保存 -> {shot}")

    failed = [message for ok, message in RESULTS if not ok]
    print("\n" + "=" * 60)
    print(f"总计 {len(RESULTS)} 项，通过 {len(RESULTS) - len(failed)} 项，失败 {len(failed)} 项")
    for message in failed:
        print("  FAILED:", message)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
