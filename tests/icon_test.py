"""应用图标测试：窗口图标 / 任务栏图标必须真的设置上，且各尺寸都清晰。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from drawx.app import create_application  # noqa: E402
from drawx.ui.appicon import ICON_SIZES, app_icon, draw_app_icon  # noqa: E402
from drawx.ui.main_window import MainWindow  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def check(condition: bool, message: str) -> None:
    RESULTS.append((bool(condition), message))
    print(("  PASS  " if condition else "  FAIL  ") + message)


def count_colors(image, tolerance: int = 60) -> dict[str, int]:
    counts = {"red": 0, "blue": 0, "white": 0, "opaque": 0}
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() < 40:
                continue
            counts["opaque"] += 1
            if color.red() > 170 and color.green() < 110 and color.blue() < 110:
                counts["red"] += 1
            elif color.blue() > 110 and color.blue() > color.red() + 30:
                counts["blue"] += 1
            elif color.red() > 225 and color.green() > 225 and color.blue() > 225:
                counts["white"] += 1
    return counts


def main() -> int:
    app = create_application([])

    print("\n[1] QApplication 的窗口图标已设置（标题栏 / 任务栏都用它）")
    icon = QApplication.windowIcon()
    check(not icon.isNull(), "QApplication.windowIcon() 不为空")
    sizes = sorted(size.width() for size in icon.availableSizes())
    print(f"  可用尺寸: {sizes}")
    for size in (16, 32, 256):
        check(size in sizes, f"包含 {size}×{size}（任务栏取 32/16，Alt+Tab 取大图）")

    print("\n[2] 每个尺寸都画出了内容且颜色正确")
    for size in ICON_SIZES:
        image = draw_app_icon(size)
        counts = count_colors(image)
        ok = counts["opaque"] > size * size * 0.5 and counts["red"] > 3 and counts["blue"] > 10
        check(
            ok,
            f"{size:>3}px: 不透明 {counts['opaque']:>5}，蓝 {counts['blue']:>5}，红 {counts['red']:>4}"
            + ("" if size < 32 else f"，白 {counts['white']}"),
        )

    print("\n[3] 小尺寸走简化版（省掉相框，箭头才不会糊）")
    small = count_colors(draw_app_icon(16))
    large = count_colors(draw_app_icon(64))
    check(small["white"] == 0, "16px 不含白色相框（简化版）")
    check(large["white"] > 30, f"64px 含白色相框（{large['white']} 像素）")

    print("\n[4] 主窗口自身也带图标")
    window = MainWindow()
    window.show()
    app.processEvents()
    check(not window.windowIcon().isNull(), "MainWindow.windowIcon() 不为空")
    check(
        not window.windowIcon().pixmap(32, 32).isNull(),
        "能取出 32×32 位图",
    )

    print("\n[5] 缓存：多次调用返回同一个 QIcon 实例")
    check(app_icon() is app_icon(), "app_icon() 做了缓存")

    out = ROOT / "build" / "smoke" / "icon_check.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet = draw_app_icon(256)
    sheet.save(str(out))
    check(out.exists(), f"图标预览已保存 -> {out}")

    print("\n[6] 弧形箭头的参数约束（改图标时不能破，会画歪）")
    import math

    from drawx.ui.icons import CURVED_ARROW, arc_local_radius, tool_icon

    cfg = CURVED_ARROW
    size = 22.0
    head = cfg["head"] * size
    spread = math.radians(cfg["spread"])
    base_width = 2.0 * head * math.sin(spread)
    stroke = cfg["pen"] * size
    # 关键：要用**收尾处的曲率半径**，不能用椭圆平均半径。
    # 椭圆越靠近左右两端曲率半径越小（175° 处只有平均半径的 2/3），
    # 老参数（head .16 / end 175°）就是被这条漏判，箭头侧边一直戳出一小截线。
    radius = arc_local_radius(cfg, cfg["end"]) * size
    deviation = math.degrees(head / radius) if radius else 999.0
    print(
        f"  22px 下：收尾处曲率半径 {radius:.1f}  箭头长 {head:.1f}"
        f"  根部宽 {base_width:.1f}  线宽 {stroke:.1f}"
        f"  弧线在箭头长度内的偏转 {deviation:.0f}°"
    )
    check(
        deviation <= cfg["spread"] * 1.05,
        f"弧线在箭头长度内偏转 {deviation:.0f}° ≤ 张角 {cfg['spread']:.0f}°"
        " —— 否则弧线会从三角形两侧戳出来，看着像断开",
    )
    check(
        base_width >= stroke * 1.8,
        f"箭头根部宽({base_width:.1f}) ≥ 线宽×1.8({stroke * 1.8:.1f}) —— 否则读不出箭头感",
    )
    check(cfg["end"] <= 180.0, f"收尾角 {cfg['end']}° ≤ 180° —— 越过之后切线会往里勾")
    check(
        cfg["end"] <= 150.0,
        f"收尾角 {cfg['end']}° ≤ 150° —— 再靠后切线几乎垂直向下，箭头会朝里勾（用户反馈过）",
    )
    check(0.04 <= cfg["pen"] <= 0.10, f"线宽比例 {cfg['pen']} 在合理区间")
    # bias 的几何上限是张角本身：只要 bias < spread，弧线就还是从三角形的"底边"
    # 进入（而不是从两侧戳出来）。留一半余量是为了让三角形看着仍"长在弧线末端"。
    check(
        0.0 <= cfg["bias"] <= cfg["spread"] * 0.65,
        f"箭头外偏角 {cfg['bias']}° 在 0~张角×0.65({cfg['spread'] * 0.65:.0f}°) 之间"
        " —— 超过张角就从三角形侧面穿出去了",
    )

    # 箭头方向必须"朝外"：用真实几何算一遍，箭头指向与正左方（undo）/正右方（redo）
    # 的夹角要小。老参数是 48°（几乎是朝下的），用户反馈"太朝里"。
    def head_direction(to_left: bool) -> float:
        rxp = cfg["w"] / 2.0
        ryp = cfg["h"] / 2.0
        end = cfg["end"] if to_left else 180.0 - cfg["end"]

        def point(deg):
            rad = math.radians(deg)
            return (rxp * math.cos(rad), -ryp * math.sin(rad))

        tip = point(end)
        prev = point(end - 8.0 if to_left else end + 8.0)
        angle = math.degrees(math.atan2(tip[1] - prev[1], tip[0] - prev[0]))
        return angle + (cfg["bias"] if to_left else -cfg["bias"])

    for to_left, label, target in ((True, "撤销", 180.0), (False, "重做", 0.0)):
        angle = head_direction(to_left)
        offset = abs(angle - target)
        check(
            offset <= 30.0,
            f"{label}箭头偏离正{'左' if to_left else '右'}方 {offset:.0f}° ≤ 30°"
            f"（实测 {angle:.0f}°）—— 否则箭头是往弧线内侧勾的",
        )

    print("\n[7] 每个图标都必须画满且居中（把漏乘 size / 画歪 变成会失败的测试）")
    import inspect
    import re

    def ink_box(name: str, box: int = 22, scale: int = 8):
        """返回图标"墨迹"的包围盒（以逻辑像素为单位）。"""
        image = tool_icon(name, box * scale).pixmap(box * scale, box * scale).toImage()
        xs, ys = [], []
        for y in range(image.height()):
            for x in range(image.width()):
                if image.pixelColor(x, y).alpha() > 40:
                    xs.append(x)
                    ys.append(y)
        if not xs:
            return None
        factor = float(scale)
        return (
            min(xs) / factor,
            min(ys) / factor,
            (max(xs) + 1) / factor,
            (max(ys) + 1) / factor,
        )

    # 直接从 tool_icon 的源码里把所有图标名抠出来（`name == "x"` 与 `name in ("x","y")`
    # 两种写法都要认）：这样以后新增图标会自动被这条检查覆盖，不用维护第二份清单。
    source = inspect.getsource(tool_icon)
    names = set(re.findall(r'name == "([a-z_]+)"', source))
    for group in re.findall(r"name in \(([^)]*)\)", source):
        names.update(re.findall(r'"([a-z_]+)"', group))
    names = sorted(names)
    check(len(names) >= 26, f"扫描到 {len(names)} 个图标：{names}")
    for name in names:
        box = ink_box(name)
        if box is None:
            check(False, f"{name} 图标是空的")
            continue
        width, height = box[2] - box[0], box[3] - box[1]
        cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
        # 漏乘 size 会让整个图形缩成 1 像素小点；偏心会让工具栏看起来高低不齐
        check(
            width >= 8.0 and height >= 4.0,
            f"{name} 墨迹尺寸 {width:.1f}×{height:.1f} ≥ 8×4（22px 按钮里的下限）",
        )
        check(
            abs(cx - 11.0) <= 2.0 and abs(cy - 11.0) <= 2.0,
            f"{name} 墨迹重心 ({cx:.1f},{cy:.1f}) 接近按钮中心 (11,11)",
        )
    # undo/redo 是镜像，两者重心必须关于中心对称
    undo_box, redo_box = ink_box("undo"), ink_box("redo")
    if undo_box and redo_box:
        undo_cx = (undo_box[0] + undo_box[2]) / 2.0
        redo_cx = (redo_box[0] + redo_box[2]) / 2.0
        check(
            abs((undo_cx + redo_cx) / 2.0 - 11.0) <= 0.6,
            f"undo/redo 重心关于中心对称（{(undo_cx + redo_cx) / 2.0:.2f}）",
        )
        check(
            abs(undo_box[3] - redo_box[3]) <= 1.5,
            f"undo/redo 视觉高度一致（{undo_box[3] - undo_box[1]:.1f} vs"
            f" {redo_box[3] - redo_box[1]:.1f}）",
        )

    print("\n[8] 每个图标在 16/32/48px 下都不是空白（缩放不该把它们抹掉）")
    for size in (16, 32, 48):
        blank = []
        for name in names:
            box = ink_box(name, box=size, scale=4)
            if box is None or (box[2] - box[0]) < 3.0:
                blank.append(name)
        check(not blank, f"{size}px 下没有空白/退化的图标（异常：{blank}）")
    # 显隐/锁定两态必须长得不一样，否则用户分不出当前状态
    from drawx.ui.icons import tool_icon as _icon

    def raw(name: str) -> bytes:
        return bytes(_icon(name).pixmap(22, 22).toImage().constBits())

    check(raw("eye") != raw("eye_off"), "睁眼 / 闭眼图标不同")
    check(raw("lock") != raw("unlock"), "上锁 / 开锁图标不同")

    failed = [message for ok, message in RESULTS if not ok]
    print("\n" + "=" * 60)
    print(f"总计 {len(RESULTS)} 项，通过 {len(RESULTS) - len(failed)} 项，失败 {len(failed)} 项")
    for message in failed:
        print("  FAILED:", message)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
