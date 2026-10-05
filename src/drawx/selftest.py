"""打包自检：验证 exe 在目标机器上能真正跑起来（Qt 插件、字体、写文件）。

用法：DrawX.exe --selftest 报告.json

打包成 --windowed 后没有控制台输出，所以结果写进 JSON 文件。
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path


def run(window, out_path: str) -> int:
    report: dict = {
        "ok": False,
        "app": "DrawX",
        "platform": "",
        "fonts": {},
        "steps": [],
        "errors": [],
    }

    def record(name: str, ok: bool, detail: object = "") -> None:
        report["steps"].append({"name": name, "ok": bool(ok), "detail": str(detail)[:400]})
        if not ok:
            report["errors"].append(f"{name}: {detail}")

    try:
        from PySide6.QtGui import QFont, QFontInfo, QFontDatabase, QImage, QPainter, QColor
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        report["platform"] = app.platformName() if app else "?"
        families = QFontDatabase.families()
        report["fonts"] = {
            "count": len(families),
            "microsoft_yahei": "Microsoft YaHei" in families,
            "exact_match": QFontInfo(QFont("Microsoft YaHei")).exactMatch(),
        }

        # 0. 界面中文化：打包时 qtbase_zh_CN.qm 有没有被带上（PyInstaller 的坑）
        from PySide6.QtWidgets import QInputDialog, QMessageBox

        from .ui import dialogs

        button_texts = [
            dialogs.message_box(
                window,
                "尚未保存",
                "当前工程有未保存的修改，要先保存吗？",
                QMessageBox.Icon.Question,
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            .button(name)
            .text()
            for name in (
                QMessageBox.StandardButton.Save,
                QMessageBox.StandardButton.Discard,
                QMessageBox.StandardButton.Cancel,
            )
        ]
        dialog = QInputDialog(window)
        record(
            "标准按钮中文化",
            button_texts == ["保存", "不保存", "取消"]
            and dialog.okButtonText() == "确定"
            and dialog.cancelButtonText() == "取消",
            f"提示框 {button_texts}　输入框 {dialog.okButtonText()}/"
            f"{dialog.cancelButtonText()}",
        )

        # Qt 自己造的字符串（文字编辑右键菜单的剪切/复制/粘贴等）靠 qtbase_zh_CN.qm，
        # 单文件 exe 里这份翻译有没有被解包出来，只有跑起来才知道。
        raw_box = QMessageBox(window)
        raw_box.setStandardButtons(
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
        )
        qt_texts = [
            raw_box.button(name).text()
            for name in (
                QMessageBox.StandardButton.Save,
                QMessageBox.StandardButton.Discard,
            )
        ]
        record(
            "Qt 内置翻译已加载",
            all(any("\u4e00" <= char <= "\u9fff" for char in text) for text in qt_texts),
            f"Qt 自绘按钮 {qt_texts}（中文即说明 qtbase_zh_CN.qm 生效）",
        )

        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        work = out.parent / "selftest_work"
        work.mkdir(parents=True, exist_ok=True)

        # 1. 造两张图片各成一个图片图层（验证多图 + 图层化）
        background = QImage(900, 600, QImage.Format.Format_RGB32)
        background.fill(QColor("#f4f6f9"))
        painter = QPainter(background)
        painter.setPen(QColor("#20304a"))
        painter.drawText(60, 100, "DrawX selftest 13800138000")
        painter.fillRect(500, 320, 220, 140, QColor("#88b04b"))
        painter.end()
        window.add_image_layer(background)
        record(
            "导入图片图层",
            window.scene.doc.canvas_w == 900 and window.scene.doc.has_image,
            f"{window.scene.doc.canvas_w}x{window.scene.doc.canvas_h} "
            f"图层={len(window.scene.doc.image_layers())}",
        )

        second = QImage(300, 400, QImage.Format.Format_RGB32)
        second.fill(QColor("#e8eef7"))
        window.add_image_items([("selftest-second.png", second)])
        layers = window.scene.doc.image_layers()
        record(
            "多图片图层并存",
            len(layers) == 2 and window.scene.doc.canvas_w > 900,
            f"图片图层 {len(layers)} 个，画布 {window.scene.doc.canvas_w}x"
            f"{window.scene.doc.canvas_h}",
        )
        first_image = next(
            (
                layer.image_item()
                for layer in layers
                if layer.image_item() is not None
                and layer.image_item().natural_size() == (900, 600)
            ),
            None,
        )
        window.scene.set_selection([first_image] if first_image is not None else [])
        cropped_ok = False
        if first_image is not None:
            before_crop = QRectF(first_image.src_rect)
            first_image.apply_src_rect(QRectF(50, 40, 400, 300))
            cropped_ok = (
                abs(first_image.src_rect.width() - 400.0) < 0.01
                and first_image.natural_size() == (900, 600)
            )
            first_image.reset_crop()
            cropped_ok = cropped_ok and first_image.src_rect == before_crop
        record(
            "图片非破坏裁剪可还原",
            cropped_ok,
            f"src={first_image.src_rect.width():.0f}x{first_image.src_rect.height():.0f}"
            if first_image is not None
            else "没找到 900x600 的图片图层",
        )
        # 图片可以移动 / 缩放
        scaled_ok = False
        if first_image is not None:
            first_image.moveBy(10.0, 12.0)
            first_image.set_display_scale(0.5, 0.5)
            scaled_ok = abs(first_image.local_rect().width() - 450.0) < 1.0
            first_image.set_display_scale(1.0, 1.0)
            first_image.moveBy(-10.0, -12.0)
        record(
            "图片可移动 / 缩放",
            scaled_ok,
            f"显示 {first_image.local_rect().width():.0f}x"
            f"{first_image.local_rect().height():.0f}"
            if first_image is not None
            else "-",
        )
        window.scene.set_selection([])

        # 2. 每种标注对象各来一个
        from drawx.items.base import set_local_rect_keep_anchor
        from drawx.items.factory import ITEM_TYPES

        samples = {
            "rect": (100, 120, 220, 130),
            "ellipse": (380, 120, 180, 130),
            "roundrect": (620, 120, 180, 130),
            "line": (100, 300, 200, 90),
            "arrow": (360, 300, 200, 90),
            "highlight": (100, 440, 240, 40),
            "mosaic": (40, 70, 300, 50),
            "blur": (520, 440, 200, 90),
        }
        created = 0
        for type_name, (x, y, w, h) in samples.items():
            item = window.scene.create_item({"type": type_name})
            item.setPos(x, y)
            set_local_rect_keep_anchor(item, QRectF(0, 0, w, h))
            window.scene.add_anno(item)
            created += 1

        text_item = window.scene.create_item({"type": "text"})
        text_item.setPlainText("中文自检：标注对象可再编辑")
        text_item.apply_text_style()
        text_item.setPos(120, 520)
        window.scene.add_anno(text_item)
        created += 1

        freehand = window.scene.create_item({"type": "freehand"})
        freehand.set_scene_points([QPointF(700, 460), QPointF(760, 430), QPointF(820, 470)])
        window.scene.add_anno(freehand)
        created += 1
        record("自由笔画点集", len(freehand.points) == 3, len(freehand.points))

        present = {item.TYPE for item in window.scene.anno_items()}
        missing = sorted(set(ITEM_TYPES) - present)
        record(
            "创建全部标注类型",
            not missing,
            f"{len(present)}/{len(ITEM_TYPES)} 缺: {missing}",
        )
        layout = window.layer_panel.tree.topLevelItemCount()
        record(
            "图层面板列出全部图层",
            layout == len(window.scene.layers()),
            f"面板 {layout} 行 / 文档 {len(window.scene.layers())} 个图层",
        )

        # 3. 渲染导出（1x / 2x）
        from drawx.render.exporter import render_document, save_image

        image_1x = render_document(window.scene.doc, window.scene, scale=1.0)
        expect_w = window.scene.doc.canvas_w
        record(
            "1x 渲染",
            image_1x.width() == expect_w,
            f"{image_1x.width()}x{image_1x.height()}（画布 {expect_w}）",
        )
        image_2x = render_document(window.scene.doc, window.scene, scale=2.0)
        record(
            "2x 渲染",
            image_2x.width() == expect_w * 2,
            f"{image_2x.width()}x{image_2x.height()}",
        )
        png = work / "selftest_export.png"
        record("导出 PNG", save_image(image_1x, str(png)), png)
        jpg = work / "selftest_export.jpg"
        record("导出 JPG", save_image(image_2x, str(jpg), quality=88), jpg)

        # 4. 保存 / 重新打开工程
        from drawx.model import serialize

        project = work / "selftest.drawx"
        serialize.save_project(
            str(project),
            window.scene.doc,
            window.scene.layers(),
            scene=window.scene,
        )
        size_kb = round(project.stat().st_size / 1024, 1)
        record("保存 .drawx 工程", project.exists(), f"{size_kb} KB")

        count_before = len(window.scene.annotation_items())
        doc, layers, _view = serialize.load_project(str(project))
        images_back = sum(
            1
            for layer in layers
            for item in layer.items
            if getattr(item, "TYPE", "") == "image" and item.has_source()
        )
        record(
            "读回 .drawx 工程",
            len(layers) == 3 and images_back == 2,
            f"{len(layers)} 个图层 / {images_back} 张原图 / "
            f"标注 {sum(len(l.items) for l in layers) - images_back}",
        )
        record(
            "图片随工程内嵌",
            doc.has_image and doc.canvas_w == window.scene.doc.canvas_w,
            f"{doc.canvas_w}x{doc.canvas_h} has_image={doc.has_image} "
            f"标注数={count_before}",
        )
        # 5. 撤销 / 重做
        window.scene.undo_stack.clear()
        item = window.scene.create_item({"type": "arrow"})
        window.scene.add_anno(item)
        window.view.commit_new_item(item)
        added = len(window.scene.annotation_items())
        window.scene.undo_stack.undo()
        undone = len(window.scene.annotation_items())
        window.scene.undo_stack.redo()
        redone = len(window.scene.annotation_items())
        record(
            "撤销 / 重做",
            added == undone + 1 and redone == added,
            f"{undone} -> {added} -> {redone}",
        )

        report["ok"] = not report["errors"]

    except Exception:  # noqa: BLE001
        report["errors"].append(traceback.format_exc())
        report["ok"] = False

    try:
        Path(out_path).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass

    try:
        window.scene.doc.modified = False
    except Exception:
        pass
    return 0 if report["ok"] else 1
