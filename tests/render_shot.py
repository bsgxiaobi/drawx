"""真实平台渲染截图：验证系统字体（中文）与整体外观。

用默认的 windows 平台插件运行，会短暂弹出窗口。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QPointF, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402

from drawx.app import create_application  # noqa: E402
from drawx.ui.main_window import MainWindow  # noqa: E402

OUT = ROOT / "build" / "smoke"


def make_screenshot_like(width: int = 900, height: int = 560) -> QImage:
    """造一张"像是截图"的背景图，便于肉眼检查标注效果。"""
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    painter.fillRect(0, 0, width, 44, QColor("#2b579a"))
    painter.setPen(QColor("#ffffff"))
    font = painter.font()
    font.setPointSize(11)
    painter.setFont(font)
    painter.drawText(20, 29, "订单管理系统 —— 用户资料")

    font.setPointSize(10)
    painter.setFont(font)
    painter.setPen(QColor("#333333"))
    rows = [
        ("用户名", "zhangsan"),
        ("手机号", "13800138000"),
        ("身份证", "110101199003074512"),
        ("邮箱", "zhangsan@example.com"),
        ("收货地址", "北京市海淀区中关村大街 1 号"),
        ("支付方式", "招商银行 **** 8899"),
    ]
    y = 90
    for label, value in rows:
        painter.setPen(QColor("#888888"))
        painter.drawText(40, y, label)
        painter.setPen(QColor("#222222"))
        painter.drawText(150, y, value)
        y += 46

    painter.setPen(QColor("#d0d0d6"))
    painter.drawRect(36, 60, 828, 260)
    painter.end()
    return image


def build_demo(window: MainWindow) -> None:
    from drawx.items.base import set_local_rect_keep_anchor
    from drawx.items.freehand import FreehandItem
    from drawx.items.shapes import ArrowItem, EllipseItem, ShapeItem

    scene = window.scene
    window.add_image_layer(make_screenshot_like())
    doc = scene.doc

    def make(cls, x, y, w, h, style=None, **extra):
        item = cls(style)
        item.setZValue(scene.next_z())
        item.setPos(x, y)
        set_local_rect_keep_anchor(item, __import__("PySide6.QtCore", fromlist=["QRectF"]).QRectF(0, 0, w, h))
        for key, value in extra.items():
            setattr(item, key, value)
        scene.add_anno(item)
        return item

    # 手机号打码
    make(
        __import__("drawx.items.mosaic", fromlist=["MosaicItem"]).MosaicItem,
        140, 116, 190, 26,
        {"opacity": 1.0},
        block=8.0,
    )
    # 身份证模糊
    make(
        __import__("drawx.items.mosaic", fromlist=["BlurItem"]).BlurItem,
        140, 208, 210, 26,
        {"opacity": 1.0},
        block=7.0,
    )
    # 重点框选
    box = make(ShapeItem, 130, 100, 220, 52, {"stroke": "#ff3b30", "strokeWidth": 3, "strokeStyle": "dash", "fill": "#00000000"})
    # 圆角提示框
    from drawx.items.shapes import RoundRectItem

    make(RoundRectItem, 470, 350, 380, 120, {"stroke": "#2f7cf6", "strokeWidth": 3, "fill": "#2f7cf61f"})
    # 椭圆
    make(EllipseItem, 620, 150, 210, 120, {"stroke": "#af52de", "strokeWidth": 3, "fill": "#00000000"})
    # 箭头
    arrow = make(ArrowItem, 430, 120, 180, 90, {"stroke": "#ff9500", "strokeWidth": 5})
    arrow.p1 = QPointF(0, 0)
    arrow.p2 = QPointF(180, 90)
    arrow.head = "end"
    arrow.refresh_origin()
    # 文字
    from drawx.items.text import TextItem

    label = TextItem({"stroke": "#ff3b30", "fontSize": 18, "bold": True})
    label.setPlainText("这里是重点，注意核对")
    label.apply_text_style()
    label.setPos(470, 330)
    label.setZValue(scene.next_z())
    scene.add_anno(label)
    # 高亮
    from drawx.items.freehand import HighlightItem

    highlight = HighlightItem()
    highlight.set_scene_points([QPointF(146, 250), QPointF(230, 248), QPointF(320, 252)])
    highlight.setZValue(scene.next_z())
    scene.add_anno(highlight)
    # 手绘圈
    pen = FreehandItem({"stroke": "#34c759", "strokeWidth": 4})
    pen.set_scene_points(
        [
            QPointF(700, 300), QPointF(740, 270), QPointF(790, 288),
            QPointF(800, 330), QPointF(760, 356), QPointF(710, 344),
        ]
    )
    pen.setZValue(scene.next_z())
    scene.add_anno(pen)

    scene.set_selection([box])
    return doc


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = create_application([])
    window = MainWindow()
    window.resize(1280, 820)
    window.show()
    build_demo(window)
    window.view.zoom_reset()
    window.view.fit_to_window()

    def snapshot() -> None:
        app.processEvents()
        path = OUT / "real_platform.png"
        ok = window.grab().save(str(path))
        print("平台:", app.platformName())
        print("截图:", path, "ok" if ok else "FAILED")
        # Qt 6 的 app.quit() 会顺带关掉顶层窗口，于是触发"未保存"确认框；
        # 脚本里没人能点那个框，整个过程就会挂住。退出前先清掉脏标记。
        window.scene.doc.modified = False
        app.quit()

    QTimer.singleShot(700, snapshot)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
