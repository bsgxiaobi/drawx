"""主窗口：菜单、工具栏、图层/属性面板、状态栏、文件与剪贴板。"""

from __future__ import annotations

import json
import math
from pathlib import Path

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    QMimeData,
    QPointF,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStyle,
    QToolBar,
)

from ..const import (
    APP_NAME,
    APP_NAME_CN,
    APP_VERSION,
    EXPORT_FILTER,
    IMAGE_OPEN_FILTER,
    IMAGE_SUFFIXES,
    PROJECT_EXT,
    PROJECT_FILTER,
)
from ..items.base import new_id
from ..items.factory import type_label
from ..items.image_item import ImageItem
from ..model import serialize
from ..model.commands import (
    AddItemsCommand,
    AddLayerCommand,
    CompoundCommand,
    DocPropCommand,
    ModifyCommand,
)
from ..model.layers import KIND_ANNOTATION, KIND_IMAGE, Layer, new_layer_id
from ..render.effects import read_image_with_orientation
from ..render.exporter import export_document, render_document
from ..tools import TOOL_KEYS, TOOL_ORDER
from .canvas_scene import CanvasScene
from .canvas_view import CanvasView
from . import dialogs
from .dialogs import ExportDialog
from .icons import tool_icon
from .layer_panel import LayerPanel
from .property_panel import PropertyPanel

OBJECT_MIME = "application/x-drawx-objects"

