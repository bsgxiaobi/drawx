"""标注对象工厂：类型字符串 <-> 类，工程文件与撤销栈都靠它重建对象。"""

from __future__ import annotations

from .base import AnnoItem
from .freehand import FreehandItem, HighlightItem
from .image_item import ImageItem
from .mosaic import BlurItem, MosaicItem
from .shapes import ArrowItem, EllipseItem, LineItem, RoundRectItem, ShapeItem
from .text import TextItem

ITEM_TYPES: dict[str, type] = {
    ShapeItem.TYPE: ShapeItem,
    EllipseItem.TYPE: EllipseItem,
    RoundRectItem.TYPE: RoundRectItem,
    LineItem.TYPE: LineItem,
    ArrowItem.TYPE: ArrowItem,
    FreehandItem.TYPE: FreehandItem,
    HighlightItem.TYPE: HighlightItem,
    TextItem.TYPE: TextItem,
    MosaicItem.TYPE: MosaicItem,
    BlurItem.TYPE: BlurItem,
    ImageItem.TYPE: ImageItem,
}

# 人类可读名称，用于菜单/状态栏
TYPE_LABELS = {
    ShapeItem.TYPE: "矩形",
    EllipseItem.TYPE: "椭圆",
    RoundRectItem.TYPE: "圆角矩形",
    LineItem.TYPE: "直线",
    ArrowItem.TYPE: "箭头",
    FreehandItem.TYPE: "画笔",
    HighlightItem.TYPE: "高亮",
    TextItem.TYPE: "文字",
    MosaicItem.TYPE: "马赛克",
    BlurItem.TYPE: "模糊",
    ImageItem.TYPE: "图片",
}


def create_item(data: dict, assets: dict | None = None) -> AnnoItem | None:
    """按字典重建对象；未知类型返回 None（保证旧版本文件可向前打开）。

    ``assets`` 是 ``资源 id -> QImage``；只有图片对象会用到，用来把内嵌的原始位图
    接回去（见 :meth:`ImageItem.apply_assets`）。
    """
    cls = ITEM_TYPES.get(str(data.get("type", "")))
    if cls is None:
        return None
    item = cls()
    item.apply_dict(data)
    item.apply_assets(assets)
    return item


def type_label(type_name: str) -> str:
    return TYPE_LABELS.get(type_name, type_name)
