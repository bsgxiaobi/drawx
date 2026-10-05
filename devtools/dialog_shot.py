"""把几个标准提示框渲染成图片，方便肉眼验收文案（真实平台，中文才准）。

为什么要单独截：提示框是**模态**的，脚本里没法用真实鼠标去点，但 `QWidget.grab()`
不需要人点也能把控件画出来，而且比抓屏干净（不会带上桌面上的其他窗口）。

用法：.venv\\Scripts\\python.exe devtools/dialog_shot.py
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.pop("QT_QPA_PLATFORM", None)  # 必须真实平台：离屏没有字体，中文会变方块

from PySide6.QtWidgets import QMessageBox  # noqa: E402

from drawx.app import create_application  # noqa: E402
from drawx.ui import dialogs  # noqa: E402
from drawx.ui.main_window import MainWindow  # noqa: E402

OUT = os.path.join(ROOT, "build", "gui")


def main() -> int:
    app = create_application([])
    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    for _ in range(4):
        app.processEvents()

    os.makedirs(OUT, exist_ok=True)
    shots = []

    # 1. 退出时的"要保存吗"——用户反馈的就是这一框
    save_box = dialogs.message_box(
        window,
        "尚未保存",
        "当前工程有未保存的修改，要先保存吗？",
        QMessageBox.Icon.Question,
        QMessageBox.StandardButton.Save
        | QMessageBox.StandardButton.Discard
        | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Save,
    )
    save_box.show()
    app.processEvents()
    path = os.path.join(OUT, "dialog_save_prompt.png")
    shots.append((path, save_box.grab()))
    save_box.close()

    # 2. 普通提示（只有一个"确定"）
    info_box = dialogs.message_box(window, "导出失败", "写入文件失败，请检查路径与权限。",
                                   QMessageBox.Icon.Critical)
    info_box.show()
    app.processEvents()
    path = os.path.join(OUT, "dialog_error.png")
    shots.append((path, info_box.grab()))
    info_box.close()

    # 3. 输入框（重命名图层走的就是它）
    from PySide6.QtWidgets import QInputDialog

    dialog = QInputDialog(window)
    dialog.setWindowTitle("重命名图层")
    dialog.setLabelText("图层名称：")
    dialog.setTextValue("现场照片 1")
    dialog.setOkButtonText("确定")
    dialog.setCancelButtonText("取消")
    dialog.show()
    app.processEvents()
    path = os.path.join(OUT, "dialog_rename.png")
    shots.append((path, dialog.grab()))
    dialog.close()

    # 4. 画布大小（一个框设宽高 + 比例预设），两种状态各截一张
    from drawx.ui.dialogs import CANVAS_RATIOS, CanvasSizeDialog

    ratios = dict(CANVAS_RATIOS)
    for label, name in (("16:9", "a"), ("自由", "b")):
        size_dialog = CanvasSizeDialog(
            window.scene.doc.canvas_w,
            window.scene.doc.canvas_h,
            window,
            content_rect=window.scene.itemsBoundingRect(),
        )
        if label != "自由":
            size_dialog.set_ratio(ratios[label])
        size_dialog.show()
        app.processEvents()
        path = os.path.join(OUT, f"dialog_canvas_size_{name}.png")
        shots.append((path, size_dialog.grab()))
        size_dialog.close()

    for path, pixmap in shots:
        ok = pixmap.save(path)
        print(f"{path}  {pixmap.width()}x{pixmap.height()}  {'ok' if ok else 'FAILED'}")

    window.scene.doc.modified = False
    window.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
