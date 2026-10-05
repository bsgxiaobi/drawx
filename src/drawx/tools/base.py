"""工具基类。

工具只处理交互，不直接改数据 —— 所有修改最终都要变成命令。
视图负责事件分发；工具返回 True 表示"事件我已处理，不要再走默认逻辑"。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt


class Tool:
    name = "select"
    label = "选择"
    hint = ""
    cursor = Qt.CursorShape.ArrowCursor
    #: 是否需要在视图层额外绘制（裁剪框、橡皮筋等）
    draws_overlay = False

    def __init__(self) -> None:
        self.view = None

    # ---------------------------------------------------------- 生命周期
    def activate(self, view) -> None:
        self.view = view
        self.reset()

    def deactivate(self) -> None:
        self.reset()

    def reset(self) -> None:
        """取消进行中的操作（切换工具时调用）。"""

    # ---------------------------------------------------------- 事件
    def mouse_press(self, view, event) -> bool:
        return False

    def mouse_move(self, view, event) -> bool:
        return False

    def mouse_release(self, view, event) -> bool:
        return False

    def mouse_double_click(self, view, event) -> bool:
        return False

    def key_press(self, view, event) -> bool:
        return False

    def hover_handle(self, view, view_pos) -> str | None:
        """悬停到某个控制点时返回它的名字，供视图切换光标。"""
        return None

    def paint_overlay(self, view, painter) -> None:
        """在视口坐标系里画工具的临时装饰。"""

    # ---------------------------------------------------------- 小工具
    @staticmethod
    def scene_pos(view, event) -> QPointF:
        return view.to_scene(event.position())
