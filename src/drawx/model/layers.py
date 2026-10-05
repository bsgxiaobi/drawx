"""图层模型。

一份文档由若干图层组成，图层只有两种：

* ``image`` —— **图片图层**：恰好承载一个 :class:`~drawx.items.image_item.ImageItem`。
  它保存原始位图（``source``）与**非破坏**的保留区域（``src_rect``，源图像素坐标），
  于是"裁剪"随时可以改回来，缩放/旋转也不损失原始像素。
* ``annotation`` —— **标注图层**：承载任意多个矢量标注对象，用来把标注分组，
  也用来控制"标注在图片上面还是下面"。

顺序约定（整个项目只有这一份真相）：

* ``Document.layers`` **顶层在前**，和图层面板从上到下看到的顺序完全一致，
  所以面板行号 == 列表下标，不需要任何反序换算（这是最容易写错的地方）。
* 绘制顺序是它的**反序**（先画最后一个）。
* 每个对象的 ``zValue()`` 由 :meth:`CanvasScene.reflow_z` 按图层顺序统一分配，
  **不要手工设 z**；撤销/重做之后场景会自动重排一次，避免快照里的旧 z 把
  对象"搬到别的图层上面去"。
"""

from __future__ import annotations

from dataclasses import dataclass, field

KIND_IMAGE = "image"
KIND_ANNOTATION = "annotation"

#: 图层 id 前缀，纯粹为了日志/排查时好认
_PREFIX = {"image": "im", "annotation": "an"}


def new_layer_id(kind: str = KIND_ANNOTATION) -> str:
    from ..items.base import new_id

    return f"{_PREFIX.get(kind, 'ly')}-{new_id()}"


@dataclass
class Layer:
    """一个图层。``items`` 就是该图层承载的对象（图片图层恒为 1 个）。"""

    id: str
    name: str
    kind: str = KIND_ANNOTATION
    visible: bool = True
    locked: bool = False
    opacity: float = 1.0
    items: list = field(default_factory=list)
    #: 面板缩略图缓存（不参与序列化，源图变了要置 None）
    thumb: object = None
    #: 工程文件里出现的未知字段，保存时原样写回（版本兼容用）
    extra: dict = field(default_factory=dict)

    # ---------------------------------------------------------------- 便捷
    @property
    def is_image(self) -> bool:
        return self.kind == KIND_IMAGE

    def image_item(self):
        """图片图层里的那个图片对象；没有就返回 None。"""
        for item in self.items:
            if getattr(item, "TYPE", "") == "image":
                return item
        return None

    def source_name(self) -> str:
        """图片图层对应的源文件名（仅用于展示）。"""
        item = self.image_item()
        return str(getattr(item, "source_name", "") or "")

    def clamp_opacity(self) -> None:
        self.opacity = max(0.0, min(1.0, float(self.opacity)))

    def to_dict(self) -> dict:
        """图层的元信息（不含对象）。对象由 serialize 单独拼。"""
        data = {
            "id": self.id,
            "name": self.name,
            "type": self.kind,
            "visible": bool(self.visible),
            "locked": bool(self.locked),
            "opacity": round(float(self.opacity), 3),
        }
        for key, value in self.extra.items():
            data.setdefault(key, value)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Layer":
        known = {"id", "name", "type", "visible", "locked", "opacity", "objects"}
        return cls(
            id=str(data.get("id") or new_layer_id(str(data.get("type", "")) or KIND_ANNOTATION)),
            name=str(data.get("name") or "图层"),
            kind=str(data.get("type") or KIND_ANNOTATION),
            visible=bool(data.get("visible", True)),
            locked=bool(data.get("locked", False)),
            opacity=float(data.get("opacity", 1.0)),
            extra={k: v for k, v in data.items() if k not in known},
        )
