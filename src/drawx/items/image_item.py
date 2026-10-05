"""图片对象：一个图片图层的内容。

它和别的标注对象最大的不同有两点：

1. **原始位图永不改动**。绘制时是 ``painter.drawImage(局部矩形, 源图, src_rect)``，
   所以「裁剪」只是换一个 ``src_rect``，改回来就能恢复全部像素 —— 这是相比
   Photoshop 破坏性裁剪的优势，也让工程文件永远只内嵌一份原图。
2. **显示尺度与源像素解耦**。``局部矩形 / src_rect`` 就是每个源像素占多少画布单位，
   于是放大缩小（缩放控制点）和非破坏裁剪可以各自独立进行，互不干扰。

裁剪编辑期的"全图模式"：``begin_crop()`` 临时把 ``src_rect`` 换成整幅源图，
并把局部矩形一起按同一比例放大，再用锚点补偿让画面**看起来完全没动**。
这样用户能看见已经被裁掉的部分并重新框选（否则非破坏裁剪根本没法"改回来"）。
:meth:`apply_src_rect` 是这两件事的公共实现。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from .base import AnnoItem, new_id


class ImageItem(AnnoItem):
    TYPE = "image"
    LABEL = "图片"
    CLOSED_SHAPE = True

    def __init__(self, style: dict | None = None) -> None:
        super().__init__(style)
        #: 资源 id（工程文件里 assets 的键），新图片自动生成
        self.asset_id: str = f"img-{new_id()}"
        #: 原始位图（内存里始终保留未经裁剪的原图）
        self.source: QImage | None = None
        #: 源文件名，仅用于标题/面板展示
        self.source_name: str = ""
        #: 非破坏保留区域，源图像素坐标
        self.src_rect: QRectF = QRectF(0.0, 0.0, 1.0, 1.0)
        self._rect: QRectF = QRectF(0.0, 0.0, 1.0, 1.0)
        #: 裁剪编辑期间的原始状态 (pos, 局部矩形, src_rect)
        self._crop_backup: tuple | None = None

    # ---------------------------------------------------------------- 几何
    def local_rect(self) -> QRectF:
        return QRectF(self._rect)

    def set_local_rect(self, rect: QRectF) -> None:
        self.prepareGeometryChange()
        self._rect = QRectF(0.0, 0.0, max(1.0, rect.width()), max(1.0, rect.height()))
        self.refresh_origin()

    def content_margin(self) -> float:
        # 图片没有描边，包围盒就是内容本身
        return 0.0

    def boundingRect(self) -> QRectF:
        return self.local_rect()

    def natural_size(self) -> tuple[int, int]:
        if self.source is None or self.source.isNull():
            return (int(self.src_rect.width()), int(self.src_rect.height()))
        return (self.source.width(), self.source.height())

    def pixel_scale(self) -> tuple[float, float]:
        """一个源像素在画布上占多少单位（x/y 分开，允许非等比拉伸）。"""
        width = max(0.001, self.src_rect.width())
        height = max(0.001, self.src_rect.height())
        return (self._rect.width() / width, self._rect.height() / height)

    def has_source(self) -> bool:
        return self.source is not None and not self.source.isNull()

    # ---------------------------------------------------------------- 位图
    def set_source(self, image: QImage, source_name: str = "") -> None:
        """换掉原始位图：保留区域归零，显示尺寸 = 源图原始像素（1:1）。"""
        self.prepareGeometryChange()
        self.source = QImage(image) if image is not None else None
        self.source_name = source_name
        self.src_rect = QRectF(0.0, 0.0, float(image.width()), float(image.height()))
        self._rect = QRectF(0.0, 0.0, float(image.width()), float(image.height()))
        self.refresh_origin()

    def reset_crop(self) -> None:
        """恢复完整源图（显示尺度保持不变）。"""
        if not self.has_source():
            return
        self.apply_src_rect(
            QRectF(0.0, 0.0, float(self.source.width()), float(self.source.height()))
        )

    def apply_src_rect(self, new_src: QRectF) -> None:
        """把保留区域换成 ``new_src``（源图像素坐标）。

        两个不变量：
        * **显示尺度不变**（``局部矩形 / src_rect`` 前后一致），用户看到的是"裁掉多余的"，
          而不是整个图片被拉伸。
        * **``new_src`` 左上角当前的场景位置保持不动**，所以裁剪框之外的内容消失时，
          画面不会整体跳动。旋转状态下这一点靠 ``mapToScene`` 自动成立。
        """
        if not self.has_source():
            return
        full = QRectF(0.0, 0.0, float(self.source.width()), float(self.source.height()))
        new_src = QRectF(new_src).intersected(full)
        if new_src.width() < 1.0 or new_src.height() < 1.0:
            return
        kx, ky = self.pixel_scale()
        anchor = self.mapToScene(QPointF(new_src.x() * kx, new_src.y() * ky))

        self.prepareGeometryChange()
        self.src_rect = new_src
        self._rect = QRectF(
            0.0, 0.0, new_src.width() * kx, new_src.height() * ky
        )
        self.refresh_origin()
        current = self.mapToScene(QPointF(0.0, 0.0))
        self.moveBy(anchor.x() - current.x(), anchor.y() - current.y())
        self.update()

    # ---------------------------------------------------------------- 缩放
    def set_display_scale(self, kx: float, ky: float) -> None:
        """按指定尺度显示（1 个源像素占 kx/ky 个画布单位），左上角保持不动。

        "原始大小"就是 ``set_display_scale(1, 1)``；因为源图始终是原图，
        这个缩放是矢量式的（随时可以再放大回去，不会掉像素）。
        """
        if not self.has_source():
            return
        kx = max(0.01, float(kx))
        ky = max(0.01, float(ky))
        anchor = self.mapToScene(QPointF(0.0, 0.0))
        self.prepareGeometryChange()
        self._rect = QRectF(
            0.0, 0.0, self.src_rect.width() * kx, self.src_rect.height() * ky
        )
        self.refresh_origin()
        current = self.mapToScene(QPointF(0.0, 0.0))
        self.moveBy(anchor.x() - current.x(), anchor.y() - current.y())
        self.update()

    # ---------------------------------------------------------------- 裁剪编辑
    @property
    def cropping(self) -> bool:
        return self._crop_backup is not None
    def begin_crop(self) -> bool:
        """进入"显示整幅源图"的裁剪编辑状态。"""
        if not self.has_source() or self.cropping:
            return False
        self._crop_backup = (
            QPointF(self.pos()),
            QRectF(self._rect),
            QRectF(self.src_rect),
        )
        self.apply_src_rect(
            QRectF(0.0, 0.0, float(self.source.width()), float(self.source.height()))
        )
        return True

    def end_crop(self, new_src: QRectF | None = None) -> None:
        """结束裁剪编辑。``new_src`` 为空表示放弃（回到进入前的状态）。"""
        backup = self._crop_backup
        if backup is None:
            return
        self._crop_backup = None
        if new_src is None:
            pos, rect, src = backup
            self.prepareGeometryChange()
            self._rect = QRectF(rect)
            self.src_rect = QRectF(src)
            self.refresh_origin()
            self.setPos(pos)
            self.update()
            return
        self.apply_src_rect(new_src)

    # ---------------------------------------------------------------- 绘制
    def draw_image(self, painter: QPainter) -> None:
        """在**本对象局部坐标系**里画出当前保留区域。"""
        if not self.has_source():
            self._paint_missing(painter)
            return
        painter.drawImage(self.local_rect(), self.source, self.src_rect)

    def _paint_missing(self, painter: QPainter) -> None:
        rect = self.local_rect()
        painter.fillRect(rect, QColor(90, 90, 100, 120))
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(200, 200, 210, 160), 0, Qt.PenStyle.DashLine))
        painter.drawRect(rect)
        painter.drawLine(rect.topLeft(), rect.bottomRight())
        painter.drawLine(rect.topRight(), rect.bottomLeft())
        painter.restore()

    def paint(self, painter, option, widget=None) -> None:
        self.draw_image(painter)

    # ---------------------------------------------------------------- 序列化
    def geometry_dict(self) -> dict:
        return {
            "assetId": self.asset_id,
            "sourceName": self.source_name,
            "naturalW": self.natural_size()[0],
            "naturalH": self.natural_size()[1],
            "srcX": round(self.src_rect.x(), 3),
            "srcY": round(self.src_rect.y(), 3),
            "srcW": round(self.src_rect.width(), 3),
            "srcH": round(self.src_rect.height(), 3),
        }

    def apply_geometry(self, geometry: dict, data: dict) -> None:
        self.asset_id = str(geometry.get("assetId") or self.asset_id)
        self.source_name = str(geometry.get("sourceName") or "")
        natural_w = max(1.0, float(geometry.get("naturalW", data.get("w", 1.0))))
        natural_h = max(1.0, float(geometry.get("naturalH", data.get("h", 1.0))))
        self.src_rect = QRectF(
            float(geometry.get("srcX", 0.0)),
            float(geometry.get("srcY", 0.0)),
            max(1.0, float(geometry.get("srcW", natural_w))),
            max(1.0, float(geometry.get("srcH", natural_h))),
        )
        self._rect = QRectF(
            0.0,
            0.0,
            max(1.0, float(data.get("w", self.src_rect.width()))),
            max(1.0, float(data.get("h", self.src_rect.height()))),
        )

    def apply_assets(self, assets: dict | None) -> None:
        """按 ``asset_id`` 取回原始位图（工程文件读取路径）。"""
        if self.has_source() or not assets:
            return
        image = assets.get(self.asset_id)
        if image is not None and not image.isNull():
            self.source = image
