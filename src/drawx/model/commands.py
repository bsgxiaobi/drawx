"""撤销命令。

架构纪律：**任何修改文档的代码路径都必须包在 QUndoCommand 里**。
命令统一用对象状态快照（``to_dict()``/``apply_dict()``）实现，
这样"移动/缩放/旋转/改样式/改层级/改文字"只需要一个 ModifyCommand，
而且天然是对象级撤销（内存开销极小），不是像素级回滚。
"""

from __future__ import annotations

from PySide6.QtGui import QUndoCommand

MERGE_TAG = 0x1001


class AddItemsCommand(QUndoCommand):
    """按字典新建对象并加入场景。

    ``adopt`` 用于"对象已经在场景里"的情况（交互绘制时对象一直存在做预览），
    此时首次 redo 只是把它重新加入（幂等），既不会闪一下也不会多分配对象。
    """

    def __init__(
        self, scene, data_list: list[dict], text: str = "添加标注", adopt: list | None = None
    ) -> None:
        super().__init__(text)
        self._scene = scene
        self._data = [dict(d) for d in data_list]
        self._items: list = list(adopt or [])

    def items(self) -> list:
        return list(self._items)

    def redo(self) -> None:
        if self._items:
            for item in self._items:
                self._scene.add_anno(item)
        else:
            for data in self._data:
                item = self._scene.create_item(data)
                if item is None:
                    continue
                self._items.append(item)
                self._scene.add_anno(item)
        self._scene.set_selection(self._items)

    def undo(self) -> None:
        self._scene.set_selection([])
        for item in self._items:
            self._scene.remove_anno(item)


class RemoveItemsCommand(QUndoCommand):
    """删除对象；撤销时复用同一批对象，状态原样恢复。"""

    def __init__(self, scene, items: list, text: str = "删除标注") -> None:
        super().__init__(text)
        self._scene = scene
        self._items = list(items)

    def redo(self) -> None:
        self._scene.set_selection([])
        for item in self._items:
            self._scene.remove_anno(item)

    def undo(self) -> None:
        for item in self._items:
            self._scene.add_anno(item)
        self._scene.set_selection(self._items)


class ModifyCommand(QUndoCommand):
    """通用修改命令：记录修改前后的对象快照。"""

    def __init__(
        self,
        items: list,
        old_data: list[dict],
        new_data: list[dict],
        text: str = "修改标注",
        mergeable: bool = False,
        merge_key: tuple | None = None,
    ) -> None:
        super().__init__(text)
        self._items = list(items)
        self._old = [dict(d) for d in old_data]
        self._new = [dict(d) for d in new_data]
        self._mergeable = mergeable
        self._merge_key = merge_key

    def id(self) -> int:  # noqa: A003 - Qt 接口
        return MERGE_TAG if self._mergeable else -1

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802 - Qt 接口
        if not self._mergeable or not isinstance(other, ModifyCommand):
            return False
        if other._merge_key != self._merge_key:
            return False
        if [id(i) for i in other._items] != [id(i) for i in self._items]:
            return False
        self._new = other._new
        self.setText(other.text())
        return True

    def redo(self) -> None:
        self._apply(self._new)

    def undo(self) -> None:
        self._apply(self._old)

    def _apply(self, data: list[dict]) -> None:
        for item, snapshot in zip(self._items, data):
            item.apply_dict(snapshot)


class DocPropCommand(QUndoCommand):
    """文档级属性（裁剪框、背景色…）的修改，setter 里顺带刷新视图。"""

    def __init__(self, setter, old, new, text: str = "修改画布") -> None:
        super().__init__(text)
        self._setter = setter
        self._old = old
        self._new = new

    def redo(self) -> None:
        self._setter(self._new)

    def undo(self) -> None:
        self._setter(self._old)


class CompoundCommand(QUndoCommand):
    """把若干条命令当成一次操作（例如同时删掉两个图层 + 一批标注）。

    自己没有状态，只负责按顺序 redo、按反序 undo。全部用同一个 QUndoStack，
    所以撤销历史里只出现一条。
    """

    def __init__(self, commands: list, text: str = "批量操作") -> None:
        super().__init__(text)
        self._commands = list(commands)

    def redo(self) -> None:
        for command in self._commands:
            command.redo()

    def undo(self) -> None:
        for command in reversed(self._commands):
            command.undo()


# ------------------------------------------------------------------ 图层
class AddLayerCommand(QUndoCommand):
    """插入图层（连同它承载的对象一起入场）。"""

    def __init__(self, scene, layer, index: int = 0, text: str = "新建图层") -> None:
        super().__init__(text)
        self._scene = scene
        self._layer = layer
        self._index = int(index)

    def layer(self):
        return self._layer

    def redo(self) -> None:
        self._scene.add_layer(self._layer, self._index)

    def undo(self) -> None:
        self._scene.remove_layer(self._layer)


class RemoveLayerCommand(QUndoCommand):
    """删除图层；撤销时把同一个图层对象（含全部对象）原样放回。"""

    def __init__(self, scene, layer, text: str = "删除图层") -> None:
        super().__init__(text)
        self._scene = scene
        self._layer = layer
        self._index = max(0, scene.layer_index(layer))

    def redo(self) -> None:
        self._scene.remove_layer(self._layer)

    def undo(self) -> None:
        self._scene.add_layer(self._layer, self._index)


class MoveLayerCommand(QUndoCommand):
    """调整图层顺序（行号 0 = 最顶层）。"""

    def __init__(self, scene, layer, new_index: int, text: str = "调整图层顺序") -> None:
        super().__init__(text)
        self._scene = scene
        self._layer = layer
        self._old_index = max(0, scene.layer_index(layer))
        self._new_index = int(new_index)

    def redo(self) -> None:
        self._scene.move_layer(self._layer, self._new_index)

    def undo(self) -> None:
        self._scene.move_layer(self._layer, self._old_index)


class LayerPropCommand(QUndoCommand):
    """图层自身属性：名称 / 显隐 / 锁定 / 不透明度。"""

    def __init__(self, scene, layer, key: str, old, new, text: str = "修改图层") -> None:
        super().__init__(text)
        self._scene = scene
        self._layer = layer
        self._key = key
        self._old = old
        self._new = new

    def id(self) -> int:  # noqa: A003 - Qt 接口
        # 拖动不透明度滑块会连发几十条命令，让它们合并成一条
        return MERGE_TAG if self._key == "opacity" else -1

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802 - Qt 接口
        if not isinstance(other, LayerPropCommand):
            return False
        if other._key != self._key or other._layer is not self._layer:
            return False
        self._new = other._new
        return True

    def redo(self) -> None:
        self._apply(self._new)

    def undo(self) -> None:
        self._apply(self._old)

    def _apply(self, value) -> None:
        setattr(self._layer, self._key, value)
        self._layer.clamp_opacity()
        self._scene.apply_layer_state(self._layer)
