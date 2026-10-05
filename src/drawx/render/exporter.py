"""导出：把文档重新矢量渲染成位图。

三个关键点：

1. **导出与屏幕缩放完全解耦**。导出走独立的离屏渲染，按 ``crop`` 区域 × 倍率
   生成 QImage，所以 2x/4x 导出时文字与线条是矢量重绘，依然锐利（不是插值放大）。
2. **编辑态装饰不会混进导出图**。选中框、控制点、参考线一律画在
   ``QGraphicsView.drawForeground()`` 里，而这里是直接渲染 QGraphicsScene，
   天然拿不到那些装饰，不需要"取消选中 → 渲染 → 恢复选中"这种脆弱做法。
3. **图层天然包含在内**：图片图层是场景图元，``scene.render`` 会把它们按 z 顺序
   画进来，所以多图拼合后的导出就是所见即所得。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from ..model.document import Document

FORMAT_BY_SUFFIX = {
    ".png": "PNG",
    ".jpg": "JPG",
    ".jpeg": "JPG",
    ".webp": "WEBP",
    ".bmp": "BMP",
}


def render_document(
    doc: Document,
    scene,
    scale: float = 1.0,
    area: QRectF | None = None,
    opaque_background: bool = False,
) -> QImage:
    """把文档渲染成 QImage。``area`` 默认取非破坏裁剪框。"""
    region = QRectF(area) if area is not None else QRectF(doc.crop)
    if region.width() < 1.0 or region.height() < 1.0:
        region = doc.canvas_rect()

    scale = max(0.01, float(scale))
    width = max(1, int(round(region.width() * scale)))
    height = max(1, int(round(region.height() * scale)))

    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent if not opaque_background else Qt.GlobalColor.white)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    try:
        painter.save()
        painter.scale(scale, scale)
        painter.translate(-region.x(), -region.y())

        canvas = doc.canvas_rect()
        # 画布底色。图片图层不是背景位图，而是场景里的图元，由下面的 scene.render
        # 一并画出来 —— 所以导出器不需要知道有几个图片图层。
        color = QColor(doc.bg_color)
        if color.alpha() > 0:
            painter.fillRect(canvas, color)

        if scene is not None:
            # source == target（painter 已经带了缩放），保证矢量清晰
            scene.render(
                painter,
                region,
                region,
                Qt.AspectRatioMode.IgnoreAspectRatio,
            )
        painter.restore()
    finally:
        painter.end()
    return image


def save_image(image: QImage, path: str, quality: int = 92) -> bool:
    suffix = Path(path).suffix.lower()
    fmt = FORMAT_BY_SUFFIX.get(suffix, "PNG")
    target = QImage(image)
    if fmt in ("JPG", "BMP"):
        flat = QImage(target.size(), QImage.Format.Format_RGB32)
        flat.fill(Qt.GlobalColor.white)
        painter = QPainter(flat)
        painter.drawImage(0, 0, target)
        painter.end()
        target = flat
    if fmt == "PNG":
        return bool(target.save(path, "PNG"))
    if fmt == "BMP":
        return bool(target.save(path, "BMP"))
    return bool(target.save(path, fmt, int(quality)))


def export_document(
    doc: Document,
    scene,
    path: str,
    scale: float = 1.0,
    quality: int = 92,
    area: QRectF | None = None,
) -> bool:
    image = render_document(doc, scene, scale=scale, area=area)
    return save_image(image, path, quality=quality)
