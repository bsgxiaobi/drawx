"""应用入口：QApplication、深色主题、高 DPI、中文翻译与命令行参数。"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, Qt, QTranslator
from PySide6.QtWidgets import QApplication

from .const import APP_NAME, APP_VERSION, ORG_NAME
from .ui.appicon import app_icon
from .ui.main_window import MainWindow
from .ui.style import DarkStyle

STYLESHEET = """
QWidget { background-color: #26262a; color: #e6e6ea; font-size: 13px; }
QMainWindow::separator { background: #33333a; width: 1px; height: 1px; }

QToolBar { background: #2c2c31; border: none; padding: 4px; spacing: 4px; }
QToolBar::separator { background: #3d3d45; width: 1px; margin: 4px 6px; }

QToolButton { background: transparent; border: 1px solid transparent;
              border-radius: 5px; padding: 4px; }
QToolButton:hover { background: #3a3a43; }
QToolButton:pressed { background: #45454f; }
QToolButton:checked { background: #2f5fa8; border-color: #4d94ff; }
QToolButton:disabled { color: #6b6b74; }

QMenuBar { background: #2c2c31; }
QMenuBar::item { padding: 5px 10px; background: transparent; }
QMenuBar::item:selected { background: #3a3a43; }
QMenu { background: #2f2f35; border: 1px solid #45454f; padding: 4px; }
QMenu::item { padding: 5px 24px 5px 18px; border-radius: 4px; }
QMenu::item:selected { background: #2f5fa8; }
QMenu::separator { height: 1px; background: #45454f; margin: 4px 8px; }

QDockWidget { titlebar-close-icon: none; }
QDockWidget::title { background: #2c2c31; padding: 6px 8px; border-bottom: 1px solid #3d3d45; }

QGroupBox { border: 1px solid #3d3d45; border-radius: 6px; margin-top: 14px;
            padding: 8px 6px 6px 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px;
                   color: #9a9aa4; }
QGroupBox:disabled { color: #6b6b74; }

QSlider::groove:horizontal { height: 4px; background: #45454f; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #4d94ff; border-radius: 2px; }
QSlider::handle:horizontal { background: #e6e6ea; width: 12px; height: 12px;
                             margin: -5px 0; border-radius: 6px; }

QComboBox, QSpinBox { background: #33333a; border: 1px solid #45454f;
                      border-radius: 4px; padding: 3px 6px; }
QComboBox:hover, QSpinBox:hover { border-color: #4d94ff; }
QComboBox QAbstractItemView { background: #2f2f35; border: 1px solid #45454f;
                              selection-background-color: #2f5fa8; padding: 2px; }
/* 注意：千万不要在这里给 QComboBox::drop-down / QSpinBox::up-button 写规则。
   一旦写了，Qt 就改由样式表自己绘制该子控件，而没有指定 image 时它什么都不画，
   下拉箭头和微调箭头会直接消失。箭头交给 ui/style.py 的 DarkStyle 画。 */

QPushButton { background: #33333a; border: 1px solid #45454f; border-radius: 4px;
              padding: 4px 10px; }
QPushButton:hover { border-color: #4d94ff; }
QPushButton:pressed { background: #3d3d45; }

QCheckBox { spacing: 6px; }
QStatusBar { background: #2c2c31; border-top: 1px solid #3d3d45; }
QStatusBar QLabel { background: transparent; }
QScrollArea { border: none; }
QScrollBar:vertical { background: #26262a; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #4a4a55; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #5a5a66; }
QScrollBar:horizontal { background: #26262a; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #4a4a55; border-radius: 5px; min-width: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QToolTip { background: #1f1f24; color: #e6e6ea; border: 1px solid #45454f; padding: 4px; }
"""


#: Qt 自带翻译的候选目录。打包成 onefile 之后 `QLibraryInfo` 报的路径不一定是
#: 真实解包路径，所以多试几个地方（这个坑很常见）。
def translation_dirs() -> list[str]:
    candidates: list[str] = []
    try:
        candidates.append(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    except Exception:  # noqa: BLE001
        pass
    try:
        import PySide6

        candidates.append(str(Path(PySide6.__file__).resolve().parent / "translations"))
    except Exception:  # noqa: BLE001
        pass
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidates.append(str(Path(bundle) / "PySide6" / "translations"))
        candidates.append(str(Path(bundle) / "translations"))
    seen: list[str] = []
    for item in candidates:
        if item and item not in seen and Path(item).is_dir():
            seen.append(item)
    return seen


def install_translations(app: QApplication, language: str = "zh_CN") -> bool:
    """装上 Qt 自带的中文翻译，返回是否装成功。

    **不装的话，Qt 自己造的那些按钮全是英文**：另存为提示里的 `Save / Discard /
    Cancel`、各种提示框的 `OK`、画布上右键文字编辑菜单的 `Cut / Copy / Paste` ——
    界面文案明明全中文，就这几个按钮露英文，用户一眼就能看见（用户反馈过）。
    """
    translator = QTranslator(app)
    for folder in translation_dirs():
        if translator.load(f"qtbase_{language}", folder):
            app.installTranslator(translator)
            # 必须留个引用：QTranslator 被 GC 掉之后翻译就失效了
            app.qt_translator = translator  # type: ignore[attr-defined]
            return True
    return False


def create_application(argv: list[str] | None = None) -> QApplication:
    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName(ORG_NAME)
    QApplication.setApplicationVersion(APP_VERSION)
    # 高 DPI：不做取整，避免 125%/150% 缩放下手柄错位
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv if argv is not None else sys.argv)
    # 先落 Fusion 再套一层代理样式：代理样式负责把下拉/微调箭头画成浅色雪佛龙
    app.setStyle("Fusion")
    app.setStyle(DarkStyle("Fusion"))
    app.setStyleSheet(STYLESHEET)
    # 标准对话框按钮的中文化（详见 install_translations 的注释）
    install_translations(app)
    # 窗口标题栏、任务栏、Alt+Tab 的图标。
    # PyInstaller 的 --icon 只改了 exe 的文件图标，窗口图标必须在这里显式设置，
    # 否则 Qt 会用它自己的默认图标（用户看到的就是左上角/任务栏没有图标）。
    app.setWindowIcon(app_icon())
    return app


def main(argv: list[str] | None = None) -> int:
    arguments = list(argv if argv is not None else sys.argv)
    app = create_application(arguments)
    window = MainWindow()
    window.show()

    if "--selftest" in arguments:
        # 打包成 exe 后没有控制台，自检结果写进 JSON 文件
        from PySide6.QtCore import QTimer

        from .selftest import run as run_selftest

        index = arguments.index("--selftest")
        out_path = (
            arguments[index + 1]
            if len(arguments) > index + 1 and not arguments[index + 1].startswith("-")
            else "drawx_selftest.json"
        )

        def finish() -> None:
            code = run_selftest(window, out_path)
            app.exit(code)

        QTimer.singleShot(400, finish)
        return app.exec()

    for argument in arguments[1:]:
        path = Path(argument)
        if not path.exists():
            continue
        if path.suffix.lower() == ".drawx":
            window.open_project(str(path))
        elif path.suffix.lower() in {
            ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"
        }:
            window._load_image_file(str(path))
        break

    return app.exec()
