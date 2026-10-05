"""工具栏图标：用 QPainter 现画，避免依赖外部图标资源文件。"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)

FG = "#e8e8ee"
ACCENT = "#4d94ff"

#: 弧形箭头（撤销/重做）的几何比例，全部相对图标 size。
#: 关键是**弧线笔宽也必须跟着 size 缩放**：之前笔宽固定 1.7px，而箭头长度按 size
#: 线性放大，于是 64px 下就变成"细弧线 + 一个大实心三角"，比例完全崩掉。
CURVED_ARROW = {
    "pen": 0.070,    # 弧线粗细
    "head": 0.205,   # 箭头长度（受下面第 3 条约束限制，别单独调大）
    "spread": 36.0,  # 箭头半张角（度），总张角 72°
    "bias": 19.0,    # 箭头方向额外往外偏的角度（用户要求"箭头更朝外"）
    "x": 0.066,      # 弧线外接矩形（椭圆只画上面一段，所以矩形可以伸到框外一点）
    "y": 0.445,
    "w": 0.82,
    "h": 0.56,
    "start": 30.0,   # 起点角度（30° = 右上方）
    "end": 138.0,    # 终点角度（138° = 左上方；别靠近 180°，那里切线几乎垂直向下）
}


def arc_local_radius(cfg: dict, deg: float) -> float:
    """椭圆弧在 ``deg`` 处的曲率半径（单位与 cfg 的 w/h 一致，即 size 的倍数）。

    这条是调参时最容易被忽略的量：椭圆的曲率半径沿弧线变化很大，**越靠近左右两端
    （90°→180°）越小**。收尾角太靠近 180° 时半径只有弧线"平均半径"的三分之二，
    于是同样长的箭头会从三角形两侧戳出来（看着像箭头和弧线断开）。
    """
    rx = float(cfg["w"]) / 2.0
    ry = float(cfg["h"]) / 2.0
    rad = math.radians(deg)
    sin2 = math.sin(rad) ** 2
    cos2 = math.cos(rad) ** 2
    if rx <= 0 or ry <= 0:
        return 0.0
    return ((rx * rx * sin2 + ry * ry * cos2) ** 1.5) / (rx * ry)


def _curved_arrow(painter: QPainter, size: float, to_left: bool) -> None:
    """撤销/重做用的弧形箭头。

    系统标准图标（SP_ArrowBack/Forward）在深色主题下是纯黑的实心三角，很丑，
    所以自己画一个带弧线的浅色箭头。

    四条必须一起满足的约束（任何一条不满足都会画歪）：
    1. **收尾角不能越过 180°**：越过之后该点切线变成"往内侧勾"，箭头就像粘在弧线上的一坨。
    2. **笔宽必须跟着 size 缩放**：笔宽固定时，大尺寸下会变成"细弧线 + 一个大实心三角"。
    3. **箭头长度 ≤ 收尾处的曲率半径 × 张角（弧度）**：弧线在箭头长度内会偏离切线约
       `head/R` 弧度，超过张角就会从三角形两侧戳出来 —— 表现就是箭头和弧线"断开"了。
       注意 ``R`` 要用 :func:`arc_local_radius` 算**该处的**曲率半径，不能用平均值：
       本图标收尾角从 175° 收到 140° 之后半径大了 1.6 倍，才装得下更大的箭头。
    4. **``bias`` 别超过张角的一半左右**：bias 只是把三角形绕尖端往外转一点（让箭头读起来
       更"朝外"而不是往弧线内侧勾），转太多就会和弧线脱节。

    弧线画满、箭头直接盖在末端上（同色不透明，重叠看不出来），比掐准角度截断稳妥。
    """
    cfg = CURVED_ARROW
    rect = QRectF(
        cfg["x"] * size, cfg["y"] * size, cfg["w"] * size, cfg["h"] * size
    )
    cx, cy = rect.center().x(), rect.center().y()
    rx, ry = rect.width() / 2.0, rect.height() / 2.0

    def point(deg: float) -> QPointF:
        rad = math.radians(deg)
        return QPointF(cx + rx * math.cos(rad), cy - ry * math.sin(rad))

    if to_left:
        start_deg, end_deg = cfg["start"], cfg["end"]
    else:
        start_deg, end_deg = 180.0 - cfg["start"], 180.0 - cfg["end"]

    arc_pen = QPen(painter.pen())
    arc_pen.setWidthF(max(1.2, cfg["pen"] * size))
    arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

    tip = point(end_deg)
    previous = point(end_deg - 8.0 if to_left else end_deg + 8.0)
    angle = math.atan2(tip.y() - previous.y(), tip.x() - previous.x())
    # 让箭头再往外偏一点：undo 往左外（角度增大），redo 镜像往右外（角度减小）
    bias = math.radians(float(cfg.get("bias", 0.0)))
    angle += bias if to_left else -bias
    head = cfg["head"] * size
    spread = math.radians(cfg["spread"])
    base_left = QPointF(
        tip.x() - head * math.cos(angle - spread),
        tip.y() - head * math.sin(angle - spread),
    )
    base_right = QPointF(
        tip.x() - head * math.cos(angle + spread),
        tip.y() - head * math.sin(angle + spread),
    )

    path = QPainterPath()
    path.arcMoveTo(rect, start_deg)
    path.arcTo(rect, start_deg, end_deg - start_deg)

    painter.save()
    painter.setPen(arc_pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(FG))
    painter.drawPolygon(QPolygonF([tip, base_left, base_right]))
    painter.restore()


def _copy_image_glyph(painter: QPainter, size: float) -> None:
    """"快速复制为图片"：两张叠在一起的相片。"""
    back = QRectF(0.26 * size, 0.13 * size, 0.50 * size, 0.42 * size)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(back, 0.07 * size, 0.07 * size)

    front = QRectF(0.15 * size, 0.33 * size, 0.58 * size, 0.48 * size)
    painter.setBrush(QColor("#26262a"))
    painter.drawRoundedRect(front, 0.07 * size, 0.07 * size)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(front, 0.07 * size, 0.07 * size)

    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(FG))
    painter.drawEllipse(QRectF(0.22 * size, 0.38 * size, 0.11 * size, 0.11 * size))
    mountain = QPainterPath(QPointF(0.17 * size, 0.76 * size))
    mountain.lineTo(0.37 * size, 0.53 * size)
    mountain.lineTo(0.50 * size, 0.66 * size)
    mountain.lineTo(0.60 * size, 0.58 * size)
    mountain.lineTo(0.71 * size, 0.76 * size)
    mountain.closeSubpath()
    painter.drawPath(mountain)
    painter.restore()


def _pen(width: float = 1.7, color: str = FG) -> QPen:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def tool_icon(name: str, size: int = 22) -> QIcon:
    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(_pen())
    painter.setBrush(Qt.BrushStyle.NoBrush)
    s = float(size)

    if name == "select":
        arrow = QPolygonF(
            [
                QPointF(0.30, 0.14),
                QPointF(0.30, 0.80),
                QPointF(0.45, 0.66),
                QPointF(0.55, 0.90),
                QPointF(0.65, 0.85),
                QPointF(0.55, 0.62),
                QPointF(0.74, 0.60),
            ]
        )
        painter.setBrush(QColor(FG))
        painter.drawPolygon(_scale_polygon(arrow, s))
    elif name == "crop":
        # 注意：这里的坐标必须乘 s（曾经漏乘，图标缩成了 1 像素的小点）
        painter.drawLine(QPointF(0.28 * s, 0.10 * s), QPointF(0.28 * s, 0.70 * s))
        painter.drawLine(QPointF(0.28 * s, 0.70 * s), QPointF(0.88 * s, 0.70 * s))
        painter.drawLine(QPointF(0.10 * s, 0.30 * s), QPointF(0.70 * s, 0.30 * s))
        painter.drawLine(QPointF(0.70 * s, 0.30 * s), QPointF(0.70 * s, 0.90 * s))
    elif name == "rect":
        painter.drawRect(QRectF(0.16 * s, 0.22 * s, 0.68 * s, 0.56 * s))
    elif name == "ellipse":
        painter.drawEllipse(QRectF(0.14 * s, 0.22 * s, 0.72 * s, 0.56 * s))
    elif name == "roundrect":
        painter.drawRoundedRect(
            QRectF(0.16 * s, 0.22 * s, 0.68 * s, 0.56 * s), 0.14 * s, 0.14 * s
        )
    elif name == "line":
        painter.drawLine(QPointF(0.18 * s, 0.80 * s), QPointF(0.82 * s, 0.20 * s))
    elif name == "arrow":
        painter.drawLine(QPointF(0.18 * s, 0.80 * s), QPointF(0.74 * s, 0.26 * s))
        painter.setBrush(QColor(FG))
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(0.84 * s, 0.16 * s),
                    QPointF(0.56 * s, 0.24 * s),
                    QPointF(0.76 * s, 0.44 * s),
                ]
            )
        )
    elif name == "freehand":
        path = QPainterPath(QPointF(0.14 * s, 0.68 * s))
        path.quadTo(QPointF(0.34 * s, 0.16 * s), QPointF(0.48 * s, 0.50 * s))
        path.quadTo(QPointF(0.62 * s, 0.86 * s), QPointF(0.86 * s, 0.34 * s))
        painter.drawPath(path)
    elif name == "highlight":
        pen = _pen(4.2, "#ffd60a")
        painter.setPen(pen)
        painter.drawLine(QPointF(0.18 * s, 0.72 * s), QPointF(0.72 * s, 0.26 * s))
        painter.setPen(_pen(1.2, FG))
        painter.drawRect(QRectF(0.14 * s, 0.14 * s, 0.72 * s, 0.72 * s))
    elif name == "text":
        painter.drawLine(QPointF(0.22 * s, 0.24 * s), QPointF(0.78 * s, 0.24 * s))
        painter.drawLine(QPointF(0.50 * s, 0.24 * s), QPointF(0.50 * s, 0.80 * s))
        painter.drawLine(QPointF(0.36 * s, 0.80 * s), QPointF(0.64 * s, 0.80 * s))
    elif name == "mosaic":
        cell = 0.24 * s
        painter.setPen(Qt.PenStyle.NoPen)
        for row in range(3):
            for col in range(3):
                if (row + col) % 2 == 0:
                    painter.setBrush(QColor(FG))
                else:
                    painter.setBrush(QColor(120, 120, 130))
                painter.drawRect(
                    QRectF(0.16 * s + col * cell, 0.16 * s + row * cell, cell, cell)
                )
    elif name == "blur":
        painter.setPen(_pen(1.6, FG))
        painter.drawEllipse(QRectF(0.30 * s, 0.30 * s, 0.40 * s, 0.40 * s))
        painter.setPen(_pen(1.4, "#9aa0aa"))
        painter.drawEllipse(QRectF(0.16 * s, 0.16 * s, 0.68 * s, 0.68 * s))
        painter.setPen(_pen(1.2, "#5f646d"))
        painter.drawEllipse(QRectF(0.06 * s, 0.06 * s, 0.88 * s, 0.88 * s))
    elif name == "import":
        painter.drawRect(QRectF(0.12 * s, 0.28 * s, 0.76 * s, 0.58 * s))
        painter.drawEllipse(QRectF(0.20 * s, 0.36 * s, 0.14 * s, 0.14 * s))
        painter.drawLine(QPointF(0.50 * s, 0.06 * s), QPointF(0.50 * s, 0.62 * s))
        painter.drawLine(QPointF(0.36 * s, 0.48 * s), QPointF(0.50 * s, 0.62 * s))
        painter.drawLine(QPointF(0.64 * s, 0.48 * s), QPointF(0.50 * s, 0.62 * s))
    elif name == "export":
        painter.drawRect(QRectF(0.12 * s, 0.34 * s, 0.76 * s, 0.52 * s))
        painter.drawEllipse(QRectF(0.20 * s, 0.42 * s, 0.14 * s, 0.14 * s))
        painter.drawLine(QPointF(0.50 * s, 0.62 * s), QPointF(0.50 * s, 0.08 * s))
        painter.drawLine(QPointF(0.36 * s, 0.22 * s), QPointF(0.50 * s, 0.08 * s))
        painter.drawLine(QPointF(0.64 * s, 0.22 * s), QPointF(0.50 * s, 0.08 * s))
    elif name == "delete":
        painter.drawLine(QPointF(0.22 * s, 0.28 * s), QPointF(0.78 * s, 0.28 * s))
        painter.drawLine(QPointF(0.40 * s, 0.28 * s), QPointF(0.44 * s, 0.18 * s))
        painter.drawLine(QPointF(0.60 * s, 0.28 * s), QPointF(0.56 * s, 0.18 * s))
        painter.drawLine(QPointF(0.44 * s, 0.18 * s), QPointF(0.56 * s, 0.18 * s))
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(0.28 * s, 0.32 * s),
                    QPointF(0.72 * s, 0.32 * s),
                    QPointF(0.65 * s, 0.84 * s),
                    QPointF(0.35 * s, 0.84 * s),
                ]
            )
        )
    elif name == "undo":
        _curved_arrow(painter, s, to_left=True)
    elif name == "redo":
        _curved_arrow(painter, s, to_left=False)
    elif name == "copy_image":
        _copy_image_glyph(painter, s)
    elif name in ("eye", "eye_off"):
        _eye_glyph(painter, s, closed=name == "eye_off")
    elif name in ("lock", "unlock"):
        _lock_glyph(painter, s, locked=name == "lock")
    elif name == "image":
        _picture_glyph(painter, s)
    elif name == "layers":
        _layers_glyph(painter, s)
    elif name == "layer_add":
        _picture_glyph(painter, s, box=QRectF(0.08 * s, 0.20 * s, 0.62 * s, 0.58 * s))
        painter.setPen(_pen(2.0, ACCENT))
        painter.drawLine(QPointF(0.80 * s, 0.30 * s), QPointF(0.80 * s, 0.62 * s))
        painter.drawLine(QPointF(0.64 * s, 0.46 * s), QPointF(0.96 * s, 0.46 * s))
    elif name == "layer_dup":
        painter.drawRoundedRect(QRectF(0.30 * s, 0.10 * s, 0.58 * s, 0.46 * s), 0.06 * s, 0.06 * s)
        painter.drawRoundedRect(QRectF(0.12 * s, 0.40 * s, 0.58 * s, 0.46 * s), 0.06 * s, 0.06 * s)
    elif name == "move_up":
        painter.drawLine(QPointF(0.50 * s, 0.82 * s), QPointF(0.50 * s, 0.22 * s))
        painter.drawLine(QPointF(0.28 * s, 0.44 * s), QPointF(0.50 * s, 0.22 * s))
        painter.drawLine(QPointF(0.72 * s, 0.44 * s), QPointF(0.50 * s, 0.22 * s))
    elif name == "move_down":
        painter.drawLine(QPointF(0.50 * s, 0.18 * s), QPointF(0.50 * s, 0.78 * s))
        painter.drawLine(QPointF(0.28 * s, 0.56 * s), QPointF(0.50 * s, 0.78 * s))
        painter.drawLine(QPointF(0.72 * s, 0.56 * s), QPointF(0.50 * s, 0.78 * s))
    else:
        painter.drawEllipse(QRectF(0.2 * s, 0.2 * s, 0.6 * s, 0.6 * s))

    painter.end()
    return QIcon(pixmap)


def _eye_glyph(painter: QPainter, size: float, closed: bool = False) -> None:
    """图层显隐：眼睛（闭眼 = 带斜杠）。"""
    path = QPainterPath(QPointF(0.08 * size, 0.50 * size))
    path.quadTo(QPointF(0.50 * size, 0.06 * size), QPointF(0.92 * size, 0.50 * size))
    path.quadTo(QPointF(0.50 * size, 0.94 * size), QPointF(0.08 * size, 0.50 * size))
    painter.save()
    if closed:
        painter.setPen(_pen(1.7, "#7c7c86"))
    painter.drawPath(path)
    painter.setBrush(QColor(FG if not closed else "#7c7c86"))
    painter.drawEllipse(QRectF(0.38 * size, 0.38 * size, 0.24 * size, 0.24 * size))
    if closed:
        painter.setPen(_pen(2.0, "#ff6b60"))
        painter.drawLine(QPointF(0.14 * size, 0.86 * size), QPointF(0.86 * size, 0.14 * size))
    painter.restore()


def _lock_glyph(painter: QPainter, size: float, locked: bool = True) -> None:
    """图层锁定：上锁 / 开锁。"""
    painter.save()
    color = "#e8c14a" if locked else "#7c7c86"
    painter.setPen(_pen(1.7, color))
    # 锁梁：开锁时向右上翘起并偏到右侧
    if locked:
        painter.drawArc(
            QRectF(0.30 * size, 0.12 * size, 0.40 * size, 0.44 * size), 0, 180 * 16
        )
    else:
        painter.drawArc(
            QRectF(0.46 * size, 0.10 * size, 0.42 * size, 0.44 * size), 0, 180 * 16
        )
    painter.setPen(QPen(QColor(color), 1.4))
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(
        QRectF(0.24 * size, 0.46 * size, 0.52 * size, 0.42 * size),
        0.08 * size,
        0.08 * size,
    )
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#2a2a30"))
    painter.drawEllipse(QRectF(0.46 * size, 0.60 * size, 0.09 * size, 0.16 * size))
    painter.restore()


def _picture_glyph(painter: QPainter, size: float, box: QRectF | None = None) -> None:
    """图片图层的类型标志：相框 + 山 + 太阳。"""
    frame = box if box is not None else QRectF(0.10 * size, 0.16 * size, 0.80 * size, 0.68 * size)
    painter.save()
    painter.setPen(_pen(1.6))
    painter.setBrush(QColor("#26262a"))
    painter.drawRoundedRect(frame, 0.06 * size, 0.06 * size)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(FG))
    painter.drawEllipse(
        QRectF(
            frame.left() + 0.12 * frame.width(),
            frame.top() + 0.14 * frame.height(),
            0.14 * frame.width(),
            0.14 * frame.height(),
        )
    )
    mountain = QPainterPath(
        QPointF(frame.left() + 0.08 * frame.width(), frame.bottom() - 0.10 * frame.height())
    )
    mountain.lineTo(
        frame.left() + 0.42 * frame.width(), frame.top() + 0.38 * frame.height()
    )
    mountain.lineTo(
        frame.left() + 0.62 * frame.width(), frame.bottom() - 0.30 * frame.height()
    )
    mountain.lineTo(
        frame.left() + 0.78 * frame.width(), frame.top() + 0.50 * frame.height()
    )
    mountain.lineTo(frame.right() - 0.06 * frame.width(), frame.bottom() - 0.10 * frame.height())
    mountain.closeSubpath()
    painter.setBrush(QColor(FG))
    painter.drawPath(mountain)
    painter.restore()


def _layers_glyph(painter: QPainter, size: float) -> None:
    """标注图层的类型标志：三层叠片。

    三层叠片的墨迹范围是 0.10~0.90（重心正好在 0.5）—— 图标要么整体居中，
    要么在工具栏里会比旁边的图标高/低一两像素（`devtools/icon_metrics.py` 能量出来）。
    """
    painter.save()
    painter.setPen(_pen(1.6))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for index, top in enumerate((0.10, 0.36, 0.62)):
        path = QPainterPath(QPointF(0.50 * size, top * size))
        path.lineTo(0.88 * size, (top + 0.14) * size)
        path.lineTo(0.50 * size, (top + 0.28) * size)
        path.lineTo(0.12 * size, (top + 0.14) * size)
        path.closeSubpath()
        if index == 2:
            painter.setBrush(QColor("#3a3a44"))
        painter.drawPath(path)
    painter.restore()


def _scale_polygon(polygon: QPolygonF, size: float) -> QPolygonF:
    return QPolygonF([QPointF(p.x() * size, p.y() * size) for p in polygon])


def color_swatch(color: str, size: int = 18) -> QIcon:
    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    rect = QRectF(1.5, 1.5, size - 3.0, size - 3.0)
    if QColor(color).alpha() == 0:
        painter.setBrush(QColor(60, 60, 66))
        painter.setPen(QPen(QColor("#8a8a92"), 1))
        painter.drawRect(rect)
        painter.setPen(QPen(QColor("#ff5f56"), 1.6))
        painter.drawLine(rect.topLeft(), rect.bottomRight())
    else:
        painter.setBrush(QColor(color))
        painter.setPen(QPen(QColor("#20202a"), 1))
        painter.drawRect(rect)
    painter.end()
    return QIcon(pixmap)
