"""把图片图层合成成一张位图。

马赛克 / 模糊是"非破坏"的：它只在渲染时从**它下面的图层**重新采样，然后当场做像素化，
源位图一个字节都不改。v0.1 只能采样唯一的那张背景图；图层化之后要采样
"z 比它低的所有图片图层"，所以抽成这个独立函数。

采样粒度约定：**1 场景单位 = 1 像素**（与导出、与马赛克块大小一致）。
放大倍数很大的图片上做马赛克，边缘会略软 —— 这是刻意保留的取舍，
换来的是块大小在任何缩放下都有稳定语义。
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter


def sample_backdrop(scene, scene_rect: QRectF, z_limit: float) -> QImage:
    """把 ``z_limit`` 以下、与 ``scene_rect`` 相交的图片图层画成一张位图。"""
    area = QRectF(scene_rect).toAlignedRect()
    if area.width() < 1 or area.height() < 1:
        area = area.adjusted(0, 0, 1, 1)
    image = QImage(
        max(1, area.width()), max(1, area.height()), QImage.Format.Format_ARGB32_Premultiplied
    )
    doc = getattr(scene, "doc", None)
    image.fill(QColor(getattr(doc, "bg_color", "#FFFFFF")))

    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.translate(-float(area.x()), -float(area.y()))
        for layer in reversed(getattr(doc, "layers", [])):  # 底层先画
            if layer.opacity <= 0.0:
                continue
            for item in layer.items:
                if getattr(item, "TYPE", "") != "image":
                    continue
                if item.zValue() >= z_limit or not item.isVisible():
                    continue
                if not item.scene_rect().intersects(QRectF(area)):
                    continue
                painter.save()
                painter.setOpacity(float(item.opacity()))
                painter.setTransform(item.sceneTransform(), True)
                item.draw_image(painter)
                painter.restore()
    finally:
        painter.end()
    return image
