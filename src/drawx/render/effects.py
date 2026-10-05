"""图像特效：马赛克（像素化）与模糊。

关键设计：这两种效果都是**非破坏**的 —— 对象只记录"区域 + 参数"，
每次渲染时从背景位图重新采样，所以区域随时能移动、缩放、调强度、删除。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

try:  # Pillow 只用于更高质量的高斯模糊与 EXIF 处理，缺了也能跑
    from PIL import Image, ImageFilter

    _HAS_PIL = True
except Exception:  # pragma: no cover
    _HAS_PIL = False


def pixelate(image: QImage, block: float) -> QImage:
    """把图像按 block 像素一块地降采样再放大，得到马赛克效果。"""
    if image.isNull():
        return image
    size = max(2.0, float(block))
    w = max(1, int(round(image.width() / size)))
    h = max(1, int(round(image.height() / size)))
    small = image.scaled(
        w,
        h,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
    return small.scaled(
        image.width(),
        image.height(),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )


def _qimage_to_pil(image: QImage) -> "Image.Image":
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = converted.width(), converted.height()
    buffer = converted.constBits()
    return Image.frombytes("RGBA", (width, height), bytes(buffer))


def _pil_to_qimage(image: "Image.Image") -> QImage:
    data = image.tobytes("raw", "RGBA")
    qimage = QImage(data, image.width, image.height, QImage.Format.Format_RGBA8888)
    # QImage 不持有 Python bytes 的所有权，必须深拷贝
    return qimage.copy()


def blur(image: QImage, radius: float) -> QImage:
    """高斯模糊；没有 Pillow 时退化为"平滑降采样再放大"。"""
    if image.isNull():
        return image
    r = max(0.5, float(radius))
    if _HAS_PIL:
        try:
            pil = _qimage_to_pil(image)
            out = pil.filter(ImageFilter.GaussianBlur(radius=r))
            return _pil_to_qimage(out)
        except Exception:
            pass
    factor = max(2.0, r * 2.0)
    w = max(1, int(round(image.width() / factor)))
    h = max(1, int(round(image.height() / factor)))
    small = image.scaled(
        w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    return small.scaled(
        image.width(),
        image.height(),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def read_image_with_orientation(path: str) -> QImage:
    """按 EXIF 方向读取图片（手机拍的照片需要）。"""
    from PySide6.QtGui import QImageReader

    reader = QImageReader(path)
    reader.setAutoTransform(True)
    image = reader.read()
    if not image.isNull():
        return image

    if _HAS_PIL:
        from PIL import ImageOps

        with Image.open(path) as pil:
            pil = ImageOps.exif_transpose(pil)
            pil = pil.convert("RGBA")
            return _pil_to_qimage(pil)
    from PySide6.QtGui import QImage as _QImage

    return _QImage(path)
