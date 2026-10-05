"""``.drawx`` 工程文件读写。

容器就是一个 zip：

    photo.drawx
    ├── project.json            文档模型（UTF-8，缩进 2 空格，便于人工排查）
    ├── assets/<assetId>.png    各图片图层的**原始**位图（无损内嵌，挪机器不丢）
    └── thumbnail.png           缩略图（最近文件列表用）

v2 与 v1 的区别：背景位图不再是一个特殊字段，而是最底下的一个**图片图层**，
所以资源变成"每个图片图层一份"，路径也从固定的 ``assets/background.png``
改成 ``assets/<assetId>.png``。v1 文件打开时由 :func:`_migrate_1_to_2` 自动升级。

兼容策略：版本号 + 迁移链；读取时**保留未知字段**（顶层与图层级都保留），保存时写回，
这样高版本新增的字段不会被低版本静默丢弃。对象级未知字段暂不保留（见项目状态文档）。
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QImage

from ..const import APP_NAME, APP_VERSION, FORMAT_NAME, FORMAT_VERSION
from ..items.base import DEFAULT_STYLE, new_id
from ..model.document import Document
from ..model.layers import KIND_ANNOTATION, KIND_IMAGE, Layer, new_layer_id

PROJECT_JSON = "project.json"
THUMB_NAME = "thumbnail.png"

_TOP_LEVEL_KEYS = {
    "format",
    "version",
    "app",
    "canvas",
    "crop",
    "background",
    "assets",
    "layers",
    "objects",
    "view",
}


# ------------------------------------------------------------------ 位图工具
def image_to_png_bytes(image: QImage) -> bytes:
    buffer = QByteArray()
    device = QBuffer(buffer)
    device.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(device, "PNG")
    device.close()
    return bytes(buffer)


def image_from_bytes(data: bytes) -> QImage:
    image = QImage()
    image.loadFromData(data)
    return image


def asset_path(asset_id: str) -> str:
    return f"assets/{asset_id}.png"


def render_thumbnail(doc: Document, scene, max_size: int = 256) -> QImage | None:
    """生成缩略图；渲染失败不影响保存。"""
    try:
        from ..render.exporter import render_document
    except Exception:
        return None
    try:
        image = render_document(doc, scene, scale=1.0)
        if image.isNull():
            return None
        return image.scaled(
            max_size,
            max_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    except Exception:
        return None


# ------------------------------------------------------------------ 写
def build_project_dict(doc: Document, layers: list, view_state: dict | None = None) -> dict:
    """把文档 + 图层 + 对象拼成 project.json 的字典。

    ``layers`` **顶层在前**（与图层面板一致），资源表按图片图层逐个登记。
    """
    assets: dict = {}
    layer_entries: list[dict] = []
    for layer in layers:
        entry = layer.to_dict()
        objects: list[dict] = []
        for item in layer.items:
            data = item.to_dict()
            source = getattr(item, "source", None)
            if source is not None and not source.isNull():
                asset_id = str(getattr(item, "asset_id", "") or f"img-{item.id}")
                item.asset_id = asset_id
                assets[asset_id] = {
                    "path": asset_path(asset_id),
                    "mime": "image/png",
                    "width": source.width(),
                    "height": source.height(),
                }
                data.setdefault("geometry", {})["assetId"] = asset_id
            objects.append(data)
        entry["objects"] = objects
        layer_entries.append(entry)

    payload = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "app": {"name": APP_NAME, "version": APP_VERSION},
        "canvas": {
            "width": doc.canvas_w,
            "height": doc.canvas_h,
            "background": doc.bg_color,
        },
        "crop": {
            "x": round(doc.crop.x(), 3),
            "y": round(doc.crop.y(), 3),
            "w": round(doc.crop.width(), 3),
            "h": round(doc.crop.height(), 3),
        },
        # 兼容字段：v1 的读取器只看 background.assetId；v2 把它当成普通图片图层
        "background": {"color": doc.bg_color, "assetId": None},
        "assets": assets,
        "layers": layer_entries,
        "view": view_state or {"zoom": 1.0, "panX": 0.0, "panY": 0.0},
    }
    for key, value in (doc.extra or {}).items():
        payload.setdefault(key, value)
    return payload


def save_project(
    path: str,
    doc: Document,
    layers: list,
    view_state: dict | None = None,
    scene=None,
) -> None:
    """原子写入工程文件：先写 .tmp 再替换，避免中途失败毁掉原文件。

    ``scene`` 可选；给了就顺带写一张缩略图（最近文件列表用）。
    """
    data = build_project_dict(doc, layers, view_state)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    target = Path(path)
    tmp = target.with_suffix(target.suffix + ".tmp")

    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PROJECT_JSON, text.encode("utf-8"))
        for layer in layers:
            for item in layer.items:
                source = getattr(item, "source", None)
                if source is None or source.isNull():
                    continue
                asset_id = str(getattr(item, "asset_id", "") or f"img-{item.id}")
                archive.writestr(asset_path(asset_id), image_to_png_bytes(source))
        if scene is not None:
            thumb = render_thumbnail(doc, scene)
            if thumb is not None and not thumb.isNull():
                archive.writestr(THUMB_NAME, image_to_png_bytes(thumb))
    tmp.replace(target)


# ------------------------------------------------------------------ 迁移
def _image_object(asset_id: str, natural_w: int, natural_h: int, w: float, h: float) -> dict:
    return {
        "id": new_id(),
        "type": "image",
        "x": 0.0,
        "y": 0.0,
        "w": float(w),
        "h": float(h),
        "rotation": 0.0,
        "z": 1.0,
        "visible": True,
        "style": dict(DEFAULT_STYLE),
        "geometry": {
            "assetId": asset_id,
            "sourceName": "",
            "naturalW": int(natural_w),
            "naturalH": int(natural_h),
            "srcX": 0.0,
            "srcY": 0.0,
            "srcW": float(natural_w),
            "srcH": float(natural_h),
        },
    }


def _migrate_1_to_2(data: dict) -> dict:
    """v1 → v2：把"背景位图"升级成最底下的图片图层。"""
    canvas = data.get("canvas", {}) if isinstance(data.get("canvas"), dict) else {}
    canvas_w = int(canvas.get("width", 1) or 1)
    canvas_h = int(canvas.get("height", 1) or 1)
    background = data.get("background", {}) if isinstance(data.get("background"), dict) else {}
    assets = data.get("assets", {}) if isinstance(data.get("assets"), dict) else {}
    asset_id = background.get("assetId")

    layers: list[dict] = []
    if asset_id and asset_id in assets:
        info = assets.get(asset_id) or {}
        natural_w = int(info.get("width", canvas_w) or canvas_w)
        natural_h = int(info.get("height", canvas_h) or canvas_h)
        # v1 是"把位图拉伸到整幅画布"，迁移时保持同样的视觉结果
        layers.append(
            {
                "id": new_layer_id(KIND_IMAGE),
                "name": "背景",
                "type": KIND_IMAGE,
                "visible": True,
                "locked": False,
                "opacity": 1.0,
                "objects": [_image_object(asset_id, natural_w, natural_h, canvas_w, canvas_h)],
            }
        )

    old_layers = data.get("layers")
    if isinstance(old_layers, list) and old_layers:
        for layer in old_layers:
            if not isinstance(layer, dict):
                continue
            if layer.get("type") == "background" or layer.get("assetId"):
                continue
            fixed = dict(layer)
            fixed.setdefault("type", KIND_ANNOTATION)
            fixed.setdefault("name", "标注")
            fixed["objects"] = [
                obj for obj in (fixed.get("objects") or []) if isinstance(obj, dict)
            ]
            layers.append(fixed)
    else:
        objects = [o for o in (data.get("objects") or []) if isinstance(o, dict)]
        layers.append(
            {
                "id": new_layer_id(KIND_ANNOTATION),
                "name": "标注",
                "type": KIND_ANNOTATION,
                "visible": True,
                "locked": False,
                "opacity": 1.0,
                "objects": objects,
            }
        )

    data["layers"] = layers
    data["background"] = {"color": background.get("color", "#FFFFFF"), "assetId": None}
    return data


def _migrate(data: dict) -> dict:
    """版本迁移链。"""
    version = int(data.get("version", FORMAT_VERSION))
    if version > FORMAT_VERSION:
        raise ValueError(
            f"工程文件版本 {version} 高于当前程序支持的 {FORMAT_VERSION}，请升级程序。"
        )
    while version < FORMAT_VERSION:
        if version == 1:
            data = _migrate_1_to_2(data)
        version += 1
    data["version"] = version
    return data


# ------------------------------------------------------------------ 读
def _read_raw(path: str) -> dict:
    p = Path(path)
    try:
        with zipfile.ZipFile(p) as archive:
            if PROJECT_JSON not in archive.namelist():
                raise ValueError("压缩包里没有 project.json，可能不是 DrawX 工程文件。")
            data = json.loads(archive.read(PROJECT_JSON).decode("utf-8"))
            data["__assets_raw__"] = {
                name: archive.read(name)
                for name in archive.namelist()
                if name.startswith("assets/") and not name.endswith("/")
            }
            return data
    except zipfile.BadZipFile:
        # 兼容纯 JSON 工程（早期格式 / 手工编辑过的文件）
        with open(p, "rb") as handle:
            data = json.loads(handle.read().decode("utf-8"))
        data["__assets_raw__"] = {}
        return data


def _load_asset_images(data: dict) -> dict:
    raw_assets: dict = data.pop("__assets_raw__", {}) or {}
    assets = data.get("assets", {}) if isinstance(data.get("assets"), dict) else {}
    images: dict[str, QImage] = {}
    for asset_id, info in assets.items():
        if not isinstance(info, dict):
            continue
        blob = raw_assets.get(str(info.get("path", "")))
        if not blob:
            continue
        image = image_from_bytes(blob)
        if not image.isNull():
            images[str(asset_id)] = image
    return images


def load_project(path: str):
    """返回 ``(文档, 图层列表(顶层在前，对象已重建), 视图状态)``。"""
    data = _migrate(_read_raw(path))
    images = _load_asset_images(data)

    doc = Document()
    canvas = data.get("canvas", {}) if isinstance(data.get("canvas"), dict) else {}
    background = data.get("background", {}) if isinstance(data.get("background"), dict) else {}
    doc.bg_color = str(canvas.get("background", background.get("color", "#FFFFFF")))
    doc.set_canvas(int(canvas.get("width", 1) or 1), int(canvas.get("height", 1) or 1))

    crop = data.get("crop")
    if isinstance(crop, dict):
        doc.crop = QRectF(
            float(crop.get("x", 0.0)),
            float(crop.get("y", 0.0)),
            float(crop.get("w", doc.canvas_w)),
            float(crop.get("h", doc.canvas_h)),
        )
    else:
        doc.reset_crop()
    doc.clamp_crop()

    from ..items.factory import create_item

    layers: list[Layer] = []
    raw_layers = data.get("layers")
    if not isinstance(raw_layers, list):
        raw_layers = []
    missing = 0
    for raw in raw_layers:
        if not isinstance(raw, dict):
            continue
        layer = Layer.from_dict(raw)
        for obj in raw.get("objects") or []:
            if not isinstance(obj, dict):
                continue
            item = create_item(obj, images)
            if item is not None:
                if item.TYPE == "image" and not item.has_source():
                    missing += 1
                layer.items.append(item)
        layers.append(layer)
    if not layers:
        layers.append(Layer(id=new_layer_id(KIND_ANNOTATION), name="标注"))

    doc.active_layer_id = layers[0].id
    doc.extra = {k: v for k, v in data.items() if k not in _TOP_LEVEL_KEYS}
    doc.file_path = str(path)
    #: 有多少张图片的位图在文件里找不到（面板会提示，但工程本身照常打开）
    doc.missing_assets = missing
    # 让返回的 Document 自身就是自洽的（document.has_image / image_layers 依赖它），
    # 而不是"必须有人再调用 adopt_document 才算装配好"。
    doc.layers = layers
    view_state = data.get("view", {}) if isinstance(data.get("view"), dict) else {}
    return doc, layers, view_state
