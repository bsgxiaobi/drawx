"""真实 Windows 平台验证：快速复制为图片 → 读回剪贴板，并检查能否干净退出。

用法：
  python tests/clipboard_real_test.py copy   # 复制并退出（检查是否有崩溃）
  python tests/clipboard_real_test.py read   # 只读剪贴板里的图片尺寸
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.pop("QT_QPA_PLATFORM", None)  # 必须用真实平台

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from drawx.app import create_application  # noqa: E402
from drawx.ui.main_window import MainWindow  # noqa: E402


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "copy"
    app = create_application([])

    if action == "read":
        image = QApplication.clipboard().image()
        if image.isNull():
            print("CLIPBOARD_EMPTY")
        else:
            print(f"CLIPBOARD_IMAGE {image.width()} {image.height()}")
        return 0

    work = ROOT / "build" / "smoke" / "uitest"
    work.mkdir(parents=True, exist_ok=True)
    sample = work / "clip_real.png"
    source = QImage(360, 240, QImage.Format.Format_RGB32)
    source.fill(QColor("#dfe7ef"))
    source.save(str(sample))

    window = MainWindow()
    window.resize(1100, 760)
    window.show()
    for _ in range(4):
        app.processEvents()

    window._load_image_file(str(sample))
    for _ in range(3):
        app.processEvents()

    window.quick_copy_image()
    for _ in range(3):
        app.processEvents()

    print("COPIED", window.statusBar().currentMessage())

    # 再来一张图片图层：验证"快速复制"复制的是**拼合后的整幅画布**，
    # 而不是第一张图片（多图拼合是 v0.2 的主场景）。
    second = work / "clip_real_2.png"
    extra = QImage(200, 200, QImage.Format.Format_RGB32)
    extra.fill(QColor("#f6eef7"))
    extra.save(str(second))
    window._load_image_file(str(second))
    for _ in range(3):
        app.processEvents()
    window.quick_copy_image()
    for _ in range(3):
        app.processEvents()
    clipboard = QApplication.clipboard()
    composite = clipboard.image()
    print(
        "COPIED_COMPOSITE",
        f"{composite.width()}x{composite.height()}",
        "canvas",
        f"{window.scene.doc.canvas_w}x{window.scene.doc.canvas_h}",
        "layers",
        len(window.scene.doc.image_layers()),
    )

    # 复制之后再随便画一个对象、撤销一次，确认剪贴板操作不会破坏状态
    from drawx.items.base import set_local_rect_keep_anchor
    from PySide6.QtCore import QRectF

    item = window.scene.create_item({"type": "rect"})
    item.setPos(20.0, 20.0)
    set_local_rect_keep_anchor(item, QRectF(0, 0, 100, 60))
    item.setZValue(window.scene.next_z())
    window.scene.add_anno(item)
    window.view.commit_new_item(item)
    window.scene.undo_stack.undo()
    for _ in range(3):
        app.processEvents()
    print("STATE_OK objects=", len(window.scene.anno_items()))

    window.scene.doc.modified = False
    window.close()
    for _ in range(3):
        app.processEvents()
    print("CLOSED_CLEANLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
