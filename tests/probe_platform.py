"""最小探针：确认默认平台是否能建窗口、系统字体是否可用。"""

from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, str(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))


def watchdog() -> None:
    time.sleep(15)
    print("WATCHDOG: 15 秒未完成，强制退出", flush=True)
    os._exit(3)


threading.Thread(target=watchdog, daemon=True).start()

print("step1 import", flush=True)
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QFontDatabase, QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

print("step2 create app (platform 由环境决定)", flush=True)
app = QApplication([])
print("step3 platform =", app.platformName(), flush=True)

families = QFontDatabase.families()
print("step4 字体数量 =", len(families), flush=True)
print("   含 YaHei:", [f for f in families if "YaHei" in f or "宋体" in f or "SimSun" in f][:6], flush=True)

from PySide6.QtGui import QFont  # noqa: E402

probe = QFont("Microsoft YaHei")
print("   请求 Microsoft YaHei -> 实际:", QFontInfo_family := QFontMetrics(probe).fontDpi() and probe.family(), flush=True)
print("   字体可用性 exactMatch:",
      __import__("PySide6.QtGui", fromlist=["QFontInfo"]).QFontInfo(probe).exactMatch(), flush=True)

label = QLabel("中文测试 ABC")
label.resize(240, 80)
label.show()
print("step5 show() 返回", flush=True)
app.processEvents()
print("step6 processEvents 返回，截图尝试", flush=True)
try:
    ok = label.grab().save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "smoke", "probe.png"))
    print("   截图:", ok, flush=True)
except Exception as error:  # noqa: BLE001
    print("   截图失败:", error, flush=True)

QTimer.singleShot(300, app.quit)
app.exec()
print("step7 正常退出", flush=True)
