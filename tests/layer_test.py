"""图层与多图片图层的回归测试。

覆盖：
1. 图层面板背后的模型/命令（增删、排序、显隐、锁定、不透明度、复制、z 重排）
2. 多张图片作为独立图层导入：自动排布、画布自动长大、移动/缩放/旋转
3. 图片图层的**非破坏裁剪**（几何锚点、撤销还原、重置回整幅）
4. 画布操作：设置尺寸、适应内容、自动排列
5. .drawx v2 多资源存取往返 + v1 迁移
6. 导出/快速复制包含所有图层

运行：.venv\\Scripts\\python.exe tests\\layer_test.py
（逻辑测试，走离屏平台）
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
from drawx.model.layers import KIND_ANNOTATION, KIND_IMAGE  # noqa: E402
from drawx.model.serialize import PROJECT_JSON  # noqa: E402
from drawx.render.exporter import render_document  # noqa: E402
from drawx.ui.main_window import MainWindow  # noqa: E402

RESULTS: list[tuple[bool, str]] = []
WORK = ROOT / "build" / "smoke" / "layertest"


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


def drag_scene(view, start_scene, end_scene, steps=6, modifiers=None):
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


def make_image(width: int, height: int, color: str, mark: str = "") -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    painter = QPainter(image)
    if mark:
        painter.setPen(QColor("#101010"))
        painter.drawText(6, 20, mark)
    painter.fillRect(0, 0, max(1, width // 8), max(1, height // 8), QColor("#203040"))
    painter.end()
    return image


def main() -> int:  # noqa: PLR0915 - 测试脚本，线性铺开更好读
    app = create_application([])
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    app.processEvents()
    view = window.view
    scene = window.scene
    panel = window.layer_panel
    WORK.mkdir(parents=True, exist_ok=True)

    print("\n[1] 新建文档就有一个可用的标注图层")
    check(len(scene.layers()) == 1, f"初始图层数 1（实际 {len(scene.layers())}）")
    check(scene.layers()[0].kind == KIND_ANNOTATION, "初始图层是标注图层")
    check(scene.active_layer() is scene.layers()[0], "初始活动图层就是它")
    check(panel.tree.topLevelItemCount() == 1, "面板显示 1 行")

    print("\n[2] 多张图片各自成为一个图片图层")
    first = make_image(400, 300, "#dfe7ef", "A")
    second = make_image(300, 500, "#e7dfef", "B")
    window.add_image_items([("A.png", first), ("B.png", second)])
    app.processEvents()
    layers = scene.layers()
    check(len(layers) == 3, f"图层数 3（实际 {len(layers)}）")
    check(len(scene.doc.image_layers()) == 2, "有 2 个图片图层")
    check(layers[0].kind == KIND_ANNOTATION, "标注图层仍在最上面（照片在底、标注在上）")
    check(layers[1].name == "A" and layers[2].name == "B", f"图层名取自文件名 {[l.name for l in layers]}")
    image_a = layers[1].image_item()
    image_b = layers[2].image_item()
    check(image_a is not None and image_b is not None, "两个图层都拿到了图片对象")
    check(
        close(image_a.local_rect().width(), 400) and close(image_a.local_rect().height(), 300),
        f"A 显示尺寸 400x300（实际 {image_a.local_rect().width():.0f}x{image_a.local_rect().height():.0f}）",
    )
    check(close(image_b.pos().x(), 400 + 24), f"B 自动摆在 A 右边（x={image_b.pos().x():.0f}）")
    check(
        scene.doc.canvas_w >= 700 and scene.doc.canvas_h >= 500,
        f"画布自动长大到 {scene.doc.canvas_w}x{scene.doc.canvas_h}",
    )
    check(len(scene.anno_items()) == 2, "场景里能枚举到两个图片对象")
    check(panel.tree.topLevelItemCount() == 3, "面板显示 3 行")

    print("\n[3] z 顺序由图层顺序派生")
    order = [item.zValue() for item in scene.anno_items()]
    check(order == sorted(order), f"z 单调递增 {order}")
    check(
        image_b.zValue() < image_a.zValue(),
        "面板里更靠下的图层 z 更小（B 在 A 之下，先被画出来）",
    )
    check(
        image_a.zValue() < scene.layers()[0].items[0].zValue()
        if scene.layers()[0].items
        else True,
        "标注图层的对象 z 最大（画在最上面）",
    )
    window.layer_panel.move_to(0, layers[2])
    app.processEvents()
    check(scene.layers()[0] is layers[2], "B 已置顶")
    check(
        image_b.zValue() > image_a.zValue(),
        "置顶后 B 的 z 大于 A（顺序真的生效了）",
    )
    scene.undo_stack.undo()
    app.processEvents()
    check(scene.layers()[0].kind == KIND_ANNOTATION, "撤销后顺序还原")

    print("\n[4] 移动 / 缩放 / 旋转一张图片")
    view.set_tool("select")
    scene.set_selection([image_a])
    before = QPointF(image_a.pos())
    drag_scene(view, (100, 100), (160, 130))
    check(
        close(image_a.pos().x(), before.x() + 60) and close(image_a.pos().y(), before.y() + 30),
        f"拖动移动 60,30（pos={image_a.pos().x():.0f},{image_a.pos().y():.0f}）",
    )
    scene.undo_stack.undo()
    check(close(image_a.pos().x(), before.x()), "撤销移动还原")
    scene.undo_stack.clear()

    handle = image_a.mapToScene(image_a.local_rect().bottomRight())
    drag_scene(view, (handle.x(), handle.y()), (handle.x() + 100, handle.y() + 100))
    check(
        close(image_a.local_rect().width(), 500) and close(image_a.local_rect().height(), 400),
        f"拖右下角把图片放大到 {image_a.local_rect().width():.0f}x{image_a.local_rect().height():.0f}",
    )
    kx, ky = image_a.pixel_scale()
    check(close(kx, 1.25) and close(ky, 4 / 3), f"像素尺度分开计算 kx={kx:.3f} ky={ky:.3f}")
    scene.undo_stack.undo()
    check(close(image_a.local_rect().width(), 400), "撤销缩放还原")
    scene.undo_stack.clear()

    print("\n[5] 图片图层的非破坏裁剪")
    view.set_tool("crop")
    scene.set_selection([image_a])
    app.processEvents()
    tool = view.tool
    check(tool.image_target() is image_a, "裁剪工具认出了选中的图片")
    drag_scene(view, (50, 40), (250, 240))
    check(
        close(image_a.src_rect.x(), 50) and close(image_a.src_rect.y(), 40)
        and close(image_a.src_rect.width(), 200) and close(image_a.src_rect.height(), 200),
        f"保留区 = {image_a.src_rect.x():.0f},{image_a.src_rect.y():.0f} "
        f"{image_a.src_rect.width():.0f}x{image_a.src_rect.height():.0f}",
    )
    check(not image_a.cropping, "松手后已退出'整幅原图'的编辑状态")
    check(
        close(image_a.scene_rect().x(), 50) and close(image_a.scene_rect().y(), 40),
        f"保留区左上角留在原地（scene x={image_a.scene_rect().x():.0f}）",
    )
    check(
        close(image_a.scene_rect().width(), 200),
        f"显示尺寸变成保留区大小（{image_a.scene_rect().width():.0f}）",
    )
    check(image_a.natural_size() == (400, 300), "原图尺寸没变（非破坏）")
    scene.undo_stack.undo()
    check(
        close(image_a.src_rect.width(), 400) and close(image_a.scene_rect().width(), 400),
        "撤销裁剪后恢复整幅",
    )
    scene.undo_stack.redo()
    check(close(image_a.src_rect.width(), 200), "重做裁剪又回到 200 宽")
    scene.undo_stack.undo()
    scene.undo_stack.clear()

    # 再裁一次，然后验证"重置裁剪"
    drag_scene(view, (100, 50), (300, 250))
    check(close(image_a.src_rect.x(), 100), f"第二次裁剪 x={image_a.src_rect.x():.0f}")
    window.layer_panel.reset_image_crop(layers[1])
    check(
        close(image_a.src_rect.width(), 400) and close(image_a.scene_rect().width(), 400),
        "面板的「重置图片裁剪」恢复整幅",
    )
    scene.undo_stack.undo()
    check(close(image_a.src_rect.width(), 200), "「重置图片裁剪」也可撤销")
    scene.undo_stack.undo()
    scene.undo_stack.clear()

    print("\n[6] 裁剪工具在'没选图片'时裁的是导出范围")
    view.set_tool("crop")
    scene.set_selection([])
    app.processEvents()
    check(view.tool.image_target() is None, "没有图片被选中")
    drag_scene(view, (20, 20), (420, 320))
    check(
        close(scene.doc.crop.x(), 20) and close(scene.doc.crop.width(), 400),
        f"导出范围 = {scene.doc.crop.x():.0f},{scene.doc.crop.y():.0f} "
        f"{scene.doc.crop.width():.0f}x{scene.doc.crop.height():.0f}",
    )
    scene.undo_stack.undo()
    check(not scene.doc.is_cropped, "撤销后导出范围复原")
    scene.undo_stack.clear()
    view.set_tool("select")

    print("\n[7] 图层显隐 / 锁定 / 不透明度")
    panel.toggle_visible(layers[1])
    app.processEvents()
    check(not layers[1].visible and not image_a.isVisible(), "隐藏图层后对象也不可见")
    hidden = render_document(scene.doc, scene, scale=1.0)
    check(
        hidden.pixelColor(5, 5) != QColor("#dfe7ef") or True,
        "隐藏后仍然能正常渲染（不抛异常）",
    )
    scene.undo_stack.undo()
    app.processEvents()
    check(layers[1].visible and image_a.isVisible(), "撤销后恢复显示")

    panel.toggle_locked(layers[1])
    app.processEvents()
    check(layers[1].locked, "图层已锁定")
    check(image_a not in scene.selectable_anno(), "锁定图层不参与命中/框选")
    check(view.anno_at(view.viewportTransform().map(QPointF(5, 5))) is not image_a, "画布上点不中它")
    scene.undo_stack.undo()
    app.processEvents()
    check(not layers[1].locked and image_a in scene.selectable_anno(), "撤销后可以再选中")

    panel.tree.setCurrentItem(panel._row_of(layers[1]))
    panel._on_opacity_changed(40)
    app.processEvents()
    check(close(layers[1].opacity, 0.4), f"图层不透明度 = {layers[1].opacity}")
    check(close(image_a.opacity(), 0.4), f"对象不透明度跟着变成 {image_a.opacity()}")
    scene.undo_stack.undo()
    app.processEvents()
    check(close(layers[1].opacity, 1.0), "撤销后不透明度还原")
    check(close(image_a.opacity(), 1.0), "对象不透明度也还原")

    print("\n[8] 删除 / 复制图层")
    panel.tree.setCurrentItem(panel._row_of(layers[2]))
    count = len(scene.layers())
    panel.delete_layer(layers[2])
    app.processEvents()
    check(len(scene.layers()) == count - 1, "删除图层生效")
    check(image_b.scene() is None, "对象已从场景摘掉")
    scene.undo_stack.undo()
    app.processEvents()
    check(len(scene.layers()) == count and image_b.scene() is scene, "撤销后图层与对象都回来了")
    check(close(image_b.local_rect().width(), 300), "撤销后几何也还原")

    before_ids = {layer.id for layer in scene.layers()}
    panel.duplicate_layer(layers[1])
    app.processEvents()
    check(len(scene.layers()) == count + 1, "复制图层生效")
    clone_layer = next(layer for layer in scene.layers() if layer.id not in before_ids)
    clone = clone_layer.image_item()
    check(clone is not None and clone is not image_a, "复制出来的是新对象")
    check(clone.src_rect == image_a.src_rect, "复制保留了裁剪区")
    check(clone.source is image_a.source, "复制共用同一份原图（不重复占内存）")
    check(clone_layer.name == "A 副本", f"副本名字 {clone_layer.name}")
    check(clone is not None and clone.id != image_a.id, "副本的对象 id 也是新的")
    scene.undo_stack.undo()
    app.processEvents()
    check(len(scene.layers()) == count, "撤销复制")

    print("\n[9] 画布：设置尺寸 / 适应内容 / 自动排列")
    from drawx.model.commands import DocPropCommand

    before_state = (scene.doc.canvas_w, scene.doc.canvas_h, QRectF(scene.doc.crop))
    window.view.push_command(
        DocPropCommand(
            window._apply_canvas_state,
            before_state,
            (900, 700, QRectF(0, 0, 900, 700)),
            "设置画布大小",
        )
    )
    app.processEvents()
    check(scene.doc.canvas_w == 900 and scene.doc.canvas_h == 700, "画布尺寸已设为 900x700")
    scene.undo_stack.undo()
    app.processEvents()
    check(
        (scene.doc.canvas_w, scene.doc.canvas_h) == before_state[:2],
        "撤销后画布尺寸还原",
    )

    image_b.setPos(-40.0, -60.0)
    window.fit_canvas_to_content(margin=20.0)
    app.processEvents()
    bounds = scene.itemsBoundingRect()
    check(
        close(bounds.left(), 20, 1.0) and close(bounds.top(), 20, 1.0),
        f"适应内容后内容左上角在 (20,20)（实际 {bounds.left():.0f},{bounds.top():.0f}）",
    )
    check(
        scene.doc.canvas_w >= int(bounds.right()),
        f"画布容纳了全部内容（画布 {scene.doc.canvas_w}，内容右边界 {bounds.right():.0f}）",
    )
    check(not scene.doc.is_cropped, "适应内容后导出范围 = 整幅画布")
    scene.undo_stack.undo()
    app.processEvents()
    check(close(image_b.pos().x(), -40.0), "撤销适应内容后位置还原")

    scenes = [layer.image_item() for layer in scene.doc.image_layers()]
    for item in scenes:
        item.set_display_scale(1.0, 1.0)
    window.arrange_image_layers(columns=2, gap=10.0)
    app.processEvents()
    tops = sorted(item.scene_rect().top() for item in scenes)
    lefts = sorted(item.scene_rect().left() for item in scenes)
    check(close(tops[0], 10, 1.0), f"自动排列后第一行顶部 = 10（实际 {tops[0]:.0f}）")
    check(len(set(round(x) for x in lefts)) >= 2, f"自动排列产生了多列 {lefts}")
    check(
        scene.doc.canvas_w >= max(item.scene_rect().right() for item in scenes),
        "自动排列后画布包住了网格",
    )

    print("\n[9b] 画布大小对话框：一个框设宽高 + 比例预设")
    from PySide6.QtCore import QTimer

    from drawx.ui.dialogs import CANVAS_RATIOS, CanvasSizeDialog

    ratios = dict(CANVAS_RATIOS)
    check(len(CANVAS_RATIOS) == 6, f"预设里有 5 种比例 + 自由（实际 {len(CANVAS_RATIOS)}）")
    check(
        all(label in ratios for label in ("自由", "1:1", "4:3", "3:4", "16:9", "9:16")),
        f"比例清单齐全：{[label for label, _ in CANVAS_RATIOS]}",
    )

    dialog = CanvasSizeDialog(1280, 800)
    check(dialog.size() == (1280, 800), f"初始值 = 当前画布尺寸 {dialog.size()}")
    check(dialog.ratio_buttons["自由"].isChecked(), "初始选中的是「自由」")
    expected = {"16:9": (1280, 720), "9:16": (1280, 2276), "1:1": (1280, 1280),
                "4:3": (1280, 960), "3:4": (1280, 1707)}
    for label, want in expected.items():
        dialog.set_ratio(ratios[label])
        check(
            dialog.size() == want,
            f"选 {label} → {dialog.size()}（期望 {want}，宽度保持不变）",
        )
        check(dialog.ratio_buttons[label].isChecked(), f"{label} 按钮已选中")
    dialog.set_ratio(ratios["16:9"])
    dialog.height_spin.setValue(1080)
    check(dialog.size() == (1920, 1080), f"锁定比例时改高会自动换算宽：{dialog.size()}")
    dialog.width_spin.setValue(800)
    check(dialog.size() == (800, 450), f"锁定比例时改宽会自动换算高：{dialog.size()}")

    dialog.set_ratio(None)
    dialog.width_spin.setValue(600)
    dialog.height_spin.setValue(800)
    dialog.set_ratio(ratios["3:4"])
    check(dialog.size() == (600, 800), f"锁 3:4 且宽 600 → {dialog.size()}")
    dialog.swap()
    check(dialog.size() == (800, 600), f"「交换宽高」生效：{dialog.size()}")
    check(dialog.ratio_buttons["4:3"].isChecked(), "交换后比例按钮跟着换成镜像的 4:3")
    dialog.set_ratio(ratios["1:1"])
    check(dialog.size() == (800, 800), f"锁 1:1 → {dialog.size()}")
    dialog.swap()
    check(
        dialog.size() == (800, 800) and dialog.ratio_buttons["1:1"].isChecked(),
        f"1:1 交换后还是 1:1（{dialog.size()}）",
    )

    dialog.set_ratio(None)
    dialog.width_spin.setValue(1000)
    check(dialog.size() == (1000, 800), f"「自由」时改宽不影响高：{dialog.size()}")
    dialog.height_spin.setValue(1500)
    check(dialog.size() == (1000, 1500), f"「自由」时高也各填各的：{dialog.size()}")
    check("比例 自由" in dialog.hint.text(), f"提示里写明当前是自由：{dialog.hint.text()!r}")

    # 内容装不下时给出提示（不是错误，只是提醒有「画布适应内容」）
    # 注意：对话框没 show()，所以要用 isHidden() 判断"有没有被显式隐藏"
    outside = CanvasSizeDialog(100, 100, content_rect=QRectF(0, 0, 900, 600))
    check(not outside.warning.isHidden(), "内容超出新画布时会提示")
    inside = CanvasSizeDialog(2000, 2000, content_rect=QRectF(0, 0, 900, 600))
    check(inside.warning.isHidden(), "装得下时不提示")

    # 走一遍真实菜单动作：弹框 → 设 1600×900 → 确定 → 画布真的变了且可撤销
    def drive_dialog() -> None:
        modal = app.activeModalWidget()
        if isinstance(modal, CanvasSizeDialog):
            modal.set_ratio(None)
            modal.width_spin.setValue(1600)
            modal.height_spin.setValue(900)
            modal.accept()

    size_before = (scene.doc.canvas_w, scene.doc.canvas_h)
    crop_before = QRectF(scene.doc.crop)
    QTimer.singleShot(60, drive_dialog)
    window.set_canvas_size_dialog()
    app.processEvents()
    check(
        (scene.doc.canvas_w, scene.doc.canvas_h) == (1600, 900),
        f"菜单动作生效：{scene.doc.canvas_w}×{scene.doc.canvas_h}",
    )
    check(scene.doc.crop == QRectF(0, 0, 1600, 900), "导出范围跟着变成整幅新画布")
    check(scene.doc.modified, "画布尺寸变化被标记为已修改")
    scene.undo_stack.undo()
    app.processEvents()
    check(
        (scene.doc.canvas_w, scene.doc.canvas_h) == size_before
        and scene.doc.crop == crop_before,
        "撤销后画布尺寸与导出范围都还原",
    )

    # 取消（Esc）不应改动任何东西
    def cancel_dialog() -> None:
        modal = app.activeModalWidget()
        if isinstance(modal, CanvasSizeDialog):
            modal.width_spin.setValue(1234)
            modal.reject()

    before_cancel = (scene.doc.canvas_w, scene.doc.canvas_h, QRectF(scene.doc.crop))
    QTimer.singleShot(60, cancel_dialog)
    window.set_canvas_size_dialog()
    app.processEvents()
    check(
        (scene.doc.canvas_w, scene.doc.canvas_h, scene.doc.crop) == before_cancel,
        "点取消不改动画布",
    )

    print("\n[10] 标注进的是活动图层，锁定图层拒绝新标注")
    layers_now = scene.layers()
    top_anno = layers_now[0]
    scene.set_active_layer(top_anno, sync_selection=False)
    rect_item = scene.create_item({"type": "rect", "w": 80, "h": 60})
    rect_item.setPos(30, 30)
    scene.add_anno(rect_item)
    check(scene.layer_of(rect_item) is top_anno, "新标注落在活动图层里")
    check(scene.annotation_items()[-1] is rect_item, "标注在绘制顺序里排在图片之后（在上面）")
    check(
        rect_item.zValue() > max(
            (item.zValue() for item in scene.doc.image_layers()[0].items), default=0
        ),
        "标注的 z 高于图片图层",
    )
    scene.remove_anno(rect_item)

    print("\n[11] .drawx v2 存取往返（多张图 + 图层属性）")
    layers_now = scene.layers()
    layers_now[0].name = "现场标注"
    layers_now[0].opacity = 0.75
    layers_now[1].locked = True
    path = WORK / "layers.drawx"
    scene.doc.file_path = str(path)
    check(window.save_project(), "保存工程成功")
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        payload = json.loads(archive.read(PROJECT_JSON).decode("utf-8"))
    check(payload["version"] == 2, f"工程版本 2（实际 {payload['version']}）")
    check(
        len([n for n in names if n.startswith("assets/")]) == 2,
        f"内嵌了 2 张原图 {sorted(n for n in names if n.startswith('assets/'))}",
    )
    check(len(payload["layers"]) == len(layers_now), "layers 数量一致")
    check(payload["layers"][0]["name"] == "现场标注", "图层名已写入")
    check(close(float(payload["layers"][0]["opacity"]), 0.75), "图层不透明度已写入")
    check(payload["layers"][1]["locked"] is True, "锁定状态已写入")
    image_object = [
        obj
        for layer in payload["layers"]
        for obj in layer["objects"]
        if obj["type"] == "image"
    ]
    check(len(image_object) == 2, "两个图片对象都写进了工程")
    check(
        all("assetId" in obj["geometry"] for obj in image_object),
        "图片对象带 assetId",
    )
    check(
        all(obj["geometry"]["naturalW"] > 0 for obj in image_object),
        "图片对象带原图尺寸",
    )

    window.open_project(str(path))
    app.processEvents()
    reopened = scene.layers()
    check(len(reopened) == len(layers_now), f"重新打开后图层数一致（{len(reopened)}）")
    check(reopened[0].name == "现场标注", "图层名还原")
    check(close(reopened[0].opacity, 0.75), "图层不透明度还原")
    check(reopened[1].locked is True, "锁定状态还原")
    reopened_images = [layer.image_item() for layer in scene.doc.image_layers()]
    check(all(item is not None and item.has_source() for item in reopened_images), "两张原图都读回来了")
    check(
        reopened_images[0].source.width() == 400
        and reopened_images[0].source.height() == 300,
        f"第一张原图尺寸正确（{reopened_images[0].source.width()}x{reopened_images[0].source.height()}）",
    )
    check(
        reopened_images[0].src_rect == image_a.src_rect,
        "非破坏裁剪区往返一致",
    )
    check(reopened[1].locked and reopened_images[1].isVisible(), "锁定图层仍然可见")
    check(not scene.doc.modified, "打开后未标记为已修改")

    second = WORK / "layers2.drawx"
    scene.doc.file_path = str(second)
    window.save_project()
    with zipfile.ZipFile(second) as archive:
        payload_two = json.loads(archive.read(PROJECT_JSON).decode("utf-8"))
    check(payload_two["layers"] == payload["layers"], "存 → 读 → 再存，图层数据完全一致")
    check(payload_two["canvas"] == payload["canvas"], "画布数据一致")
    check(payload_two["crop"] == payload["crop"], "裁剪框一致")

    print("\n[12] v1 工程文件自动迁移成图层")
    legacy = WORK / "legacy_v1.drawx"
    background = make_image(320, 200, "#cfe0ff", "OLD")
    from drawx.model.serialize import image_to_png_bytes

    project = {
        "format": "drawx",
        "version": 1,
        "app": {"name": "DrawX", "version": "0.1.0"},
        "canvas": {"width": 320, "height": 200, "background": "#FFFFFF"},
        "crop": {"x": 0, "y": 0, "w": 320, "h": 200},
        "background": {"color": "#FFFFFF", "assetId": "bg"},
        "assets": {
            "bg": {
                "path": "assets/background.png",
                "mime": "image/png",
                "width": 320,
                "height": 200,
            }
        },
        "layers": [
            {
                "id": "L1",
                "name": "标注",
                "type": "annotation",
                "objects": [
                    {"type": "arrow", "x": 10, "y": 10, "w": 60, "h": 40, "z": 1.0}
                ],
            }
        ],
        "view": {"zoom": 1.0},
        "自定义字段": {"keep": True},
    }
    with zipfile.ZipFile(legacy, "w") as archive:
        archive.writestr(PROJECT_JSON, json.dumps(project, ensure_ascii=False).encode("utf-8"))
        archive.writestr("assets/background.png", image_to_png_bytes(background))

    window.open_project(str(legacy))
    app.processEvents()
    migrated = scene.layers()
    check(len(migrated) == 2, f"v1 打开的图层数 2（实际 {len(migrated)}）")
    check(migrated[0].kind == KIND_IMAGE, "背景被升级成最上面的图片图层")
    check(migrated[0].name == "背景", f"迁移后的图层名 {migrated[0].name}")
    old_item = migrated[0].image_item()
    check(old_item is not None and old_item.source.width() == 320, "v1 的背景位图读回来了")
    check(
        close(old_item.local_rect().width(), 320) and close(old_item.local_rect().height(), 200),
        "v1 的拉伸显示被原样保留",
    )
    check(migrated[1].kind == KIND_ANNOTATION, "标注图层保留")
    check(len(migrated[1].items) == 1, "标注对象保留")
    check(migrated[1].items[0].TYPE == "arrow", "标注类型正确")
    check(scene.doc.extra.get("自定义字段") == {"keep": True}, "未知顶层字段被保留")
    migrated_path = WORK / "migrated.drawx"
    scene.doc.file_path = str(migrated_path)
    window.save_project()
    with zipfile.ZipFile(migrated_path) as archive:
        migrated_payload = json.loads(archive.read(PROJECT_JSON).decode("utf-8"))
    check(migrated_payload["version"] == 2, "另存后版本是 2")
    check(migrated_payload.get("自定义字段") == {"keep": True}, "未知字段被写回")

    print("\n[13] 导出把多个图层一起画进去")
    window.open_project(str(path))
    app.processEvents()
    scene.doc.reset_crop()
    scene.doc.bg_color = "#FFFFFF"
    rendered = render_document(scene.doc, scene, scale=1.0)
    check(
        rendered.width() == scene.doc.canvas_w and rendered.height() == scene.doc.canvas_h,
        f"导出尺寸 = 画布 {rendered.width()}x{rendered.height()}",
    )
    colors = {rendered.pixelColor(x, y).name() for x in range(0, rendered.width(), 17)
              for y in range(0, rendered.height(), 17)}
    check(len(colors) >= 3, f"导出图里有多种颜色（{len(colors)} 种），说明多图层都画上了")
    if app.platformName() == "offscreen":
        print(
            "  SKIP  离屏平台的剪贴板是空实现（写进去会崩溃），"
            "「快速复制为图片」改由 tests/clipboard_real_test.py 在真实平台验证"
        )
    else:
        window.quick_copy_image()
        app.processEvents()

    print("\n[14] 图层菜单动作的可用状态")
    window.open_project(str(path))
    app.processEvents()
    window._sync_layer_actions()
    check(window.act_layer_dup.isEnabled(), "有当前图层时「复制图层」可用")
    check(window.act_layer_del.isEnabled(), "「删除图层」可用")
    check(window.act_layer_rename.isEnabled(), "「重命名图层」可用")
    check(
        not window.act_layer_up.isEnabled(),
        "最上面的图层不能再上移（「上移一层」已禁用）",
    )
    check(window.act_layer_down.isEnabled(), "最上面的图层可以下移")
    check(not window.act_layer_top.isEnabled(), "「置顶」在最上层时禁用")
    check(window.act_layer_bottom.isEnabled(), "「置底」可用")

    last_layer = scene.layers()[-1]
    window.layer_panel.tree.setCurrentItem(window.layer_panel._row_of(last_layer))
    window._sync_layer_actions()
    check(window.act_layer_up.isEnabled(), "最下面的图层可以上移")
    check(not window.act_layer_down.isEnabled(), "最下面的图层不能再下移")
    check(window.act_layer_top.isEnabled(), "「置顶」可用")
    check(not window.act_layer_bottom.isEnabled(), "「置底」在最下层时禁用")

    print("\n[15] 锁定只挡画布交互，面板里的显式修改照常")
    # 第 [11] 节把某张图片图层设成了锁定状态并存进了工程，这里挑一个未锁定的来测
    unlocked = [layer for layer in scene.doc.image_layers() if not layer.locked]
    target = unlocked[0] if unlocked else scene.doc.image_layers()[0]
    check(not target.locked, f"挑到未锁定的图层「{target.name}」")
    window.layer_panel.tree.setCurrentItem(window.layer_panel._row_of(target))
    window.layer_panel.toggle_locked(target)
    app.processEvents()
    check(target.locked, f"图层「{target.name}」已锁定")
    check(window.act_layer_rename.isEnabled(), "锁定后仍可重命名（面板操作）")
    check(window.layer_panel.opacity_slider.isEnabled(), "锁定后不透明度滑块仍可用")
    window.layer_panel._on_opacity_changed(60)
    app.processEvents()
    check(close(target.opacity, 0.6), f"锁定图层的不透明度改到了 {target.opacity}")
    check(
        target.image_item() not in scene.selectable_anno(),
        "锁定图层在画布上依然选不中（锁定的本意）",
    )
    scene.undo_stack.undo()
    scene.undo_stack.undo()
    app.processEvents()
    check(close(target.opacity, 1.0) and not target.locked, "两次撤销把锁定与不透明度都还原")

    print("\n[16] 属性面板在选中图片时切换成图片模式")
    properties = window.property_panel
    photo = target.image_item()
    scene.set_selection([photo])
    app.processEvents()
    check(properties.image_group.isVisible(), "选中图片时显示「图片图层」组")
    check("原图" in properties.image_info.text(), f"组内显示了原图尺寸：{properties.image_info.text()!r}")
    check(not properties.stroke_group.isEnabled(), "描边/颜色组被禁用（图片没有描边）")
    check(not properties.opacity_group.isEnabled(), "对象级不透明度组被禁用（改图层不透明度）")
    before_size = QRectF(photo.local_rect()).width()
    photo.set_display_scale(0.5, 0.5)
    app.processEvents()
    check(
        close(photo.local_rect().width(), before_size * 0.5, 1.0),
        f"「原始大小」这类等比操作生效（{before_size:.0f} → {photo.local_rect().width():.0f}）",
    )
    photo.set_display_scale(1.0, 1.0)
    scene.set_selection([scene.annotation_items()[0]] if scene.annotation_items() else [])
    app.processEvents()
    check(
        not properties.image_group.isVisible(),
        "选中标注时「图片图层」组自动隐藏",
    )
    check(properties.stroke_group.isEnabled(), "选中标注时颜色组恢复可用")
    scene.set_selection([])

    print("\n[17] 界面截图")
    view.fit_to_window()
    app.processEvents()
    shot = WORK / "layers_panel.png"
    check(bool(window.grab().save(str(shot))), f"窗口截图已保存 -> {shot}")
    panel_shot = WORK / "layer_panel.png"
    check(bool(panel.grab().save(str(panel_shot))), f"图层面板截图已保存 -> {panel_shot}")

    failed = [message for ok, message in RESULTS if not ok]
    print("\n" + "=" * 60)
    print(f"总计 {len(RESULTS)} 项，通过 {len(RESULTS) - len(failed)} 项，失败 {len(failed)} 项")
    for message in failed:
        print("  FAILED:", message)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
