"""真实平台端到端验证：用 GUI 真的改一遍图层，再用工程文件核对结果。

流程：
1. 重新生成示例工程（保证图层顺序/位置是已知的初始状态）
2. 用 ``devtools/screen_agent.py`` 驱动真实窗口：移动图片、裁剪图片、
   隐藏图层、锁定图层、拖不透明度滑块、置顶图层、保存、退出
3. 重新读工程的 ``project.json``，逐项核对上一步的每个动作都落盘了
4. 最后把示例工程恢复成"干净的 2×2 拼图"，方便文档配图

用法：.venv\\Scripts\\python.exe devtools\\verify_gui_layers.py
"""

from __future__ import annotations

import json
import os
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")
PROJECT = ROOT / "build" / "gui" / "multi_site.drawx"
JOURNEY = ROOT / "devtools" / "scripts" / "gui_layers_edit.json"

RESULTS: list[tuple[bool, str]] = []


def check(condition: bool, message: str) -> None:
    RESULTS.append((bool(condition), message))
    print(("  PASS  " if condition else "  FAIL  ") + message, flush=True)


def run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("QT_QPA_PLATFORM", None)
    return subprocess.run(
        argv, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env, **kwargs
    )


def snapshot() -> dict:
    """在离屏平台里读工程，返回 {图层名: 状态}。"""
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    code = (
        "import json,sys;sys.path.insert(0,%r);"
        "from drawx.app import create_application;app=create_application([]);"
        "from drawx.model.serialize import load_project;"
        "doc,layers,view=load_project(%r);"
        "print(json.dumps({'order':[l.name for l in layers],"
        "'layers':{l.name:{'kind':l.kind,'visible':l.visible,'locked':l.locked,"
        "'opacity':round(l.opacity,3),"
        "'images':[{'pos':[round(i.pos().x(),1),round(i.pos().y(),1)],"
        "'src':[round(i.src_rect.x(),1),round(i.src_rect.y(),1),"
        "round(i.src_rect.width(),1),round(i.src_rect.height(),1)],"
        "'nat':list(i.natural_size())} for i in l.items "
        "if getattr(i,'TYPE','')=='image']} for l in layers}},ensure_ascii=False))"
    ) % (str(ROOT / "src"), str(PROJECT))
    result = run([PYTHON, "-c", code])
    if result.returncode != 0:
        raise SystemExit(f"读取工程失败：\n{result.stdout}\n{result.stderr}")
    for line in reversed(result.stdout.strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise SystemExit(f"读取工程没有输出 JSON：\n{result.stdout}")


def main() -> int:
    print("[1] 重新生成示例工程")
    result = run([PYTHON, str(ROOT / "devtools" / "multi_image_demo.py")])
    if result.returncode != 0:
        print(result.stdout, result.stderr)
        return 1
    before = snapshot()
    check(
        before["order"][:4] == ["标注", "site_1", "site_2", "site_3"],
        f"初始图层顺序 {before['order']}",
    )
    check(
        before["layers"]["site_1"]["images"][0]["pos"] == [100.0, 100.0],
        f"site_1 初始位置 {before['layers']['site_1']['images'][0]['pos']}",
    )
    check(before["layers"]["site_2"]["visible"], "site_2 初始可见")
    check(not before["layers"]["site_4"]["locked"], "site_4 初始未锁定")
    check(abs(before["layers"]["site_4"]["opacity"] - 1.0) < 1e-6, "site_4 初始不透明 100%")

    print("\n[2] 驱动真实窗口改一遍图层")
    result = run([PYTHON, str(ROOT / "devtools" / "screen_agent.py"), "run", str(JOURNEY)])
    print(result.stdout.strip()[-1200:] or result.stderr.strip()[-600:])
    check(result.returncode == 0, f"GUI 脚本跑完（exit={result.returncode}）")
    check(
        "Traceback" not in result.stdout and "Traceback" not in result.stderr,
        "GUI 脚本没抛异常",
    )

    print("\n[3] 核对工程文件（每个 GUI 动作都要落盘）")
    after = snapshot()
    check(
        after["order"][0] == "site_3",
        f"「置顶」生效：最上层是 {after['order'][0]}（顺序 {after['order']}）",
    )
    site_1 = after["layers"]["site_1"]["images"][0]
    check(
        site_1["pos"] != [100.0, 100.0],
        f"「移动图片」生效：pos={site_1['pos']}",
    )
    src = site_1["src"]
    check(
        src[2] < site_1["nat"][0] - 1 and src[3] < site_1["nat"][1] - 1,
        f"「裁剪图片」生效：保留区 {src} < 原图 {site_1['nat']}",
    )
    check(
        site_1["nat"] == [640, 480],
        f"裁剪是非破坏的：原图尺寸仍是 {site_1['nat']}",
    )
    check(not after["layers"]["site_2"]["visible"], "「隐藏图层」生效：site_2 不可见")
    check(after["layers"]["site_4"]["locked"], "「锁定图层」生效：site_4 已锁定")
    opacity = after["layers"]["site_4"]["opacity"]
    check(0.15 <= opacity <= 0.75, f"「图层不透明度」生效：site_4 = {opacity}")
    check(
        len(after["order"]) == len(before["order"]),
        "图层数量没变（没有误删）",
    )
    check(after["layers"]["site_1"]["kind"] == "image", "site_1 仍是图片图层")

    print("\n[4] 恢复成干净的示例工程（供文档/截图使用）")
    result = run([PYTHON, str(ROOT / "devtools" / "multi_image_demo.py")])
    clean = snapshot() if result.returncode == 0 else {"order": []}
    check(result.returncode == 0, "示例工程已恢复")
    check(clean["order"][:4] == ["标注", "site_1", "site_2", "site_3"], "恢复后顺序正确")
    with zipfile.ZipFile(PROJECT) as archive:
        names = set(archive.namelist())
    check(
        len([n for n in names if n.startswith("assets/")]) == 4,
        f"工程内嵌 4 张原图（{sorted(n for n in names if n.startswith('assets/'))}）",
    )

    failed = [message for ok, message in RESULTS if not ok]
    print("\n" + "=" * 60)
    print(f"总计 {len(RESULTS)} 项，通过 {len(RESULTS) - len(failed)} 项，失败 {len(failed)} 项")
    for message in failed:
        print("  FAILED:", message)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
