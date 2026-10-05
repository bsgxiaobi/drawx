"""拖放测试的"源窗口"：一个可以被拖出去的小窗口，用于真实 OLE 拖放测试。

用法：python devtools/drag_source.py <要拖的文件路径> [窗口X] [窗口Y]
启动后会把自己摆到指定屏幕位置，并把文件路径显示出来；用真实鼠标从它中间
按下拖到目标窗口，就会触发一次真正的 OLE 拖放。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QTimer, QUrl
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QApplication, QLabel

STYLE = """
QLabel { background: #1b3a63; color: #e8e8ee; border: 2px dashed #4d94ff;
         font-size: 13px; padding: 10px; }
"""


class DragSource(QLabel):
    def __init__(self, path: str) -> None:
        super().__init__(f"拖我 →\n\n{Path(path).name}\n\n(把鼠标放在这里按住，拖到 DrawX 窗口)")
        self.path = path
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(STYLE)
        self.setWindowTitle("DRAG_SOURCE")
        self.setFixedSize(360, 150)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(self.path)])
        drag = QDrag(self)
        drag.setMimeData(mime)
        print("DRAG_STARTED", flush=True)
        result = drag.exec(Qt.DropAction.CopyAction)
        print("DRAG_FINISHED", int(result), flush=True)


def main() -> int:
    path = sys.argv[1]
    x = int(sys.argv[2]) if len(sys.argv) > 2 else 1700
    y = int(sys.argv[3]) if len(sys.argv) > 3 else 260

    app = QApplication([])
    source = DragSource(path)
    source.move(x, y)
    source.show()
    print(f"SOURCE_READY {x} {y} {source.width()} {source.height()}", flush=True)
    QTimer.singleShot(30000, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
