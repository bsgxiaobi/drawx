"""生成 exe 用的 packaging/app.ico。

绘制的唯一来源是 drawx.ui.appicon，保证 **exe 文件图标 / 标题栏 / 任务栏**
三处完全一致（以前图标只有 exe 有，窗口里是空的）。
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from drawx.ui.appicon import ICON_SIZES, draw_app_icon  # noqa: E402


def main() -> int:
    app = QApplication([])  # noqa: F841
    from PIL import Image

    out_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, "app.ico")
    png_target = os.path.join(out_dir, "app.png")

    base: QImage = draw_app_icon(256)
    base.save(png_target, "PNG")

    converted = base.convertToFormat(QImage.Format.Format_RGBA8888)
    image = Image.frombytes("RGBA", (256, 256), bytes(converted.constBits()))
    sizes = [(size, size) for size in ICON_SIZES if size <= 256]
    image.save(target, format="ICO", sizes=sizes)

    print("图标已生成:", target, os.path.getsize(target), "bytes")
    print("包含尺寸:", sizes)
    print("预览图:", png_target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
