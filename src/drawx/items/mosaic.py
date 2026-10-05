"""马赛克 / 模糊区域对象（非破坏）。"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainterPath

from ..render import effects
from ..render.backdrop import sample_backdrop
from .base import AnnoItem


class PatchItem(AnnoItem):
    """遮盖类对象的共同实现：只存区域与参数，渲染时重新采样下面的图层。"""

    TYPE = "mosaic"
    LABEL = "马赛克"
    DEFAULT_BLOCK = 12.0
    CLOSED_SHAPE = True

    def __init__(self, style: dict | None = None) -> None:
        super().__init__(style)
        self.block = float(self.DEFAULT_BLOCK)
        self._rect = QRectF(0.0, 0.0, 160.0, 100.0)
        self._bd_key = None
        self._bd_image = None
        self.refresh_origin()

    # ---------------------------------------------------------- 几何
    def local_rect(self) -> QRectF:
        return QRectF(self._rect)

    def set_local_rect(self, rect: QRectF) -> None:
        self.prepareGeometryChange()
        self._rect = QRectF(rect)
        self.refresh_origin()

    def content_margin(self) -> float:
        return 1.0

    def boundingRect(self) -> QRectF:
        return self.local_rect().adjusted(-1.0, -1.0, 1.0, 1.0)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self.local_rect())
        return path

    # ---------------------------------------------------------- 特效
    def _apply_effect(self, image):
        return image

    # ---------------------------------------------------------- 采样缓存
    def _backdrop(self, scene, scene_rect: QRectF):
        """取本对象下方的合成位图。

        缓存键包含"下方图片图层的几何指纹"，所以拖动图片、改缩放、改顺序、
        改图层不透明度都会自动失效；不命中时重算一次，代价是几个位图缩放blit。
        """
        key = (
            round(scene_rect.x(), 1),
            round(scene_rect.y(), 1),
            round(scene_rect.width(), 1),
            round(scene_rect.height(), 1),
            round(float(self.zValue()), 3),
            float(self.block),
            scene.backdrop_signature(self.zValue()),
        )
        if key == self._bd_key and self._bd_image is not None:
            return self._bd_image
        image = sample_backdrop(scene, scene_rect, self.zValue())
        self._bd_key = key
        self._bd_image = image
        return image

    # ---------------------------------------------------------- 绘制
    def paint(self, painter, option, widget=None) -> None:
        local = self.local_rect()
        painter.save()
        painter.setClipRect(local)
        scene = self.scene()
        if scene is None:
            painter.restore()
            return
        scene_rect = self.scene_rect()
        if scene_rect.width() < 1.0 or scene_rect.height() < 1.0:
            painter.restore()
            return
        try:
            source = self._backdrop(scene, scene_rect)
            patch = self._apply_effect(source)
        except Exception:
            painter.fillRect(local, QColor(140, 140, 140, 110))
            painter.restore()
            return
        # paint() 的画笔已经处在"对象局部坐标"里，所以只要把采样区域映射回局部坐标即可。
        # （不要再 setTransform(sceneTransform())，那会把对象变换叠加两次。）
        target = self.mapFromScene(scene_rect).boundingRect()
        if self.TYPE == "blur":
            painter.setRenderHint(painter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(target, patch)
        painter.restore()

    # ---------------------------------------------------------- 序列化
    def geometry_dict(self) -> dict:
        return {"block": round(float(self.block), 3)}

    def apply_geometry(self, geometry: dict, data: dict) -> None:
        self.block = float(geometry.get("block", self.DEFAULT_BLOCK))
        w = max(1.0, float(data.get("w", 160.0)))
        h = max(1.0, float(data.get("h", 100.0)))
        self._rect = QRectF(0.0, 0.0, w, h)


class MosaicItem(PatchItem):
    TYPE = "mosaic"
    LABEL = "马赛克"
    DEFAULT_BLOCK = 12.0

    def _apply_effect(self, image):
        return effects.pixelate(image, self.block)


class BlurItem(PatchItem):
    TYPE = "blur"
    LABEL = "模糊"
    DEFAULT_BLOCK = 10.0

    def _apply_effect(self, image):
        return effects.blur(image, self.block)
