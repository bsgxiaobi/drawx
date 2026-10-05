"""工具交互测试：直接驱动各绘制工具与属性面板。

运行：.venv\\Scripts\\python.exe tests\\interaction_test.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402

from drawx.app import create_application  # noqa: E402
from drawx.items.text import TextItem  # noqa: E402
from drawx.ui.main_window import MainWindow  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def check(condition: bool, message: str) -> None:
    RESULTS.append((bool(condition), message))
    print(("  PASS  " if condition else "  FAIL  ") + message)


def close(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) <= tol


class FakeEvent:
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


def drag_scene(view, start, end, steps=8, modifiers=None):
    transform = view.viewportTransform()
    start_point = transform.map(QPointF(start[0], start[1]))
    end_point = transform.map(QPointF(end[0], end[1]))
    view.tool.mouse_press(view, FakeEvent(start_point, modifiers=modifiers))
    for index in range(1, steps + 1):
        ratio = index / steps
        point = QPointF(
            start_point.x() + (end_point.x() - start_point.x()) * ratio,
            start_point.y() + (end_point.y() - start_point.y()) * ratio,
        )
        view.tool.mouse_move(view, FakeEvent(point, modifiers=modifiers))
    view.tool.mouse_release(view, FakeEvent(end_point, modifiers=modifiers))


def make_background(width: int = 900, height: int = 600) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#f2f4f7"))
    painter = QPainter(image)
    painter.setPen(QColor("#20304a"))
    painter.drawText(60, 90, "Invoice 2024-0912  Total 1280.00")
    painter.fillRect(500, 300, 200, 120, QColor("#88b04b"))
    painter.end()
    return image


def main() -> int:
    app = create_application([])
    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    view = window.view
    scene = window.scene
    window.add_image_layer(make_background())
    view.zoom_reset()
    # 导入图片现在也是一条可撤销命令，清掉它才能用"撤销条数"验证后面的操作
    scene.undo_stack.clear()

    print("\n[1] 矩形工具：拖动创建 + 撤销/重做")
    view.set_tool("rect")
    view.default_style["stroke"] = "#ff3b30"
    drag_scene(view, (100, 100), (300, 220))
    items = scene.annotation_items()
    check(len(items) == 1, f"创建了 1 个对象（实际 {len(items)}）")
    rect = items[0]
    check(rect.TYPE == "rect", "类型为 rect")
    check(
        close(rect.pos().x(), 100) and close(rect.pos().y(), 100),
        f"左上角 {rect.pos().x():.0f},{rect.pos().y():.0f}",
    )
    check(
        close(rect.local_rect().width(), 200) and close(rect.local_rect().height(), 120),
        f"尺寸 {rect.local_rect().width():.0f}x{rect.local_rect().height():.0f}",
    )
    check(rect.isSelected(), "创建后自动选中")
    check(rect.style["stroke"] == "#ff3b30", "使用了属性面板里的描边色")
    check(scene.undo_stack.count() == 1, "产生 1 条撤销记录")
    scene.undo_stack.undo()
    check(len(scene.annotation_items()) == 0, "撤销后对象消失")
    scene.undo_stack.redo()
    check(len(scene.annotation_items()) == 1 and scene.annotation_items()[0] is rect, "重做复用同一对象")
    scene.undo_stack.clear()

    print("\n[2] Shift 约束正方形 / Alt 从中心画")
    view.set_tool("rect")
    drag_scene(view, (400, 100), (560, 200), modifiers=Qt.KeyboardModifier.ShiftModifier)
    square = scene.annotation_items()[-1]
    check(
        close(square.local_rect().width(), square.local_rect().height()),
        f"Shift 画出正方形 {square.local_rect().width():.0f}x{square.local_rect().height():.0f}",
    )
    scene.undo_stack.undo()

    print("\n[3] 椭圆 / 直线 / 箭头")
    view.set_tool("ellipse")
    drag_scene(view, (400, 300), (560, 400))
    ellipse = scene.annotation_items()[-1]
    check(ellipse.TYPE == "ellipse", "椭圆创建成功")

    view.set_tool("line")
    drag_scene(view, (620, 120), (800, 200))
    line = scene.annotation_items()[-1]
    check(line.TYPE == "line", "直线创建成功")
    check(
        close(line.p1.x(), 0) and close(line.p1.y(), 0) and close(line.p2.x(), 180),
        f"直线端点 p1={line.p1.x():.0f},{line.p1.y():.0f} p2={line.p2.x():.0f},{line.p2.y():.0f}",
    )

    view.set_tool("arrow")
    drag_scene(view, (620, 240), (800, 240))
    arrow = scene.annotation_items()[-1]
    check(arrow.TYPE == "arrow", "箭头创建成功")
    check(
        close(arrow.p2.x(), 180) and close(arrow.p2.y(), 0),
        f"箭头为水平（p2={arrow.p2.x():.0f},{arrow.p2.y():.0f}）",
    )
    check(arrow.head == "end", "默认末端箭头")

    print("\n[4] 画笔 / 高亮")
    view.set_tool("freehand")
    drag_scene(view, (100, 420), (300, 500), steps=20)
    pen = scene.annotation_items()[-1]
    check(pen.TYPE == "freehand", "画笔创建成功")
    check(len(pen.points) > 3, f"记录了 {len(pen.points)} 个轨迹点")

    view.set_tool("highlight")
    view.default_style["stroke"] = "#ffd60a"
    drag_scene(view, (350, 420), (600, 470), steps=15)
    highlight = scene.annotation_items()[-1]
    check(highlight.TYPE == "highlight", "高亮创建成功")
    check(
        close(highlight.style["opacity"], 0.38),
        f"高亮默认半透明（opacity={highlight.style['opacity']}）",
    )
    # 工具自带的默认样式不能覆盖用户手动调过的值
    view.user_style_keys.add("opacity")
    view.default_style["opacity"] = 1.0
    drag_scene(view, (350, 500), (600, 540), steps=10)
    opaque = scene.annotation_items()[-1]
    check(
        close(opaque.style["opacity"], 1.0),
        f"用户在面板里调过不透明度后，高亮不再强制半透明（opacity={opaque.style['opacity']}）",
    )
    view.user_style_keys.discard("opacity")
    view.default_style["opacity"] = 1.0
    drag_scene(view, (350, 560), (600, 580), steps=8)
    check(
        close(scene.annotation_items()[-1].style["opacity"], 0.38),
        "没调过不透明度时，高亮仍然默认半透明",
    )

    print("\n[5] 马赛克 / 模糊")
    view.set_tool("mosaic")
    drag_scene(view, (40, 60), (420, 110))
    mosaic = scene.annotation_items()[-1]
    check(mosaic.TYPE == "mosaic", "马赛克区域创建成功")
    check(close(mosaic.block, 12.0), f"默认强度 {mosaic.block}")
    view.set_tool("blur")
    drag_scene(view, (500, 300), (700, 420))
    blur = scene.annotation_items()[-1]
    check(blur.TYPE == "blur", "模糊区域创建成功")

    print("\n[6] 文字：落点输入 → 提交 / 空文字丢弃")
    view.set_tool("text")
    view.default_style["fontSize"] = 24.0
    transform = view.viewportTransform()
    view.tool.mouse_press(view, FakeEvent(transform.map(QPointF(120, 540))))
    check(view._edit_item is not None, "落点后进入编辑态")
    editing = view._edit_item
    check(isinstance(editing, TextItem), "新建的是文字对象")
    check(editing.editing, "文字交互标志已开启")
    editing.setPlainText("付款金额：1280.00 元")
    view.finish_text_edit()
    check(view._edit_item is None, "编辑结束")
    check(editing in scene.annotation_items(), "有内容的文字已提交")
    check(scene.undo_stack.count() > 0, "文字提交进入撤销栈")

    view.tool.mouse_press(view, FakeEvent(transform.map(QPointF(400, 540))))
    empty = view._edit_item
    view.finish_text_edit()
    check(empty not in scene.annotation_items(), "空文字对象被自动丢弃")

    view.tool.mouse_press(view, FakeEvent(transform.map(QPointF(120, 540))))
    existing = view._edit_item
    before_text = existing.toPlainText()
    existing.setPlainText(before_text + "（已核对）")
    view.finish_text_edit()
    check(
        "已核对" in existing.toPlainText(),
        "双击已有文字可再次编辑（关键差异点：对象可反复修改）",
    )

    # 文字编辑期间，会抢按键的动作必须被禁用（否则打字会触发工具切换/删除/撤销）
    view.tool.mouse_press(view, FakeEvent(transform.map(QPointF(120, 540))))
    check(view._edit_item is not None, "再次进入编辑态")
    guard_names = ("act_undo", "act_redo", "act_select_all", "act_delete", "act_copy")
    disabled = [name for name in guard_names if not getattr(window, name).isEnabled()]
    check(
        len(disabled) == len(guard_names),
        f"编辑期间这些动作被禁用：{disabled}",
    )
    view.finish_text_edit()
    still = [name for name in guard_names if not getattr(window, name).isEnabled()]
    check(not still, f"编辑结束后动作恢复可用（仍禁用：{still}）")

    print("\n[7] 裁剪工具（非破坏）")
    view.set_tool("crop")
    scene.doc.reset_crop()
    drag_scene(view, (200, 150), (700, 500))
    check(
        close(scene.doc.crop.x(), 200)
        and close(scene.doc.crop.y(), 150)
        and close(scene.doc.crop.width(), 500)
        and close(scene.doc.crop.height(), 350),
        f"裁剪框变为 {scene.doc.crop.x():.0f},{scene.doc.crop.y():.0f} "
        f"{scene.doc.crop.width():.0f}x{scene.doc.crop.height():.0f}",
    )
    check(scene.undo_stack.count() > 0, "裁剪进入撤销栈")
    scene.undo_stack.undo()
    check(not scene.doc.is_cropped, "撤销后恢复为完整画面（非破坏）")

    print("\n[8] 属性面板：改选中对象的样式 + 撤销")
    view.set_tool("select")
    scene.set_selection([rect])
    panel = window.property_panel
    panel._apply("stroke", "#2f7cf6")
    check(rect.style["stroke"] == "#2f7cf6", "描边色已改到选中对象上")
    scene.undo_stack.undo()
    check(rect.style["stroke"] == "#ff3b30", "撤销后描边色还原")
    panel._on_width_changed(9)
    check(close(rect.style["strokeWidth"], 9.0), f"线宽改为 {rect.style['strokeWidth']}")
    scene.set_selection([])
    panel._apply("stroke", "#34c759")
    check(
        view.default_style["stroke"] == "#34c759",
        "无选中时改的是新对象默认样式",
    )
    check(rect.style["stroke"] == "#2f7cf6" or rect.style["stroke"] == "#ff3b30", "不影响已有对象")

    print("\n[9] 层级与删除")
    count = len(scene.annotation_items())
    scene.set_selection([scene.annotation_items()[0]])
    view.delete_selected()
    check(len(scene.annotation_items()) == count - 1, "删除生效")
    scene.undo_stack.undo()
    check(len(scene.annotation_items()) == count, "撤销删除恢复")
    scene.select_all()
    check(len(scene.selected_anno()) == count, "全选")
    scene.set_selection([])

    print("\n[10] 导出包含全部标注")
    scene.doc.reset_crop()
    from drawx.render.exporter import render_document, save_image

    out_dir = ROOT / "build" / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered = render_document(scene.doc, scene, scale=1.0)
    check(rendered.width() == 900 and rendered.height() == 600, "导出尺寸正确")
    check(
        bool(save_image(rendered, str(out_dir / "interaction_export.png"))),
        "导出文件写入成功",
    )
    app.processEvents()
    check(
        bool(window.grab().save(str(out_dir / "interaction_window.png"))),
        "窗口截图已保存",
    )

    failed = [message for ok, message in RESULTS if not ok]
    print("\n" + "=" * 60)
    print(f"总计 {len(RESULTS)} 项，通过 {len(RESULTS) - len(failed)} 项，失败 {len(failed)} 项")
    for message in failed:
        print("  FAILED:", message)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
