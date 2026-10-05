"""工具注册表。"""

from __future__ import annotations

from .base import Tool
from .crop_tool import CropTool
from .draw_tools import FreehandTool, LineTool, PatchTool, ShapeTool, TextTool
from .select_tool import SelectTool

#: 工具栏顺序（按使用频率排）
TOOL_ORDER = [
    "select",
    "crop",
    "rect",
    "ellipse",
    "roundrect",
    "line",
    "arrow",
    "freehand",
    "highlight",
    "text",
    "mosaic",
    "blur",
]

#: 字母快捷键
TOOL_KEYS = {
    "v": "select",
    "c": "crop",
    "r": "rect",
    "o": "ellipse",
    "u": "roundrect",
    "l": "line",
    "a": "arrow",
    "p": "freehand",
    "h": "highlight",
    "t": "text",
    "b": "mosaic",
    "m": "blur",
}


def build_tools() -> dict[str, Tool]:
    tools: list[Tool] = [
        SelectTool(),
        CropTool(),
        ShapeTool("rect"),
        ShapeTool("ellipse"),
        ShapeTool("roundrect"),
        LineTool("line"),
        LineTool("arrow"),
        FreehandTool("freehand"),
        FreehandTool("highlight"),
        TextTool(),
        PatchTool("mosaic"),
        PatchTool("blur"),
    ]
    return {tool.name: tool for tool in tools}
