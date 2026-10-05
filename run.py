"""开发期启动入口：python run.py [图片或 .drawx 文件]

打包后由 PyInstaller 直接调用 drawx.app:main。
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from drawx.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
