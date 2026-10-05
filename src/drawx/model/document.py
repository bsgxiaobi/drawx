"""文档模型：画布、图层、非破坏裁剪窗口。

设计约定（与 v0.1 相比有一处重要修正）：

* **背景不再是一张特殊位图，而是最底下的一个图片图层。** 当初把背景排除在图元之外，
  是为了让它不可能被误选中；但"把多张现场照片拼成一张完整的图"这个需求，
  恰恰要求每张照片都能被选中、移动、缩放、裁剪，所以背景位图这个概念被
  图片图层取代了。画布退化成一张可调尺寸的底色纸。
* **裁剪是非破坏的**，而且分成两层：``Document.crop`` 决定导出范围（画布裁剪），
  每个图片图层的 ``src_rect`` 决定自己保留源图的哪一块（图片裁剪）。
* 场景里只存放图层承载的对象；文档只存元信息 + 图层列表。
"""

from __future__ import annotations

from PySide6.QtCore import QRectF

from .layers import KIND_ANNOTATION, KIND_IMAGE, Layer, new_layer_id

DEFAULT_CANVAS = (1280, 800)


class Document:
    """一份工程的全部非标注状态。"""

    def __init__(self) -> None:
        self.canvas_w: int = DEFAULT_CANVAS[0]
        self.canvas_h: int = DEFAULT_CANVAS[1]
        self.bg_color: str = "#FFFFFF"
        self.crop: QRectF = QRectF(0.0, 0.0, float(self.canvas_w), float(self.canvas_h))
        #: 图层，**顶层在前**（与图层面板显示顺序一致）
        self.layers: list[Layer] = []
        #: 当前活动图层 id：新标注进这个图层
        self.active_layer_id: str | None = None
        self.file_path: str | None = None
        #: 最近一次导入的图片来源（仅用于标题与默认文件名，不参与工程序列化）
        self.source_path: str | None = None
        self.modified: bool = False
        #: 工程文件里出现的未知顶层字段，保存时原样写回
        self.extra: dict = {}
        #: 打开工程时统计到的"位图缺失"的图片图层数（只在读取时设置）
        self.missing_assets: int = 0

    @property
    def display_name(self) -> str:
        """标题栏与默认文件名用的名字。"""
        from pathlib import Path

        if self.file_path:
            return Path(self.file_path).stem
        if self.source_path:
            return Path(self.source_path).stem
        return "无标题"

    # ------------------------------------------------------------ 画布
    @property
    def has_image(self) -> bool:
        """是否至少有一个装好位图的图片图层。"""
        return any(layer.image_item() is not None for layer in self.layers)

    def canvas_rect(self) -> QRectF:
        return QRectF(0.0, 0.0, float(self.canvas_w), float(self.canvas_h))

    def set_canvas(self, w: int, h: int) -> None:
        self.canvas_w = max(1, int(w))
        self.canvas_h = max(1, int(h))
        self.crop = self.canvas_rect()

    # ------------------------------------------------------------ 图层
    def layer_by_id(self, layer_id: str | None) -> Layer | None:
        if not layer_id:
            return None
        for layer in self.layers:
            if layer.id == layer_id:
                return layer
        return None

    def image_layers(self) -> list[Layer]:
        return [layer for layer in self.layers if layer.kind == KIND_IMAGE]

    def annotation_layers(self) -> list[Layer]:
        return [layer for layer in self.layers if layer.kind != KIND_IMAGE]

    def default_annotation_layer(self) -> Layer:
        """新建标注默认进哪个图层：优先活动图层，否则最上面的标注图层。

        **图片图层永远不是候选**：照片和标注混进同一个图层后，一隐藏照片标注就跟着
        消失、一调顺序标注就跑到照片后面去了，这种"看不见的连带"很难排查。
        """
        active = self.layer_by_id(self.active_layer_id)
        if active is not None and active.kind != KIND_IMAGE and not active.locked:
            return active
        for layer in self.layers:  # 顶层在前，第一个非锁定标注层就是最上面的
            if layer.kind != KIND_IMAGE and not layer.locked:
                return layer
        layer = Layer(id=new_layer_id(KIND_ANNOTATION), name="标注", kind=KIND_ANNOTATION)
        self.layers.insert(0, layer)
        self.active_layer_id = layer.id
        return layer

    def top_annotation_layer(self) -> Layer | None:
        for layer in self.layers:
            if layer.kind != KIND_IMAGE:
                return layer
        return None

    # ------------------------------------------------------------ 裁剪
    def reset_crop(self) -> None:
        self.crop = self.canvas_rect()

    def clamp_crop(self) -> None:
        """把裁剪框限制在画布内且不小于 8x8。"""
        c = self.crop.intersected(self.canvas_rect())
        if c.width() < 8 or c.height() < 8:
            c = self.canvas_rect()
        self.crop = c

    @property
    def is_cropped(self) -> bool:
        c = self.crop
        return (
            abs(c.x()) > 0.01
            or abs(c.y()) > 0.01
            or abs(c.width() - self.canvas_w) > 0.01
            or abs(c.height() - self.canvas_h) > 0.01
        )
