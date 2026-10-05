"""生成一张"像是截图"的测试素材（有文字、数字、表格），供 GUI 实操测试用。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "gui")


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"):
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def build(width: int = 1100, height: int = 720) -> Image.Image:
    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)
    title_font = load_font(24)
    label_font = load_font(17)
    value_font = load_font(17)

    draw.rectangle([0, 0, width, 58], fill="#2b579a")
    draw.text((24, 16), "客户资料管理系统 —— 订单详情", font=title_font, fill="#ffffff")

    rows = [
        ("订单号", "SO-2024-0912-0037"),
        ("客户姓名", "张三"),
        ("手机号码", "13800138000"),
        ("身份证号", "110101199003074512"),
        ("收货地址", "北京市海淀区中关村南大街 5 号院 3 号楼 1201"),
        ("支付方式", "招商银行储蓄卡 **** **** 8899"),
        ("订单金额", "￥12,800.00"),
        ("下单时间", "2024-09-12 14:32:07"),
    ]
    y = 100
    for label, value in rows:
        draw.text((48, y), label, font=label_font, fill="#8a8a92")
        draw.text((190, y), value, font=value_font, fill="#1c1c22")
        draw.line([48, y + 32, width - 48, y + 32], fill="#ececf0", width=1)
        y += 52

    draw.rectangle([48, 520, width - 48, 660], fill="#f7f9fc", outline="#d5dde8")
    draw.text((70, 540), "备注：客户要求工作日 18:00 后配送，需电话确认。", font=label_font, fill="#39465c")
    draw.text((70, 575), "内部标记：VIP 客户，历史订单 37 笔，无退款记录。", font=label_font, fill="#39465c")
    draw.text((70, 615), "Secret-Probe-9931", font=label_font, fill="#9aa3b2")

    return image


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    image = build()
    path = os.path.join(OUT_DIR, "sample_screenshot.png")
    image.save(path)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
