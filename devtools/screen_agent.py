"""给 AI 用的 Windows GUI 操控工具（纯 ctypes + Pillow，无需任何插件）。

设计原则：**尽量不碰用户的真实鼠标键盘**。点击/拖动/输入全部走
PostMessage 窗口消息，物理光标一动不动；只有截图时会短暂把目标窗口
提到前台（否则截到的是别的窗口）。

用法：
    python devtools/screen_agent.py list
    python devtools/screen_agent.py shot   --window DrawX --out step1.png
    python devtools/screen_agent.py click  --window DrawX --x 100 --y 200
    python devtools/screen_agent.py drag   --window DrawX --x1 10 --y1 10 --x2 200 --y2 120
    python devtools/screen_agent.py text   --window DrawX "中文标注"
    python devtools/screen_agent.py key    --window DrawX ctrl+s
    python devtools/screen_agent.py resize --window DrawX --x 40 --y 40 --w 1400 --h 900
    python devtools/screen_agent.py close  --window DrawX
    python devtools/screen_agent.py run    script.json     # 一串步骤一次跑完

坐标默认是**相对于窗口截图（含标题栏）的像素**，也就是你在截图里量到的位置。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import re
import sys
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t

user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, LPARAM), LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT
]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p]
KEYEVENTF_KEYUP = 0x0002
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.mouse_event.argtypes = [
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p
]
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
user32.LoadCursorW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user32.LoadCursorW.restype = ctypes.c_void_p
user32.GetCursorInfo.argtypes = [ctypes.c_void_p]


class CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hCursor", ctypes.c_void_p),
        ("ptScreenPos", wintypes.POINT),
    ]


CURSOR_NAMES = {
    32512: "arrow", 32513: "ibeam", 32514: "wait", 32515: "cross",
    32642: "size-nwse", 32643: "size-nesw", 32644: "size-we",
    32645: "size-ns", 32646: "size-all", 32648: "no", 32649: "hand",
}


def current_cursor() -> str:
    info = CURSORINFO()
    info.cbSize = ctypes.sizeof(CURSORINFO)
    if not user32.GetCursorInfo(ctypes.byref(info)):
        return "?"
    for identifier, name in CURSOR_NAMES.items():
        handle = user32.LoadCursorW(None, ctypes.cast(identifier, wintypes.LPCWSTR))
        if handle and handle == info.hCursor:
            return name
    return f"other({info.hCursor})"


# ------------------------------------------------------------------ 窗口图标
WM_GETICON = 0x007F
ICON_SMALL, ICON_BIG = 0, 1
GCLP_HICON, GCLP_HICONSM = -14, -34

user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.GetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetClassLongPtrW.restype = ctypes.c_ssize_t
user32.GetIconInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = ctypes.c_void_p
user32.ReleaseDC.argtypes = [wintypes.HWND, ctypes.c_void_p]
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", ctypes.c_void_p),
        ("hbmColor", ctypes.c_void_p),
    ]


class BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def window_icons(window: dict) -> dict:
    hwnd = wintypes.HWND(window["hwnd"])
    return {
        "wm_icon_big": int(user32.SendMessageW(hwnd, WM_GETICON, ICON_BIG, 0) or 0),
        "wm_icon_small": int(user32.SendMessageW(hwnd, WM_GETICON, ICON_SMALL, 0) or 0),
        "class_icon_big": int(user32.GetClassLongPtrW(hwnd, GCLP_HICON) or 0),
        "class_icon_small": int(user32.GetClassLongPtrW(hwnd, GCLP_HICONSM) or 0),
    }


def save_window_icon(window: dict, out_path: str, use_small: bool = False):
    """把窗口当前的图标抠出来存成 PNG，用于确认"真的是我们画的图标"。"""
    from PIL import Image

    icons = window_icons(window)
    handle = icons["wm_icon_small" if use_small else "wm_icon_big"] or icons[
        "class_icon_small" if use_small else "class_icon_big"
    ]
    if not handle:
        return None
    info = ICONINFO()
    if not user32.GetIconInfo(ctypes.c_void_p(handle), ctypes.byref(info)):
        return None
    bitmap = BITMAP()
    gdi32.GetObjectW(
        ctypes.c_void_p(info.hbmColor), ctypes.sizeof(BITMAP), ctypes.byref(bitmap)
    )
    width, height = int(bitmap.bmWidth), int(bitmap.bmHeight)
    if width <= 0 or height <= 0:
        return None

    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = width
    header.biHeight = -height  # 负数 = 自上而下
    header.biPlanes = 1
    header.biBitCount = 32
    header.biCompression = 0  # BI_RGB
    buffer = ctypes.create_string_buffer(width * height * 4)
    screen_dc = user32.GetDC(None)
    gdi32.GetDIBits(
        ctypes.c_void_p(screen_dc),
        ctypes.c_void_p(info.hbmColor),
        0,
        height,
        buffer,
        ctypes.byref(header),
        0,
    )
    user32.ReleaseDC(None, ctypes.c_void_p(screen_dc))

    image = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1)
    # 图标有可能 alpha 全 0，铺一层灰底才能看清形状
    canvas = Image.new("RGBA", (width, height), (58, 58, 64, 255))
    canvas.alpha_composite(image)
    canvas.convert("RGB").save(out_path)
    return (width, height)
try:
    user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    user32.GetDpiForWindow.restype = wintypes.UINT
except AttributeError:  # pragma: no cover - 老系统
    pass

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK = 0x0201, 0x0202, 0x0203
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x0207, 0x0208
WM_KEYDOWN, WM_KEYUP, WM_CHAR = 0x0100, 0x0101, 0x0102
WM_CLOSE = 0x0010
SW_RESTORE = 9
SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
SWP_NOMOVE, SWP_NOSIZE, SWP_SHOWWINDOW = 0x0002, 0x0001, 0x0040
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2

MK_LBUTTON, MK_RBUTTON, MK_MBUTTON = 0x0001, 0x0002, 0x0010

VK = {
    "back": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "shift": 0x10,
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "pause": 0x13, "caps": 0x14,
    "esc": 0x1B, "escape": 0x1B, "space": 0x20, "pageup": 0x21, "pagedown": 0x22,
    "end": 0x23, "home": 0x24, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "insert": 0x2D, "delete": 0x2E, "del": 0x2E,
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK[_c] = ord(_c.upper())
for _c in "=+-[],./\\;'`":
    VK.setdefault(_c, ord(_c.upper()))


# ------------------------------------------------------------------ 窗口
def list_windows() -> list[dict]:
    result: list[dict] = []
    pid = wintypes.DWORD()

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value
        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, 256)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        dpi = 96
        try:
            dpi = user32.GetDpiForWindow(hwnd) or 96
        except Exception:
            pass
        result.append(
            {
                "hwnd": int(hwnd),
                "title": title,
                "class": class_buffer.value,
                "pid": int(pid.value),
                "rect": [rect.left, rect.top, rect.right, rect.bottom],
                "size": [rect.right - rect.left, rect.bottom - rect.top],
                "dpi": int(dpi),
            }
        )
        return True

    user32.EnumWindows(
        ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, LPARAM)(callback), 0
    )
    return result


def find_window(pattern: str, hwnd: int | None = None) -> dict:
    windows = list_windows()
    if hwnd:
        for window in windows:
            if window["hwnd"] == hwnd:
                return window
        raise SystemExit(f"找不到 hwnd={hwnd}")
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        regex = re.compile(re.escape(pattern), re.IGNORECASE)
    matches = [w for w in windows if regex.search(w["title"])]
    if not matches:
        raise SystemExit(f"没有标题匹配 {pattern!r} 的可见窗口")
    matches.sort(key=lambda w: (w["size"][0] * w["size"][1]), reverse=True)
    return matches[0]


def client_offset(window: dict) -> tuple[int, int, int, int]:
    """返回窗口客户区相对窗口左上角的偏移与客户区尺寸。"""
    rect = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(window["hwnd"]), ctypes.byref(rect))
    point = wintypes.POINT(0, 0)
    user32.ClientToScreen(wintypes.HWND(window["hwnd"]), ctypes.byref(point))
    client = wintypes.RECT()
    user32.GetClientRect(wintypes.HWND(window["hwnd"]), ctypes.byref(client))
    return point.x - rect.left, point.y - rect.top, client.right, client.bottom


def to_client(window: dict, x: int, y: int) -> tuple[int, int]:
    """把"相对于窗口截图"的坐标换算成客户区坐标。"""
    offset_x, offset_y, _, _ = client_offset(window)
    return int(x) - offset_x, int(y) - offset_y


def make_lparam(x: int, y: int) -> int:
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


def post(hwnd: int, message: int, wparam: int = 0, lparam: int = 0) -> None:
    user32.PostMessageW(wintypes.HWND(hwnd), message, WPARAM(wparam), LPARAM(lparam))


# ------------------------------------------------------------------ 动作
def bring_to_front(window: dict) -> None:
    hwnd = wintypes.HWND(window["hwnd"])
    user32.ShowWindow(hwnd, SW_RESTORE)
    # 先钉到最上层再截，否则别的窗口压在目标窗口上会混进截图里
    user32.SetWindowPos(
        hwnd, wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW | SWP_NOACTIVATE,
    )
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.35)


def drop_from_top(window: dict) -> None:
    user32.SetWindowPos(
        wintypes.HWND(window["hwnd"]), wintypes.HWND(HWND_NOTOPMOST), 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
    )


def screenshot(window: dict | None, out: str, full: bool = False) -> str:
    from PIL import ImageGrab

    if full or window is None:
        image = ImageGrab.grab(all_screens=True)
    else:
        bring_to_front(window)
        try:
            rect = wintypes.RECT()
            user32.GetWindowRect(wintypes.HWND(window["hwnd"]), ctypes.byref(rect))
            image = ImageGrab.grab(
                bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True
            )
        finally:
            drop_from_top(window)
    image.save(out)
    return out


def click(window: dict, x: int, y: int, button: str = "left", double: bool = False) -> None:
    cx, cy = to_client(window, x, y)
    lparam = make_lparam(cx, cy)
    down, up, mk = {
        "left": (WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON),
        "right": (WM_RBUTTONDOWN, WM_RBUTTONUP, MK_RBUTTON),
        "middle": (WM_MBUTTONDOWN, WM_MBUTTONUP, MK_MBUTTON),
    }[button]
    post(window["hwnd"], WM_MOUSEMOVE, 0, lparam)
    time.sleep(0.05)
    if double:
        post(window["hwnd"], WM_LBUTTONDBLCLK, mk, lparam)
        post(window["hwnd"], WM_LBUTTONUP, 0, lparam)
        time.sleep(0.05)
        post(window["hwnd"], WM_LBUTTONDBLCLK, mk, lparam)
        post(window["hwnd"], WM_LBUTTONUP, 0, lparam)
        return
    post(window["hwnd"], down, mk, lparam)
    time.sleep(0.06)
    post(window["hwnd"], up, 0, lparam)


def drag(
    window: dict,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    button: str = "left",
    steps: int = 12,
    hold: float = 0.02,
) -> None:
    c1 = to_client(window, x1, y1)
    c2 = to_client(window, x2, y2)
    down, up, mk = {
        "left": (WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON),
        "right": (WM_RBUTTONDOWN, WM_RBUTTONUP, MK_RBUTTON),
        "middle": (WM_MBUTTONDOWN, WM_MBUTTONUP, MK_MBUTTON),
    }[button]
    post(window["hwnd"], WM_MOUSEMOVE, 0, make_lparam(*c1))
    time.sleep(0.06)
    post(window["hwnd"], down, mk, make_lparam(*c1))
    time.sleep(0.06)
    for index in range(1, steps + 1):
        ratio = index / steps
        x = round(c1[0] + (c2[0] - c1[0]) * ratio)
        y = round(c1[1] + (c2[1] - c1[1]) * ratio)
        post(window["hwnd"], WM_MOUSEMOVE, mk, make_lparam(x, y))
        time.sleep(hold)
    post(window["hwnd"], up, 0, make_lparam(*c2))


def type_text(window: dict, text: str) -> None:
    for character in text:
        code = ord(character)
        post(window["hwnd"], WM_CHAR, code, 0)
        time.sleep(0.012)


def press_key(window: dict, spec: str) -> None:
    """支持 ctrl+s / shift+ctrl+z / enter / F1 这类写法。"""
    parts = [p.strip().lower() for p in re.split(r"[+\-]", spec) if p.strip()]
    if not parts:
        return
    modifiers = [p for p in parts[:-1] if p in VK]
    key = parts[-1]
    if key not in VK:
        raise SystemExit(f"不认识按键: {key}")
    for name in modifiers:
        post(window["hwnd"], WM_KEYDOWN, VK[name], 0)
    post(window["hwnd"], WM_KEYDOWN, VK[key], 0)
    time.sleep(0.03)
    post(window["hwnd"], WM_KEYUP, VK[key], 0)
    for name in reversed(modifiers):
        post(window["hwnd"], WM_KEYUP, VK[name], 0)


def press_key_real(window: dict, spec: str) -> None:
    """真实键盘注入。

    组合键必须走这条路：PostMessage 伪造的 WM_KEYDOWN 不会更新 GetKeyState，
    Qt 据此判断修饰键，于是 ctrl+s 这类快捷键完全不认。
    """
    bring_to_front(window)
    parts = [p.strip().lower() for p in re.split(r"[+\-]", spec) if p.strip()]
    if not parts:
        return
    modifiers = [p for p in parts[:-1] if p in VK]
    key = parts[-1]
    if key not in VK:
        raise SystemExit(f"不认识按键: {key}")
    for name in modifiers:
        user32.keybd_event(VK[name], 0, 0, None)
        time.sleep(0.02)
    user32.keybd_event(VK[key], 0, 0, None)
    time.sleep(0.04)
    user32.keybd_event(VK[key], 0, KEYEVENTF_KEYUP, None)
    for name in reversed(modifiers):
        user32.keybd_event(VK[name], 0, KEYEVENTF_KEYUP, None)
    drop_from_top(window)


def type_text_real(window: dict, text: str) -> None:
    """真实键盘逐字注入（先放到剪贴板再粘贴会更快，但逐字更接近真人）。"""
    bring_to_front(window)
    for character in text:
        vk = VK.get(character.lower())
        if vk is None:
            continue
        shift = character.isupper() or character in "~!@#$%^&*()_+{}|:\"<>?"
        if shift:
            user32.keybd_event(VK["shift"], 0, 0, None)
        user32.keybd_event(vk, 0, 0, None)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, None)
        if shift:
            user32.keybd_event(VK["shift"], 0, KEYEVENTF_KEYUP, None)
        time.sleep(0.02)


def real_drag(x1: int, y1: int, x2: int, y2: int, steps: int = 25, hold: float = 0.04) -> None:
    """用真实鼠标做一次跨进程拖拽（屏幕绝对坐标）。

    OLE 拖放（比如从资源管理器把文件拖进程序）只认真实输入队列，
    PostMessage 伪造的鼠标消息完全不会触发它，所以测拖放必须用这个。
    """
    user32.SetCursorPos(int(x1), int(y1))
    time.sleep(0.25)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
    time.sleep(0.30)
    for index in range(1, steps + 1):
        ratio = index / steps
        x = int(x1 + (x2 - x1) * ratio)
        y = int(y1 + (y2 - y1) * ratio)
        user32.SetCursorPos(x, y)
        time.sleep(hold)
    time.sleep(0.30)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
    time.sleep(0.20)


def hover(window: dict, x: int, y: int) -> str:
    """把真实鼠标挪到窗口内某点并触发一次移动消息，然后报告当前光标形状。

    光标是否真的变了，只有让鼠标真的在那个窗口上才测得准。
    """
    cx, cy = to_client(window, x, y)
    point = wintypes.POINT(cx, cy)
    user32.ClientToScreen(wintypes.HWND(window["hwnd"]), ctypes.byref(point))
    user32.SetCursorPos(point.x, point.y)
    time.sleep(0.15)
    post(window["hwnd"], WM_MOUSEMOVE, 0, make_lparam(cx, cy))
    time.sleep(0.25)
    return current_cursor()


def resize(window: dict, x: int, y: int, w: int, h: int) -> None:
    user32.SetWindowPos(
        wintypes.HWND(window["hwnd"]), None, int(x), int(y), int(w), int(h),
        SWP_NOZORDER | SWP_NOACTIVATE,
    )


def close(window: dict) -> None:
    post(window["hwnd"], WM_CLOSE)


# ------------------------------------------------------------------ 脚本
def run_script(path: str) -> int:
    with open(path, encoding="utf-8") as handle:
        steps = json.load(handle)
    if isinstance(steps, dict):
        steps = steps.get("steps", [])
    window = None
    for index, step in enumerate(steps):
        op = step.get("op")
        if op == "sleep":
            time.sleep(float(step.get("seconds", 0.5)))
            continue
        if op == "list":
            for item in list_windows():
                print(f"  {item['hwnd']:>10}  {item['size'][0]:>5}x{item['size'][1]:<5} {item['title'][:60]}")
            continue
        if op == "launch":
            import subprocess

            # 必须把子进程的 stdio 指向 DEVNULL：
            # 否则它继承我们的 stdout，调用方的管道要等这个"被测程序"退出才 EOF，
            # 于是 `screen_agent run xxx.json | ...` 会一直挂着（实测踩过）。
            subprocess.Popen(
                step["argv"],
                cwd=step.get("cwd"),
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(float(step.get("wait", 3.0)))
            print(f"  已启动 {step['argv'][0]}", flush=True)
            continue
        if op == "kill":
            import subprocess

            subprocess.run(
                ["taskkill", "/F", "/IM", step["name"]],
                capture_output=True,
                close_fds=True,
            )
            continue
        if window is None or step.get("refresh"):
            window = find_window(step.get("window", "."))
        if op == "shot":
            out = screenshot(window, step["out"], full=step.get("full", False))
            print(f"  截图 -> {out}  窗口={window['size'][0]}x{window['size'][1]} dpi={window['dpi']}")
        elif op == "click":
            click(window, step["x"], step["y"], step.get("button", "left"), step.get("double", False))
            print(f"  点击 ({step['x']},{step['y']})")
        elif op == "drag":
            drag(window, step["x1"], step["y1"], step["x2"], step["y2"],
                 steps=int(step.get("steps", 12)))
            print(f"  拖动 ({step['x1']},{step['y1']}) -> ({step['x2']},{step['y2']})")
        elif op == "text":
            type_text(window, step["text"])
            print(f"  输入 {step['text']!r}")
        elif op == "key":
            if step.get("real"):
                press_key_real(window, step["key"])
            else:
                press_key(window, step["key"])
            print(f"  按键 {step['key']}{' (真实注入)' if step.get('real') else ''}")
        elif op == "resize":
            resize(window, step["x"], step["y"], step["w"], step["h"])
            print(f"  调整窗口 {step['w']}x{step['h']}")
        elif op == "close":
            close(window)
            print("  已请求关闭窗口")
        elif op == "waitgone":
            import subprocess

            for _ in range(int(step.get("tries", 20))):
                alive = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {window['pid']}"],
                    capture_output=True, text=True, close_fds=True,
                ).stdout
                if str(window["pid"]) not in alive:
                    break
                time.sleep(0.3)
        else:
            raise SystemExit(f"第 {index} 步不认识的操作: {op}")
        time.sleep(float(step.get("after", 0.12)))
    return 0


# ------------------------------------------------------------------ CLI
def _setup_console() -> None:
    """把标准输出切成 UTF-8。

    中文 Windows 的控制台代码页是 GBK，窗口标题里只要有一个 ❓/emoji 之类的字符，
    print 就会抛 UnicodeEncodeError，整个工具直接失败（曾经真的踩到）。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - 老环境没有 reconfigure 也无所谓
            pass


