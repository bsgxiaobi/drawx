"""文字标注对象。

直接用 ``QGraphicsTextItem`` 作为基类，白拿输入法（IME）、光标、选区、
自动换行与撤销支持 —— 中文输入法是这个项目最容易踩坑的地方，交给 Qt 最稳。

尺寸约定：文字对象的宽 = 自动换行宽度（``setTextWidth``），高度由内容决定。
所以拉伸文字框只改变换行宽度，不会把字压扁，这与标注工具的用户预期一致。
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QTextOption
from PySide6.QtWidgets import QGraphicsTextItem

from .base import AnnoMixin, TEXT_STYLE_KEYS


class TextItem(QGraphicsTextItem, AnnoMixin):
    TYPE = "text"
    LABEL = "文字"
    CLOSED_SHAPE = True

    def __init__(self, style: dict | None = None, text: str = "") -> None:
        QGraphicsTextItem.__init__(self)
        merged = dict(TEXT_STYLE_KEYS)
        merged.update(style or {})
        self._anno_init(merged)
        self.setPlainText(text)
        self._wrap_width = -1.0
        self.apply_text_style()
        self.refresh_origin()

    # ---------------------------------------------------------- 样式
    def apply_text_style(self) -> None:
        family = str(self.style.get("fontFamily", "Microsoft YaHei"))
        font = QFont(family)
        # 字体回退链：目标机器不一定装了雅黑（尤其是精简版系统）
        font.setFamilies(
            [
                family,
                "Microsoft YaHei UI",
                "Microsoft YaHei",
                "微软雅黑",
                "PingFang SC",
                "Noto Sans CJK SC",
                "Source Han Sans SC",
                "SimHei",
                "SimSun",
                "sans-serif",
            ]
        )
        font.setPointSizeF(max(4.0, float(self.style.get("fontSize", 20))))
        font.setBold(bool(self.style.get("bold", False)))
        font.setItalic(bool(self.style.get("italic", False)))
        self.setFont(font)
        self.setDefaultTextColor(QColor(self.style.get("stroke", "#FF3B30")))
        self.document().setDocumentMargin(4.0)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.document().setDefaultTextOption(option)
        self.apply_style()

    def set_style_value(self, key: str, value) -> None:
        self.style[key] = value
        if key in ("stroke", "fontFamily", "fontSize", "bold", "italic"):
            self.apply_text_style()
        else:
            self.apply_style()
            if key in ("strokeWidth", "strokeStyle"):
                self.prepareGeometryChange()
                self.refresh_origin()

    # ---------------------------------------------------------- 几何
    def local_rect(self) -> QRectF:
        doc_size = self.document().size()
        if self._wrap_width and self._wrap_width > 0:
            width = float(self._wrap_width)
        else:
            width = max(8.0, doc_size.width())
        return QRectF(0.0, 0.0, width, max(1.0, doc_size.height()))

    def set_local_rect(self, rect: QRectF) -> None:
        """文字只按宽度重排，高度自适应。"""
        self.prepareGeometryChange()
        self._wrap_width = max(16.0, float(rect.width()))
        self.setTextWidth(self._wrap_width)
        self.refresh_origin()

    def content_margin(self) -> float:
        return 6.0

    def boundingRect(self) -> QRectF:
        r = self.local_rect()
        return r.adjusted(-6.0, -6.0, 6.0, 6.0)

    # ---------------------------------------------------------- 编辑态
    def begin_edit(self) -> None:
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.setTextCursor(cursor)

    def end_edit(self) -> None:
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        # QGraphicsTextItem 没有 deselect()，清选区要走 textCursor
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)
        self.prepareGeometryChange()
        self.refresh_origin()

    @property
    def editing(self) -> bool:
        return bool(
            self.textInteractionFlags() & Qt.TextInteractionFlag.TextEditorInteraction
        )

    def focusOutEvent(self, event) -> None:
        QGraphicsTextItem.focusOutEvent(self, event)
        # 失焦即提交（例如点到工具栏上）
        scene = self.scene()
        if scene is None:
            return
        for view in scene.views():
            if getattr(view, "_edit_item", None) is self:
                view.finish_text_edit()
                break

    # ---------------------------------------------------------- 序列化
    def geometry_dict(self) -> dict:
        return {
            "text": self.toPlainText(),
            "wrapWidth": round(float(self._wrap_width), 3),
        }

    def apply_geometry(self, geometry: dict, data: dict) -> None:
        self.setPlainText(str(geometry.get("text", "")))
        wrap = float(geometry.get("wrapWidth", -1.0))
        self._wrap_width = wrap
        self.setTextWidth(wrap)
        self.apply_text_style()