#: 新图片不重叠摆放时的间距
IMAGE_GAP = 24.0


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME_CN} {APP_NAME}")
        self.resize(1360, 880)
        self.setAcceptDrops(True)
        # 再给窗口自己设一次：某些情况下（多窗口、后续子窗口）更稳
        from .appicon import app_icon

        self.setWindowIcon(app_icon())

        self.scene = CanvasScene(self)
        self.view = CanvasView(self.scene, self)
        self.setCentralWidget(self.view)
        self.property_panel = PropertyPanel(self.view, self)
        self.layer_panel = LayerPanel(self.view, self)
        self._guard_actions: list[QAction] = []
        self._tool_actions: dict[str, QAction] = {}
        self._fitted_on_show = False
        #: 正在整份替换文档（新建/打开）。期间 undo_stack.clear() 会发 indexChanged，
        #: 不能让它把"干净的"新文档标成已修改（否则新建完就弹保存提示）。
        self._loading_document = False

        self._build_actions()
        self._build_menu()
        self._build_toolbars()
        self._build_docks()
        self._build_statusbar()
        self._connect()

        self._reset_document(1280, 800)
        self.view.fit_to_window()

    # ============================================================== 构建
    def _act(
        self,
        text: str,
        slot,
        shortcut: str | list[str] | None = None,
        icon=None,
        checkable: bool = False,
        tip: str | None = None,
    ) -> QAction:
        action = QAction(text, self)
        if shortcut:
            sequences = [shortcut] if isinstance(shortcut, str) else list(shortcut)
            action.setShortcuts([QKeySequence(item) for item in sequences])
        if icon is not None:
            action.setIcon(icon)
        action.setCheckable(checkable)
        action.triggered.connect(slot)
        if tip:
            action.setToolTip(tip)
            action.setStatusTip(tip)
        self.addAction(action)
        return action

    def _std_icon(self, name):
        return self.style().standardIcon(name)

    def _build_actions(self) -> None:
        sp = QStyle.StandardPixmap
        self.act_new = self._act("新建", self.new_document, "Ctrl+N", self._std_icon(sp.SP_FileIcon), tip="新建空白画布")
        self.act_open = self._act("打开工程…", self.open_project_dialog, "Ctrl+O", self._std_icon(sp.SP_DialogOpenButton), tip="打开 .drawx 工程文件")
        self.act_import = self._act(
            "添加图片图层…",
            self.import_image_dialog,
            "Ctrl+I",
            tool_icon("import"),
            tip="把图片作为新的图片图层导入，可多选；一张画布上能叠加/拼合多张图"
                 "（也可直接拖文件进来或 Ctrl+V 粘贴截图）",
        )
        self.act_save = self._act("保存", self.save_project, "Ctrl+S", self._std_icon(sp.SP_DialogSaveButton))
        # 另存为同时给两个快捷键：中文输入法会吞掉 Ctrl+Shift 组合，F12 是保底
        self.act_save_as = self._act(
            "另存为…",
            lambda: self.save_project(save_as=True),
            ["Ctrl+Shift+S", "F12"],
            tip="另存为（F12 保底：部分中文输入法会拦截 Ctrl+Shift 组合键）",
        )
        self.act_export = self._act("导出图片…", self.export_image, "Ctrl+E", tool_icon("export"), tip="导出 PNG / JPG / WebP / BMP")
        self.act_copy_image = self._act(
            "快速复制为图片",
            self.quick_copy_image,
            ["Ctrl+Alt+C", "Ctrl+Shift+C"],
            tool_icon("copy_image"),
            tip="把当前画面按 PNG 复制到剪贴板；没有选中对象时按 Ctrl+C 也是这个效果",
        )
        self.act_quit = self._act("退出", self.close, "Ctrl+Q")

        stack = self.scene.undo_stack
        self.act_undo = stack.createUndoAction(self, "撤销")
        self.act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.act_undo.setIcon(tool_icon("undo"))
        self.act_redo = stack.createRedoAction(self, "重做")
        self.act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self.act_redo.setIcon(tool_icon("redo"))
        self.addAction(self.act_undo)
        self.addAction(self.act_redo)

        self.act_select_all = self._act("全选", lambda: self.scene.select_all(), "Ctrl+A")
        self.act_deselect = self._act("取消选择", self._deselect, "Ctrl+D")
        self.act_delete = self._act("删除选中", self.view.delete_selected, "Del", tool_icon("delete"))
        self.act_copy = self._act("复制", self.copy_selection, "Ctrl+C")
        self.act_cut = self._act("剪切", self.cut_selection, "Ctrl+X")
        self.act_paste = self._act("粘贴", self.paste, "Ctrl+V", tip="粘贴系统剪贴板里的截图，或粘贴已复制的标注对象")

        self.act_zoom_in = self._act("放大", lambda: self.view.zoom_by(1.25, under_mouse=False), "Ctrl+=")
        self.act_zoom_out = self._act("缩小", lambda: self.view.zoom_by(1 / 1.25, under_mouse=False), "Ctrl+-")
        self.act_zoom_fit = self._act("适应窗口", self.view.fit_to_window, "Ctrl+0")
        self.act_zoom_100 = self._act("实际大小", self.view.zoom_reset, "Ctrl+1")
        self.act_crop_reset = self._act("恢复完整画面", self.reset_crop, tip="把非破坏裁剪框恢复成整幅图片")

        # --- 图层
        self.act_layer_image = self._act(
            "新建图片图层…", self.import_image_dialog, tip="等同「添加图片图层」"
        )
        self.act_layer_anno = self._act(
            "新建标注图层", self.layer_panel.add_annotation_layer,
            ["Ctrl+Shift+N", "Ctrl+Alt+N"],
            tip="标注图层用来分组，也决定标注在图片上面还是下面"
        )
        self.act_layer_dup = self._act(
            "复制图层", self.layer_panel.duplicate_layer, "Ctrl+J", tool_icon("layer_dup")
        )
        self.act_layer_del = self._act(
            "删除图层", self.layer_panel.delete_layer, ["Ctrl+Shift+Del", "Ctrl+Alt+D"]
        )
        self.act_layer_up = self._act("上移一层", lambda: self.layer_panel.move_layer(-1), "Ctrl+]", tool_icon("move_up"))
        self.act_layer_down = self._act("下移一层", lambda: self.layer_panel.move_layer(1), "Ctrl+[", tool_icon("move_down"))
        self.act_layer_top = self._act("置顶", lambda: self.layer_panel.move_to(0))
        self.act_layer_bottom = self._act(
            "置底", lambda: self.layer_panel.move_to(len(self.scene.layers()) - 1)
        )
        self.act_layer_visible = self._act("显示/隐藏图层", self.layer_panel.toggle_visible)
        self.act_layer_lock = self._act("锁定/解锁图层", self.layer_panel.toggle_locked)
        self.act_layer_rename = self._act("重命名图层…", self.layer_panel.rename_layer, "F2")
        self.act_layer_reset_crop = self._act(
            "重置图片裁剪", self.layer_panel.reset_image_crop,
            tip="把图片图层恢复成完整原图",
        )

        # --- 画布
        self.act_canvas_size = self._act("画布大小…", self.set_canvas_size_dialog, tip="设置最终成图的画布尺寸")
        self.act_canvas_fit_content = self._act(
            "画布适应内容", self.fit_canvas_to_content, ["Ctrl+Shift+F", "F9"],
            tip="把所有图层收进画布并消除空白边（多张图片拼合后常用）",
        )
        self.act_canvas_arrange = self._act(
            "自动排列图片图层", self.arrange_image_layers,
            tip="把可见的图片图层按网格排布、统一缩放并重设画布，适合把多张现场照片汇成一张",
        )
        self.act_canvas_white = self._act("白色背景", lambda: self.set_canvas_color("#FFFFFF"))
        self.act_canvas_gray = self._act("浅灰背景", lambda: self.set_canvas_color("#F2F2F4"))
        self.act_canvas_dark = self._act("深灰背景", lambda: self.set_canvas_color("#22222A"))

        self.act_help = self._act("快捷键", self.show_shortcuts, "F1")
        self.act_about = self._act("关于", self.show_about)

        self._guard_actions = [
            self.act_undo,
            self.act_redo,
            self.act_select_all,
            self.act_delete,
            self.act_copy,
            self.act_cut,
            self.act_paste,
        ]

    def _build_menu(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("文件")
        for action in (self.act_new, self.act_open, self.act_import):
            file_menu.addAction(action)
        file_menu.addSeparator()
        for action in (self.act_save, self.act_save_as, self.act_export, self.act_copy_image):
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        edit_menu = bar.addMenu("编辑")
        edit_menu.addAction(self.act_undo)
        edit_menu.addAction(self.act_redo)
        edit_menu.addSeparator()
        for action in (
            self.act_select_all,
            self.act_deselect,
            self.act_delete,
            self.act_copy,
            self.act_cut,
            self.act_paste,
        ):
            edit_menu.addAction(action)

        view_menu = bar.addMenu("视图")
        for action in (
            self.act_zoom_in,
            self.act_zoom_out,
            self.act_zoom_fit,
            self.act_zoom_100,
        ):
            view_menu.addAction(action)
        view_menu.addSeparator()
        view_menu.addAction(self.act_crop_reset)

        layer_menu = bar.addMenu("图层")
        for action in (
            self.act_layer_image,
            self.act_layer_anno,
            self.act_layer_dup,
            self.act_layer_del,
        ):
            layer_menu.addAction(action)
        layer_menu.addSeparator()
        for action in (
            self.act_layer_up,
            self.act_layer_down,
            self.act_layer_top,
            self.act_layer_bottom,
        ):
            layer_menu.addAction(action)
        layer_menu.addSeparator()
        for action in (
            self.act_layer_visible,
            self.act_layer_lock,
            self.act_layer_rename,
            self.act_layer_reset_crop,
        ):
            layer_menu.addAction(action)

        canvas_menu = bar.addMenu("画布")
        for action in (
            self.act_canvas_size,
            self.act_canvas_fit_content,
            self.act_canvas_arrange,
        ):
            canvas_menu.addAction(action)
        canvas_menu.addSeparator()
        canvas_menu.addAction(self.act_canvas_white)
        canvas_menu.addAction(self.act_canvas_gray)
        canvas_menu.addAction(self.act_canvas_dark)

        tool_menu = bar.addMenu("工具")
        for name in TOOL_ORDER:
            action = self._tool_actions.get(name)
            if action is not None:
                tool_menu.addAction(action)

        help_menu = bar.addMenu("帮助")
        help_menu.addAction(self.act_help)
        help_menu.addAction(self.act_about)

    def _build_toolbars(self) -> None:
        main_bar = QToolBar("主工具栏", self)
        main_bar.setMovable(False)
        for action in (self.act_new, self.act_open, self.act_import, self.act_save, self.act_export):
            main_bar.addAction(action)
        main_bar.addSeparator()
        main_bar.addAction(self.act_copy_image)
        main_bar.addAction(self.act_undo)
        main_bar.addAction(self.act_redo)
        main_bar.addSeparator()
        main_bar.addAction(self.act_zoom_out)
        main_bar.addAction(self.act_zoom_fit)
        main_bar.addAction(self.act_zoom_100)
        main_bar.addAction(self.act_zoom_in)
        main_bar.addSeparator()
        main_bar.addAction(self.act_delete)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, main_bar)

        tool_bar = QToolBar("工具", self)
        tool_bar.setMovable(False)
        tool_bar.setOrientation(Qt.Orientation.Vertical)
        group = QActionGroup(self)
        group.setExclusive(True)
        for name in TOOL_ORDER:
            tool = self.view.tools().get(name)
            if tool is None:
                continue
            key = next((k.upper() for k, v in TOOL_KEYS.items() if v == name), "")
            action = QAction(tool_icon(name), tool.label, self)
            action.setCheckable(True)
            action.setToolTip(f"{tool.label} ({key})\n{tool.hint}")
            action.triggered.connect(lambda _checked=False, n=name: self.view.set_tool(n))
            group.addAction(action)
            tool_bar.addAction(action)
            self._tool_actions[name] = action
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, tool_bar)
        self._tool_actions["select"].setChecked(True)

    def _build_docks(self) -> None:
        dock = QDockWidget("属性", self)
        dock.setWidget(self.property_panel)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.property_dock = dock

        layer_dock = QDockWidget("图层", self)
        layer_dock.setWidget(self.layer_panel)
        layer_dock.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        layer_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, layer_dock)
        # 上下叠放：属性在上、图层在下（图层列表越长越顺手）
        self.splitDockWidget(dock, layer_dock, Qt.Orientation.Vertical)
        self.layer_dock = layer_dock
        self.resizeDocks([dock, layer_dock], [460, 330], Qt.Orientation.Vertical)
        self.resizeDocks([dock], [300], Qt.Orientation.Horizontal)

    def _build_statusbar(self) -> None:
        bar = self.statusBar()
        self.status_hint = QLabel("就绪")
        self.status_size = QLabel("")
        self.status_sel = QLabel("未选中")
        self.status_zoom = QLabel("100%")
        self.status_pos = QLabel("")
        for widget in (self.status_size, self.status_sel, self.status_zoom, self.status_pos):
            widget.setMinimumWidth(90)
            widget.setStyleSheet("color:#a0a0a8;")
        bar.addWidget(self.status_hint, 1)
        bar.addPermanentWidget(self.status_size)
        bar.addPermanentWidget(self.status_sel)
        bar.addPermanentWidget(self.status_pos)
        bar.addPermanentWidget(self.status_zoom)

    def _connect(self) -> None:
        self.view.zoom_changed.connect(self._on_zoom_changed)
        self.view.cursor_moved.connect(self._on_cursor_moved)
        self.view.tool_changed.connect(self._on_tool_changed)
        self.scene.selection_changed.connect(self._on_selection_changed)
        self.scene.content_changed.connect(self._on_content_changed)
        self.scene.layers_changed.connect(self._on_layers_changed)
        self.scene.undo_stack.indexChanged.connect(self._on_stack_changed)
        self.scene.text_edit_started.connect(lambda _item: self._set_edit_guard(True))
        self.scene.text_edit_finished.connect(lambda _item: self._set_edit_guard(False))
        self.layer_panel.request_import_image.connect(self.import_image_dialog)

    def _on_layers_changed(self) -> None:
        self._update_size_label()
        self._sync_layer_actions()

    def _sync_layer_actions(self) -> None:
        layer = self.layer_panel.current_layer()
        has = layer is not None
        index = self.scene.layer_index(layer) if has else -1
        count = len(self.scene.layers())
        self.act_layer_dup.setEnabled(has)
        self.act_layer_del.setEnabled(has)
        self.act_layer_rename.setEnabled(has)
        self.act_layer_visible.setEnabled(has)
        self.act_layer_lock.setEnabled(has)
        self.act_layer_up.setEnabled(has and index > 0)
        self.act_layer_down.setEnabled(has and 0 <= index < count - 1)
        self.act_layer_top.setEnabled(has and index > 0)
        self.act_layer_bottom.setEnabled(has and 0 <= index < count - 1)
        self.act_layer_reset_crop.setEnabled(
            has and layer.is_image and layer.image_item() is not None
        )

    # ============================================================== 状态
    def _set_edit_guard(self, editing: bool) -> None:
        """文字编辑时禁用会抢按键的动作（否则打字会触发工具切换/删除）。"""
        for action in self._guard_actions:
            action.setEnabled(not editing)

    def _on_zoom_changed(self, zoom: float) -> None:
        self.status_zoom.setText(f"{zoom * 100:.0f}%")

    def _on_cursor_moved(self, point: QPointF) -> None:
        self.status_pos.setText(f"{point.x():.0f}, {point.y():.0f}")

    def _on_tool_changed(self, name: str) -> None:
        action = self._tool_actions.get(name)
        if action is not None:
            action.setChecked(True)
        tool = self.view.tools().get(name)
        if tool is not None:
            self.status_hint.setText(tool.hint or tool.label)

    def _on_selection_changed(self) -> None:
        items = self.scene.selected_anno()
        if not items:
            self.status_sel.setText("未选中")
            self.property_panel.sync()
            self._sync_layer_actions()
            return
        if len(items) == 1:
            item = items[0]
            rect = item.local_rect()
            label = type_label(item.TYPE)
            if item.TYPE == "image":
                natural = item.natural_size()
                label += f" {natural[0]}×{natural[1]}"
            self.status_sel.setText(
                f"{label} {rect.width():.0f}×{rect.height():.0f}"
            )
        else:
            self.status_sel.setText(f"已选 {len(items)} 个")
        self.property_panel.sync()
        self._sync_layer_actions()

    def _on_content_changed(self) -> None:
        self._update_size_label()
        self._update_title()

    def _on_stack_changed(self) -> None:
        if not self._loading_document:
            self.scene.doc.modified = True
        self._update_title()
        # 撤销/重做会改掉对象的样式与几何，属性面板必须跟着刷新，
        # 否则面板会显示过期数值，用户再动一下别的控件就会把旧值写回去。
        self.property_panel.sync()
        self._sync_layer_actions()

    def _update_size_label(self) -> None:
        doc = self.scene.doc
        text = f"{doc.canvas_w}×{doc.canvas_h}"
        images = len(doc.image_layers())
        if images:
            text += f"  {images} 张图"
        text += f"  {len(doc.layers)} 个图层"
        if doc.is_cropped:
            crop = doc.crop
            text += f"  裁剪 {crop.width():.0f}×{crop.height():.0f}"
        self.status_size.setText(text)

    def _update_title(self) -> None:
        doc = self.scene.doc
        name = doc.display_name
        star = " *" if doc.modified else ""
        self.setWindowTitle(f"{name}{star} - {APP_NAME_CN} {APP_NAME} {APP_VERSION}")

    # ============================================================== 文档
    def _reset_document(self, width: int, height: int) -> None:
        doc = self.scene.doc
        self._loading_document = True
        try:
            self.scene.clear_layers()
            doc.bg_color = "#FFFFFF"
            doc.extra = {}
            doc.set_canvas(width, height)
            doc.reset_crop()
            doc.file_path = None
            doc.source_path = None
            self.scene.undo_stack.clear()
            # 任何文档都至少有一个标注图层：否则用户一进来画不了东西
            layer = Layer(id=new_layer_id(KIND_ANNOTATION), name="标注", kind=KIND_ANNOTATION)
            self.scene.add_layer(layer, 0)
            doc.active_layer_id = layer.id
            self.scene.set_selection([])
            self.scene.refresh_scene_rect()
            self.view.set_tool("select")
            self._on_tool_changed("select")
            self.layer_panel.rebuild()
        finally:
            self._loading_document = False
            doc.modified = False
        self._update_title()
        self._update_size_label()
        self._sync_layer_actions()

    def _confirm_discard(self) -> bool:
        if not self.scene.doc.modified:
            return True
        result = dialogs.ask_save_changes(
            self, "尚未保存", "当前工程有未保存的修改，要先保存吗？"
        )
        if result == QMessageBox.StandardButton.Save:
            return bool(self.save_project())
        return result == QMessageBox.StandardButton.Discard

    def new_document(self) -> None:
        if not self._confirm_discard():
            return
        self._reset_document(1280, 800)
        self.view.fit_to_window()
        self.statusBar().showMessage("已新建空白画布", 3000)

    # ---------------------------------------------------------- 打开 / 导入
    def open_project_dialog(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "打开工程", "", PROJECT_FILTER)
        if path:
            self.open_project(path)

    def open_project(self, path: str) -> None:
        try:
            doc, layers, _view_state = serialize.load_project(path)
        except Exception as error:  # noqa: BLE001 - 用户需要看到失败原因
            dialogs.error(self, "打开失败", f"无法打开工程文件：\n{error}")
            return
        self._loading_document = True
        try:
            self.scene.undo_stack.clear()
            self.scene.adopt_document(doc, layers)
            self.scene.set_selection([])
            self.view.fit_to_window()
            self.layer_panel.rebuild()
        finally:
            self._loading_document = False
            doc.modified = False
        self._update_title()
        self._update_size_label()
        self._sync_layer_actions()
        warning = getattr(doc, "missing_assets", None)
        if warning:
            self.statusBar().showMessage(
                f"已打开 {Path(path).name}，但有 {warning} 张图片的位图缺失", 8000
            )
        else:
            self.statusBar().showMessage(f"已打开 {Path(path).name}", 4000)

    def import_image_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "添加图片图层", "", IMAGE_OPEN_FILTER)
        if paths:
            self.add_image_layers(paths)

    def _load_image_file(self, path: str) -> None:
        """兼容旧调用：把一张图片加成一个图片图层。"""
        self.add_image_layers([path])

    # ---------------------------------------------------------- 图片图层
    def add_image_layers(self, paths: list[str], center: QPointF | None = None) -> list:
        """把若干图片文件各自加成图片图层（这是"多张图拼成一张"的入口）。"""
        loaded: list[tuple[str, object]] = []
        failed: list[str] = []
        for path in paths:
            image = read_image_with_orientation(path)
            if image.isNull():
                failed.append(Path(path).name)
                continue
            loaded.append((str(Path(path)), image))
        if not loaded:
            if failed:
                dialogs.warn(self, "导入失败", "无法读取图片：\n" + "\n".join(failed))
            return []
        layers = self.add_image_items(loaded, center=center)
        first = Path(loaded[0][0]).name
        message = (
            f"已添加 {len(layers)} 个图片图层：{first}"
            if len(layers) > 1
            else f"已添加图片图层 {first}"
        )
        if failed:
            message += f"（{len(failed)} 个文件读取失败）"
        self.statusBar().showMessage(message, 5000)
        self.view.fit_to_window()
        return layers

    def add_image_items(
        self, images: list[tuple[str, object]], center: QPointF | None = None
    ) -> list:
        """把已经读进内存的位图批量加成图层，自动排布并扩好画布。

        整批只有**一条**撤销记录（图层 + 画布尺寸一起进 CompoundCommand），
        所以"不小心拖进十张图"一次 Ctrl+Z 就能全身而退。
        """
        doc = self.scene.doc
        layers: list = []
        # 1) 先造图层与对象，并按"逐行铺开、超出画布就换行"排好位
        existing = [
            other
            for layer in doc.layers
            if layer.is_image
            for other in layer.items
            if getattr(other, "TYPE", "") == "image"
        ]
        if center is not None:
            cursor = QPointF(center)
            row_left = cursor.x()
            row_top = cursor.y()
        elif existing:
            row_left = max(other.scene_rect().right() for other in existing) + IMAGE_GAP
            row_top = min(other.scene_rect().top() for other in existing)
        else:
            row_left = row_top = 0.0
        widest = max(
            (float(image.width()) for _path, image in images), default=float(doc.canvas_w)
        )
        max_row = max(float(doc.canvas_w), row_left + widest)
        x, y, row_height = row_left, row_top, 0.0
        for source_path, image in images:
            item = ImageItem()
            item.set_source(image, source_name=Path(source_path).name if source_path else "")
            width = item.local_rect().width()
            height = item.local_rect().height()
            if x > row_left and (x + width) > max_row:
                x = row_left
                y += row_height + IMAGE_GAP
                row_height = 0.0
            item.setPos(x, y)
            x += width + IMAGE_GAP
            row_height = max(row_height, height)
            layer = Layer(
                id=new_layer_id(KIND_IMAGE),
                name=self.scene.unique_layer_name(
                    Path(source_path).stem if source_path else "图片"
                ),
                kind=KIND_IMAGE,
            )
            layer.items.append(item)
            layers.append(layer)
        if not layers:
            return []

        # 2) 画布要多大：空白文档直接跟随第一张图片，否则取并集
        empty_doc = not existing and not self.scene.annotation_items()
        content: QRectF | None = None
        if not empty_doc:
            content = QRectF(0.0, 0.0, float(doc.canvas_w), float(doc.canvas_h))
        for layer in layers:
            for item in layer.items:
                rect = item.scene_rect()
                content = rect if content is None else content.united(rect)
        if content is None or content.width() < 1.0 or content.height() < 1.0:
            content = QRectF(0.0, 0.0, 1.0, 1.0)
        old_state = (doc.canvas_w, doc.canvas_h, QRectF(doc.crop))
        new_w = max(1, int(math.ceil(content.right())))
        new_h = max(1, int(math.ceil(content.bottom())))
        was_full = not doc.is_cropped
        new_crop = QRectF(0.0, 0.0, float(new_w), float(new_h)) if was_full else QRectF(doc.crop)
        new_state = (new_w, new_h, new_crop)

        commands: list = []
        if new_state != old_state:
            commands.append(
                DocPropCommand(self._apply_canvas_state, old_state, new_state, "调整画布尺寸")
            )
        index = self._image_layer_index()
        for offset, layer in enumerate(layers):
            commands.append(
                AddLayerCommand(self.scene, layer, index + offset, "添加图片图层")
            )
        self.view.push_command(
            commands[0] if len(commands) == 1 else CompoundCommand(commands, "添加图片图层")
        )
        if images and images[0][0]:
            doc.source_path = images[0][0]
        last = layers[-1]
        # 新图片立刻被选中（马上就能拖/缩放），但活动图层换回标注图层：
        # 面板高亮的那一行 = 下次画标注会去的地方，不这么做标注会偷偷混进照片图层。
        self.scene.set_selection(list(last.items))
        target = doc.top_annotation_layer() or doc.default_annotation_layer()
        self.scene.set_active_layer(target, sync_selection=False)
        self.scene.refresh_scene_rect()
        self.view.refresh()
        self._update_size_label()
        self._update_title()
        return layers

    def _apply_canvas_state(self, state) -> None:
        """画布尺寸 + 导出范围的原子写入（撤销命令的 setter）。"""
        doc = self.scene.doc
        width, height, crop = state
        doc.canvas_w = max(1, int(width))
        doc.canvas_h = max(1, int(height))
        doc.crop = QRectF(crop) if crop is not None else doc.canvas_rect()
        doc.clamp_crop()
        self.scene.refresh_scene_rect()
        self.view.refresh()
        self._update_size_label()

    def _image_layer_index(self) -> int:
        """新图片插到所有图片图层的最上面，但在标注图层下面。

        这样"照片在底、标注在上"是默认顺序，符合标注工具的心智模型；
        想改随时能在图层面板里拖。
        """
        index = 0
        for layer in self.scene.layers():
            if layer.is_image:
                break
            index += 1
        return index

    def add_image_layer(self, image, source: str | None = None) -> list:
        """把一张**已经在内存里**的位图加成一个图片图层（给脚本/测试用的便捷入口）。

        界面上用户走的是「添加图片图层…」/ 拖入 / 粘贴，最终都汇到
        :meth:`add_image_items`；这里只是省去"先存成文件再读"的一步。
        """
        layers = self.add_image_items([(source or "", image)])
        self.view.fit_to_window()
        return layers

    # ---------------------------------------------------------- 保存 / 导出
    def save_project(self, save_as: bool = False) -> bool:
        doc = self.scene.doc
        path = doc.file_path
        if save_as or not path:
            suggested = path or str(Path.home() / f"标注工程{PROJECT_EXT}")
            path, _ = QFileDialog.getSaveFileName(
                self, "保存工程", suggested, PROJECT_FILTER
            )
            if not path:
                return False
            if not path.lower().endswith(PROJECT_EXT):
                path += PROJECT_EXT
        try:
            serialize.save_project(
                path,
                doc,
                self.scene.layers(),
                view_state={"zoom": self.view.zoom()},
                scene=self.scene,
            )
        except Exception as error:  # noqa: BLE001
            dialogs.error(self, "保存失败", f"无法保存工程文件：\n{error}")
            return False
        doc.file_path = path
        doc.modified = False
        self._update_title()
        self.statusBar().showMessage(f"已保存 {Path(path).name}", 4000)
        return True

    def export_image(self) -> None:
        doc = self.scene.doc
        dialog = ExportDialog(doc, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        suffix = dialog.suffix()
        base = self.scene.doc.display_name
        if base == "无标题":
            base = "标注"
        suggested = str(Path.home() / f"{base}{suffix}")
        selected, _ = QFileDialog.getSaveFileName(
            self, "导出图片", suggested, EXPORT_FILTER
        )
        if not selected:
            return
        if not selected.lower().endswith(suffix):
            selected += suffix
        try:
            ok = export_document(
                doc,
                self.scene,
                selected,
                scale=dialog.scale(),
                quality=dialog.quality(),
            )
        except Exception as error:  # noqa: BLE001
            dialogs.error(self, "导出失败", f"无法导出图片：\n{error}")
            return
        if not ok:
            dialogs.error(self, "导出失败", "写入文件失败，请检查路径与权限。")
            return
        self.statusBar().showMessage(f"已导出 {Path(selected).name}", 5000)

    def quick_copy_image(self) -> None:
        """把当前画面按 PNG 放进剪贴板，直接就能粘到聊天窗口/文档里。

        同时塞两份数据：`setImageData` 让 Windows 应用拿到 CF_DIB，
        额外的 `image/png` 让偏爱 PNG 的程序拿到无损原图。
        """
        doc = self.scene.doc
        image = render_document(doc, self.scene, scale=1.0)
        if image.isNull():
            return
        mime = QMimeData()
        mime.setImageData(image)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if image.save(buffer, "PNG"):
            mime.setData("image/png", QByteArray(buffer.data()))
        buffer.close()
        QApplication.clipboard().setMimeData(mime)
        self.statusBar().showMessage(
            f"已复制为图片（PNG） {image.width()}×{image.height()}", 4000
        )

    def reset_crop(self) -> None:
        doc = self.scene.doc
        before = QRectF(doc.crop)
        after = doc.canvas_rect()
        if before == after:
            return
        self.view.push_command(
            DocPropCommand(lambda r: self.view.set_crop(r), before, after, "恢复完整画面")
        )

    # ---------------------------------------------------------- 画布
    def set_canvas_color(self, color: str) -> None:
        doc = self.scene.doc
        if doc.bg_color == color:
            return

        def apply(value: str) -> None:
            doc.bg_color = value
            self.view.refresh()

        self.view.push_command(DocPropCommand(apply, doc.bg_color, color, "画布背景色"))

    def set_canvas_size_dialog(self) -> None:
        doc = self.scene.doc
        dialog = dialogs.CanvasSizeDialog(
            doc.canvas_w, doc.canvas_h, self, content_rect=self.scene.itemsBoundingRect()
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        width, height = dialog.size()
        before = (doc.canvas_w, doc.canvas_h, QRectF(doc.crop))
        after = (int(width), int(height), QRectF(0, 0, float(width), float(height)))
        if before == after:
            return
        self.view.push_command(
            DocPropCommand(self._apply_canvas_state, before, after, "设置画布大小")
        )
        self.statusBar().showMessage(f"画布已设为 {width}×{height}", 4000)

    def fit_canvas_to_content(self, margin: float = 24.0) -> None:
        """把所有内容收进画布，并消除四周的多余空白。"""
        scene = self.scene
        items = scene.anno_items()
        if not items:
            self.statusBar().showMessage("画布上还没有内容", 3000)
            return
        rect = scene.itemsBoundingRect()
        if rect.isNull() or rect.width() < 1 or rect.height() < 1:
            return
        dx = margin - rect.left()
        dy = margin - rect.top()
        width = int(math.ceil(rect.width() + margin * 2))
        height = int(math.ceil(rect.height() + margin * 2))
        doc = scene.doc
        commands: list = []
        if abs(dx) > 0.01 or abs(dy) > 0.01:
            old = [item.to_dict() for item in items]
            for item in items:
                item.moveBy(dx, dy)
            new = [item.to_dict() for item in items]
            commands.append(ModifyCommand(items, old, new, "适应内容"))
        before = (doc.canvas_w, doc.canvas_h, QRectF(doc.crop))
        after = (width, height, QRectF(0.0, 0.0, float(width), float(height)))
        if before != after:
            commands.append(
                DocPropCommand(self._apply_canvas_state, before, after, "适应内容")
            )
        if not commands:
            return
        self.view.push_command(
            commands[0] if len(commands) == 1 else CompoundCommand(commands, "画布适应内容")
        )
        self.view.fit_to_window()
        self.statusBar().showMessage(f"画布已适应内容：{width}×{height}", 4000)

    def arrange_image_layers(self, columns: int | None = None, gap: float = 16.0) -> None:
        """把可见的图片图层按网格重新排布、统一缩放，并重设画布。

        排布规则（刻意做得可预测，不做"智能"排版）：
        * 网格列数默认取 ``ceil(sqrt(张数))``
        * 单元格 = 各图当前显示尺寸的最大值（保留用户已经调好的相对大小）
        * 每张图等比缩放**放进**单元格（不放大，只缩小），在格内居中
        * 顺序 = 图层面板顺序（最上面的图层排在左上角第一个格子）
        """
        scene = self.scene
        images = [
            layer.image_item()
            for layer in scene.layers()
            if layer.is_image and layer.visible and layer.image_item() is not None
        ]
        images = [item for item in images if item.has_source()]
        if len(images) < 2:
            self.statusBar().showMessage("至少要有两张可见图片才能自动排列", 4000)
            return
        count = len(images)
        columns = max(1, int(columns or math.ceil(math.sqrt(count))))
        rows = int(math.ceil(count / columns))
        cell_w = max(item.local_rect().width() for item in images)
        cell_h = max(item.local_rect().height() for item in images)
        width = int(math.ceil(columns * cell_w + (columns + 1) * gap))
        height = int(math.ceil(rows * cell_h + (rows + 1) * gap))

        old = [item.to_dict() for item in images]
        for index, item in enumerate(images):
            row, column = divmod(index, columns)
            kx, ky = item.pixel_scale()
            scale = min(1.0, cell_w / max(1.0, item.local_rect().width()),
                        cell_h / max(1.0, item.local_rect().height()))
            item.set_display_scale(kx * scale, ky * scale)
            rect = item.local_rect()
            center = QPointF(
                gap + column * (cell_w + gap) + cell_w / 2.0,
                gap + row * (cell_h + gap) + cell_h / 2.0,
            )
            item.setPos(0.0, 0.0)
            delta = center - item.mapToScene(rect.center())
            item.moveBy(delta.x(), delta.y())
        new = [item.to_dict() for item in images]

        doc = scene.doc
        before = (doc.canvas_w, doc.canvas_h, QRectF(doc.crop))
        after = (width, height, QRectF(0.0, 0.0, float(width), float(height)))
        commands = [ModifyCommand(images, old, new, "自动排列图片")]
        if before != after:
            commands.append(
                DocPropCommand(self._apply_canvas_state, before, after, "自动排列图片")
            )
        self.view.push_command(CompoundCommand(commands, "自动排列图片图层"))
        self.view.fit_to_window()
        self.statusBar().showMessage(
            f"已按 {columns} 列排列 {count} 张图片，画布 {width}×{height}", 5000
        )

    # ---------------------------------------------------------- 剪贴板
    def copy_selection(self) -> None:
        items = [
            item
            for item in self.scene.selected_anno()
            if getattr(item, "TYPE", "") != "image"
        ]
        if not items:
            if self.scene.selected_anno():
                # 图片的像素不在剪贴板格式里（几百 MB 的位图也不适合塞进去），
                # 想复制一张图片请用「图层 → 复制图层」。
                self.statusBar().showMessage(
                    "图片图层请用「图层 → 复制图层」(Ctrl+J)；Ctrl+C 复制整幅成图", 5000
                )
                return
            # 没选中任何对象时，Ctrl+C 直接复制整幅图片。
            # 一是对齐微信截图 / ShareX 的习惯，二是绕开"中文输入法吞掉 Ctrl+Shift"的问题。
            self.quick_copy_image()
            return
        payload = {
            "type": "drawx/clipboard",
            "objects": [item.to_dict() for item in items],
        }
        mime = QMimeData()
        mime.setData(
            OBJECT_MIME,
            QByteArray(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
        )
        QApplication.clipboard().setMimeData(mime)
        self.statusBar().showMessage(f"已复制 {len(items)} 个标注对象", 2500)

    def cut_selection(self) -> None:
        items = self.scene.selected_anno()
        if not items:
            return
        plain = [item for item in items if getattr(item, "TYPE", "") != "image"]
        if plain:
            self.copy_selection()
        self.view.delete_items(items)

    def paste(self) -> None:
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        if mime is not None and mime.hasFormat(OBJECT_MIME):
            raw = bytes(mime.data(OBJECT_MIME))
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:  # noqa: BLE001
                return
            data_list = []
            for data in payload.get("objects", []):
                data = dict(data)
                data["id"] = new_id()
                data["x"] = float(data.get("x", 0.0)) + 18.0
                data["y"] = float(data.get("y", 0.0)) + 18.0
                data_list.append(data)
            if data_list:
                self.view.push_command(
                    AddItemsCommand(self.scene, data_list, "粘贴标注")
                )
                self.statusBar().showMessage(f"已粘贴 {len(data_list)} 个标注对象", 2500)
            return

        image = clipboard.image()
        if image is not None and not image.isNull():
            self.add_image_items([("", image)], center=None)
            self.statusBar().showMessage(
                f"已把剪贴板图片作为新图层添加 {image.width()}×{image.height()}", 4000
            )
            return
        self.statusBar().showMessage("剪贴板里没有图片或标注对象", 2500)

    # ---------------------------------------------------------- 拖放
    def dragEnterEvent(self, event) -> None:
        mime = event.mimeData()
        if mime.hasUrls() and any(
            url.isLocalFile() and self._known_suffix(url.toLocalFile())
            for url in mime.urls()
        ):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        self.handle_dropped_paths(
            [
                url.toLocalFile()
                for url in event.mimeData().urls()
                if url.isLocalFile() and self._known_suffix(url.toLocalFile())
            ]
        )
        event.acceptProposedAction()

    def handle_dropped_paths(self, paths: list[str]) -> None:
        """拖进来的文件：图片**全部**加成图片图层，.drawx 直接打开工程。

        v0.1 只处理第一个文件（"一次只能处理一个"），多图拼合的需求一上来这条就不成立了。
        """
        if not paths:
            return
        projects = [p for p in paths if p.lower().endswith(PROJECT_EXT)]
        images = [
            p for p in paths if Path(p).suffix.lower() in IMAGE_SUFFIXES
        ]
        if projects:
            if self._confirm_discard():
                self.open_project(projects[0])
            if len(projects) > 1:
                self.statusBar().showMessage(
                    f"一次只打开一个工程，已打开 {Path(projects[0]).name}", 5000
                )
        if images:
            self.add_image_layers(images)
        elif not projects:
            self.statusBar().showMessage("没有可处理的文件", 3000)

    @staticmethod
    def _known_suffix(path: str) -> bool:
        suffix = Path(path).suffix.lower()
        return suffix in IMAGE_SUFFIXES or suffix == PROJECT_EXT

    # ---------------------------------------------------------- 其他
    def _deselect(self) -> None:
        self.scene.set_selection([])
        self.view.refresh()

    def show_shortcuts(self) -> None:
        dialogs.info(
            self,
            "快捷键",
            "<b>工具</b><br>"
            "V 选择　C 裁剪　R 矩形　O 椭圆　U 圆角矩形<br>"
            "L 直线　A 箭头　P 画笔　H 高亮　T 文字<br>"
            "B 马赛克　M 模糊<br><br>"
            "<b>编辑</b><br>"
            "Ctrl+Z / Ctrl+Y 撤销 / 重做　Ctrl+A 全选　Ctrl+D 取消选择<br>"
            "Del 删除选中　Ctrl+C/X/V 复制 / 剪切 / 粘贴<br>"
            "方向键微调 1px，Shift+方向键 10px<br>"
            "Shift 加选 / 等比 / 锁定 45°　Alt 从中心画 / 拖动复制　Ctrl 点选切换<br>"
            "双击文字对象进入编辑，Esc 结束<br><br>"
            "<b>图层</b><br>"
            "Ctrl+I 添加图片图层（可多选）　Ctrl+Shift+N 新建标注图层<br>"
            "Ctrl+J 复制图层　Ctrl+[ / Ctrl+] 下移 / 上移一层　F2 重命名图层<br>"
            "面板里点眼睛 = 显隐，点锁 = 锁定（锁定后画布上点不动它）<br>"
            "拖动图层行可以调整顺序<br><br>"
            "<b>画布</b><br>"
            "F9 画布适应内容　「画布 → 自动排列图片图层」把多张图铺成网格<br>"
            "选中一张图片后按 C，裁的就是这张图片（非破坏，可恢复）<br><br>"
            "<b>视图</b><br>"
            "Ctrl+滚轮 缩放　空格拖动 或 中键拖动 平移<br>"
            "Ctrl+0 适应窗口　Ctrl+1 实际大小<br><br>"
            "<b>文件</b><br>"
            "Ctrl+N 新建　Ctrl+O 打开　Ctrl+S 保存　F12 另存为　Ctrl+E 导出<br>"
            "Ctrl+Alt+C 快速复制为图片（没选中对象时 Ctrl+C 同效）<br><br>"
            "<i>提示：部分中文输入法会拦截 Ctrl+Shift 组合键，所以另存为额外提供了 F12，"
            "新建标注图层额外提供了 Ctrl+Alt+N。</i>",
        )

    def show_about(self) -> None:
        dialogs.about(
            self,
            "关于",
            f"<b>{APP_NAME_CN} {APP_NAME}</b> v{APP_VERSION}<br><br>"
            "轻量图片标注工具：一张画布上可以放多张图片（各是一个图片图层），"
            "每张图都能移动、缩放、旋转、非破坏裁剪；标注是矢量对象，"
            "随时可选中、改样式、改层级、撤销，并保存成 .drawx 工程文件。<br><br>"
            "定位：微信截图的编辑手感 + 工程文件可再编辑 + 多图拼合，"
            "但没有 Photoshop 的重量。",
        )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # 启动后把焦点给画布，否则用户不点一下画布，单字母工具快捷键全都无效
        self.view.setFocus(Qt.FocusReason.OtherFocusReason)
        if not self._fitted_on_show:
            # 构造时窗口还没布局，视口尺寸是假的，缩放要等真正显示出来再算
            self._fitted_on_show = True
            QTimer.singleShot(0, self.view.fit_to_window)

    def closeEvent(self, event) -> None:
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()