def main(argv: list[str] | None = None) -> int:
    _setup_console()
    parser = argparse.ArgumentParser(description="Windows GUI 操控工具")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出可见窗口")

    def add_window_args(p):
        p.add_argument("--window", default=".", help="标题正则（大小写不敏感）")
        p.add_argument("--hwnd", type=int, default=None)

    p = sub.add_parser("shot")
    add_window_args(p)
    p.add_argument("--out", required=True)
    p.add_argument("--full", action="store_true", help="截整个虚拟桌面")

    p = sub.add_parser("click")
    add_window_args(p)
    p.add_argument("--x", type=int, required=True)
    p.add_argument("--y", type=int, required=True)
    p.add_argument("--button", default="left")
    p.add_argument("--double", action="store_true")

    p = sub.add_parser("drag")
    add_window_args(p)
    for name in ("x1", "y1", "x2", "y2"):
        p.add_argument(f"--{name}", type=int, required=True)
    p.add_argument("--button", default="left")
    p.add_argument("--steps", type=int, default=12)

    p = sub.add_parser("text")
    add_window_args(p)
    p.add_argument("content")

    p = sub.add_parser("key")
    add_window_args(p)
    p.add_argument("spec")
    p.add_argument("--real", action="store_true", help="真实键盘注入（组合键必须用这个）")

    p = sub.add_parser("resize")
    add_window_args(p)
    for name in ("x", "y", "w", "h"):
        p.add_argument(f"--{name}", type=int, required=True)

    p = sub.add_parser("close")
    add_window_args(p)

    p = sub.add_parser("run")
    p.add_argument("script")

    p = sub.add_parser("hover", help="移动真实鼠标到窗口内某点并报告光标形状")
    add_window_args(p)
    p.add_argument("--x", type=int, required=True)
    p.add_argument("--y", type=int, required=True)

    p = sub.add_parser("realdrag", help="真实鼠标跨进程拖拽（屏幕绝对坐标）")
    for name in ("x1", "y1", "x2", "y2"):
        p.add_argument(f"--{name}", type=int, required=True)
    p.add_argument("--steps", type=int, default=25)

    p = sub.add_parser("winicon", help="报告窗口图标句柄，并可导出成 PNG")
    add_window_args(p)
    p.add_argument("--out", default=None, help="把窗口图标存成 PNG 的路径")
    p.add_argument("--small", action="store_true", help="取 16x16 的小图标")

    p = sub.add_parser("crop", help="裁剪放大一张已有截图（方便看清局部）")
    p.add_argument("--in", dest="source", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--box", required=True, help="left,top,right,bottom")
    p.add_argument("--scale", type=float, default=2.0)

    args = parser.parse_args(argv)

    if args.command == "crop":
        from PIL import Image

        left, top, right, bottom = (int(v) for v in args.box.split(","))
        image = Image.open(args.source).crop((left, top, right, bottom))
        if args.scale != 1.0:
            image = image.resize(
                (int(image.width * args.scale), int(image.height * args.scale)),
                Image.LANCZOS,
            )
        image.save(args.out)
        print(f"{args.out}  {image.width}x{image.height}")
        return 0

    if args.command == "realdrag":
        real_drag(args.x1, args.y1, args.x2, args.y2, args.steps)
        print(f"真实拖拽 ({args.x1},{args.y1}) -> ({args.x2},{args.y2})")
        return 0

    if args.command == "winicon":
        window = find_window(args.window, args.hwnd)
        icons = window_icons(window)
        for key, value in icons.items():
            print(f"  {key:<16} = {value} (0x{value:x})" if value else f"  {key:<16} = 0")
        if args.out:
            size = save_window_icon(window, args.out, use_small=args.small)
            print(f"  图标已导出: {args.out} {size}")
        return 0

    if args.command == "list":
        for item in list_windows():
            print(f"{item['hwnd']:>10}  pid={item['pid']:<7} {item['size'][0]:>5}x{item['size'][1]:<5} "
                  f"dpi={item['dpi']:<4} {item['class'][:24]:<24} {item['title'][:70]}")
        return 0

    if args.command == "run":
        return run_script(args.script)

    window = find_window(args.window, args.hwnd)
    print(f"目标窗口: hwnd={window['hwnd']} '{window['title']}' {window['size'][0]}x{window['size'][1]}")

    if args.command == "shot":
        print(screenshot(window, args.out, full=args.full))
    elif args.command == "click":
        click(window, args.x, args.y, args.button, args.double)
    elif args.command == "drag":
        drag(window, args.x1, args.y1, args.x2, args.y2, args.button, args.steps)
    elif args.command == "text":
        type_text(window, args.content)
    elif args.command == "key":
        if args.real:
            press_key_real(window, args.spec)
        else:
            press_key(window, args.spec)
    elif args.command == "resize":
        resize(window, args.x, args.y, args.w, args.h)
    elif args.command == "close":
        close(window)
    elif args.command == "hover":
        print(f"光标: {hover(window, args.x, args.y)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
