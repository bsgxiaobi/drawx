"""全局常量与默认样式。"""

APP_NAME = "DrawX"
APP_NAME_CN = "标注工坊"
APP_VERSION = "0.2.0"
ORG_NAME = "DrawX"

PROJECT_EXT = ".drawx"
PROJECT_FILTER = "DrawX 工程 (*.drawx)"
IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff",
}
IMAGE_OPEN_FILTER = (
    "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff);;所有文件 (*.*)"
)
EXPORT_FILTER = (
    "PNG 图片 (*.png);;JPEG 图片 (*.jpg);;WebP 图片 (*.webp);;BMP 图片 (*.bmp)"
)

FORMAT_NAME = "drawx"
#: 2 = 图层化（背景位图升级为图片图层，资源按 assetId 分开存放）
FORMAT_VERSION = 2

MIN_ZOOM = 0.05
MAX_ZOOM = 16.0
UNDO_LIMIT = 100

# 视图层尺寸（单位：视口像素，不随缩放变化）
HANDLE_SIZE = 9
ROTATE_HANDLE_DIST = 28
HIT_TOLERANCE = 6

# 配色
COLOR_VIEW_BG = "#3c3c40"
COLOR_CANVAS_EDGE = "#7a7a80"
COLOR_ACCENT = "#2f7cf6"
COLOR_HANDLE = "#ffffff"
COLOR_SNAP = "#ff2d95"
COLOR_DIM = (0, 0, 0, 110)

# 调色板（属性面板色块）
PALETTE = [
    "#FF3B30", "#FF9500", "#FFCC00", "#34C759",
    "#00C7BE", "#2F7CF6", "#5856D6", "#AF52DE",
    "#FFFFFF", "#C7C7CC", "#8E8E93", "#1C1C1E",
]
