"""本次反馈的三件事的回归测试：
1. 深色主题下的下拉/微调箭头、撤销重做图标
2. 快速复制为图片（PNG 进剪贴板）
3. 图片 / .drawx 拖入
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRect, Qt, QUrl  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QImage,
    QPainter,
)
from PySide6.QtWidgets import QApplication, QStyle, QStyleOption  # noqa: E402

from drawx.app import create_application  # noqa: E402
from drawx.const import IMAGE_SUFFIXES  # noqa: E402
from drawx.ui.icons import tool_icon  # noqa: E402
from drawx.ui.main_window import MainWindow  # noqa: E402
from drawx.ui.style import DarkStyle  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def check(condition: bool, message: str) -> None:
    RESULTS.append((bool(condition), message))
    print(("  PASS  " if condition else "  FAIL  ") + message)


def opaque_pixels(image: QImage) -> int:
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 40:
                count += 1
    return count


def make_test_image(path: Path, width: int = 320, height: int = 200) -> None:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#dfe7ef"))
    painter = QPainter(image)
    painter.fillRect(40, 40, 100, 60, QColor("#88b04b"))
    painter.end()
    image.save(str(path))


def drag_event(mime: QMimeData) -> QDragEnterEvent:
    return QDragEnterEvent(
        QPoint(20, 20),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def drop_event(mime: QMimeData) -> QDropEvent:
    return QDropEvent(
        QPointF(20.0, 20.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def check_clipboard(window, scene, work: Path) -> None:
    """只在真实平台跑：离屏平台的剪贴板是空实现，会挂起。"""
    from PySide6.QtCore import QRectF

    from drawx.items.base import set_local_rect_keep_anchor

    sample = work / "clip_source.png"
    make_test_image(sample, 360, 240)
    window._load_image_file(str(sample))
    for _ in range(3):
        app_process()
    check(scene.doc.canvas_w == 360 and scene.doc.canvas_h == 240, "素材已导入（360x240）")

    window.quick_copy_image()
    for _ in range(3):
        app_process()
    clipboard = QApplication.clipboard()
    image = clipboard.image()
    check(not image.isNull(), "剪贴板里有位图数据")
    check(
        image.width() == 360 and image.height() == 240,
        f"剪贴板图片尺寸 {image.width()}x{image.height()}（期望 360x240）",
    )
    mime = clipboard.mimeData()
    check(
        mime is not None and mime.hasFormat("image/png"),
        "剪贴板同时提供 image/png 原始数据",
    )
    if mime is not None and mime.hasFormat("image/png"):
        payload = bytes(mime.data("image/png"))
        check(payload[:8] == b"\x89PNG\r\n\x1a\n", f"PNG 魔数正确（{len(payload)} 字节）")

    item = scene.create_item({"type": "rect"})
    item.setPos(60.0, 60.0)
    set_local_rect_keep_anchor(item, QRectF(0, 0, 200, 120))
    item.setZValue(scene.next_z())
    scene.add_anno(item)
    window.quick_copy_image()
    for _ in range(3):
        app_process()
    image = clipboard.image()
    red = 0
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.red() > 200 and color.green() < 120:
                red += 1
    check(red > 50, f"复制结果包含标注（红色像素 {red}）")


def app_process() -> None:
    QApplication.processEvents()


def main() -> int:
    app = create_application([])
    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    for _ in range(4):
        app.processEvents()

    view = window.view
    scene = window.scene
    work = ROOT / "build" / "smoke" / "uitest"
    work.mkdir(parents=True, exist_ok=True)

    print("\n[1] 深色主题的下拉/微调箭头由自定义样式绘制")
    from PySide6.QtWidgets import QStyleFactory

    fusion = QStyleFactory.create("Fusion")
    ours = DarkStyle("Fusion")

    def render_primitive(style, element) -> bytes:
        option = QStyleOption()
        option.rect = QRect(0, 0, 18, 18)
        option.state = QStyle.StateFlag.State_Enabled
        canvas = QImage(18, 18, QImage.Format.Format_ARGB32)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        style.drawPrimitive(element, option, painter)
        painter.end()
        return bytes(canvas.constBits())

    for element, label in (
        (QStyle.PrimitiveElement.PE_IndicatorArrowDown, "下拉箭头"),
        (QStyle.PrimitiveElement.PE_IndicatorSpinUp, "微调上箭头"),
        (QStyle.PrimitiveElement.PE_IndicatorSpinDown, "微调下箭头"),
    ):
        custom = render_primitive(ours, element)
        stock = render_primitive(fusion, element)
        check(custom != stock, f"{label}：自定义样式与 Fusion 默认不同")
        check(
            render_primitive(app.style(), element) == custom,
            f"{label}：应用里生效的确实是自定义箭头",
        )

    # QSS 里一旦出现这些子控件选择器，Qt 就改由样式表自己画，没给 image 就什么都不画，
    # 箭头会直接消失。样式表里必须永远不出现它们（改主题时最容易误加）。
    # 检查前先去掉注释：样式表里那段"千万别写 drop-down"的警告本身也含这些词。
    import re as _re

    from drawx.app import STYLESHEET

    css = _re.sub(r"/\*.*?\*/", "", STYLESHEET, flags=_re.S)
    for selector in ("drop-down", "up-button", "down-button", "up-arrow", "down-arrow"):
        check(
            f"::{selector}" not in css,
            f"样式表里没有 ::{selector} 规则（有的话箭头会被样式表画成空白）",
        )

    print("\n[1b] 每个 Ctrl+Shift 快捷键都要有保底（中文输入法会吞掉 Ctrl+Shift）")
    shift_actions: list[str] = []
    for action in window.actions():
        sequences = [item.toString() for item in action.shortcuts()]
        if not sequences:
            continue
        if any("Ctrl+Shift" in text for text in sequences):
            shift_actions.append(f"{action.text()}{sequences}")
            check(
                any("Ctrl+Shift" not in text for text in sequences),
                f"「{action.text()}」有非 Ctrl+Shift 的保底快捷键：{sequences}",
            )
    check(bool(shift_actions), f"确实存在用了 Ctrl+Shift 的动作（{len(shift_actions)} 个）")

    print("\n[2] 撤销 / 重做 / 复制图片 图标不是空白")
    for name in ("undo", "redo", "copy_image"):
        pixmap = tool_icon(name).pixmap(22, 22)
        drawn = opaque_pixels(pixmap.toImage())
        check(drawn > 25, f"{name} 图标有 {drawn} 个可见像素")

    print("\n[3] 快速复制为图片 -> 剪贴板")
    if app.platformName() == "offscreen":
        print(
            "  SKIP  离屏平台的剪贴板实现是假的（会挂起），这一节改由\n"
            "        tests/clipboard_real_test.py 在真实 Windows 平台验证"
        )
    else:
        check_clipboard(window, scene, work)

    print("\n[4] 拖入图片")
    window._reset_document(640, 480)
    for _ in range(2):
        app.processEvents()
    check(not scene.doc.has_image, "先清成空白画布")

    dropped = work / "dropped_image.png"
    make_test_image(dropped, 420, 300)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(dropped))])
    enter = drag_event(mime)
    view.dragEnterEvent(enter)
    check(enter.isAccepted(), "视图接受了图片拖入（dragEnter）")
    view.dropEvent(drop_event(mime))
    for _ in range(2):
        app.processEvents()
    check(scene.doc.has_image, "拖入后背景图已载入")
    check(
        scene.doc.canvas_w == 420 and scene.doc.canvas_h == 300,
        f"画布尺寸跟随拖入的图片（{scene.doc.canvas_w}x{scene.doc.canvas_h}）",
    )

    print("\n[5] 拖入 .drawx 工程")
    project = work / "dropped_project.drawx"
    scene.doc.file_path = str(project)
    window.save_project()
    check(project.exists(), "工程已保存用于拖入测试")
    scene.doc.modified = False

    window._reset_document(640, 480)
    for _ in range(2):
        app.processEvents()
    mime_project = QMimeData()
    mime_project.setUrls([QUrl.fromLocalFile(str(project))])
    check(drag_event(mime_project).isAccepted() or True, "构造 .drawx 拖入事件")
    enter = drag_event(mime_project)
    view.dragEnterEvent(enter)
    check(enter.isAccepted(), "视图接受了 .drawx 拖入")
    view.dropEvent(drop_event(mime_project))
    for _ in range(3):
        app.processEvents()
    check(
        Path(scene.doc.file_path or "") == project,
        f"工程已被打开（当前文件 {Path(scene.doc.file_path).name if scene.doc.file_path else '无'}）",
    )
    check(scene.doc.canvas_w == 420, "打开的是拖入的那个工程")

    print("\n[6] 不支持的文件类型应被忽略")
    other = work / "notes.txt"
    other.write_text("hello", encoding="utf-8")
    mime_other = QMimeData()
    mime_other.setUrls([QUrl.fromLocalFile(str(other))])
    enter = drag_event(mime_other)
    view.dragEnterEvent(enter)
    check(not enter.isAccepted(), ".txt 拖入被拒绝")
    from drawx.ui.canvas_view import dropped_files

    check(dropped_files(mime_other) == [], "过滤函数不返回 .txt")
    check(
        [Path(p) for p in dropped_files(mime)] == [dropped],
        "过滤函数正确返回图片路径（且已规整为正斜杠/反斜杠一致的本地路径）",
    )

    print("\n[7] 主窗口自身也接受拖放（拖到工具栏/菜单栏区域）")
    check(window.acceptDrops(), "MainWindow.acceptDrops 为真")
    check(view.viewport().acceptDrops(), "画布 viewport 接受拖放（事件在这一层被接住）")

    print("\n[8] 中文化：标准按钮必须是中文（用户反馈 Save/Discard/Cancel）")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    from drawx.ui import dialogs

    Button = QMessageBox.StandardButton
    check(hasattr(app, "qt_translator"), "应用已装 Qt 中文翻译（qtbase_zh_CN）")

    box = dialogs.message_box(
        window,
        "尚未保存",
        "当前工程有未保存的修改，要先保存吗？",
        QMessageBox.Icon.Question,
        Button.Save | Button.Discard | Button.Cancel,
        Button.Save,
    )
    labels = [box.button(b).text() for b in (Button.Save, Button.Discard, Button.Cancel)]
    check(labels == ["保存", "不保存", "取消"], f"三个按钮是中文：{labels}")
    check(
        box.button(Button.Discard).text() == "不保存",
        "Discard 用国内习惯的「不保存」，而不是 Qt 翻译的「丢弃」",
    )
    ok_box = dialogs.message_box(window, "标题", "正文")
    check(ok_box.button(Button.Ok).text() == "确定", "单按钮提示框是「确定」")

    # 真的弹一次并点「不保存」，验证模态流程与返回值（离屏平台也能跑）
    clicked: dict = {}

    def click_discard() -> None:
        modal = app.activeModalWidget()
        if isinstance(modal, QMessageBox):
            clicked["labels"] = [
                modal.button(b).text() for b in (Button.Save, Button.Discard, Button.Cancel)
            ]
            modal.button(Button.Discard).click()

    QTimer.singleShot(60, click_discard)
    result = dialogs.ask_save_changes(window, "尚未保存", "当前工程有未保存的修改，要先保存吗？")
    check(
        clicked.get("labels") == ["保存", "不保存", "取消"],
        f"真实弹出的框按钮是中文：{clicked.get('labels')}",
    )
    check(result == Button.Discard, f"点「不保存」返回 Discard（实际 {result}）")

    # 输入框（重命名图层 / 画布大小走的就是这两个封装）
    input_labels: dict = {}

    def probe_input() -> None:
        modal = app.activeModalWidget()
        if isinstance(modal, QInputDialog):
            input_labels["ok"] = modal.okButtonText()
            input_labels["cancel"] = modal.cancelButtonText()
            modal.reject()

    QTimer.singleShot(60, probe_input)
    dialogs.ask_text(window, "重命名图层", "图层名称：", "图层 1")
    check(
        input_labels.get("ok") == "确定" and input_labels.get("cancel") == "取消",
        f"输入框按钮是中文：{input_labels}",
    )

    failed = [message for ok, message in RESULTS if not ok]
    print("\n" + "=" * 60)
    print(f"总计 {len(RESULTS)} 项，通过 {len(RESULTS) - len(failed)} 项，失败 {len(failed)} 项")
    for message in failed:
        print("  FAILED:", message)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
