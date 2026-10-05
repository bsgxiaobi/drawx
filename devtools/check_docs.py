"""体检 README 与 docs/*.md 的 markdown 结构。

查四件事，都是改文档时最容易悄悄改坏的：

1. 相对链接指向的文件真的存在（`docs/` 之间的互链按所在目录解析）
2. 表格每一行的列数一致（GFM 里多一个 `|` 就会把整张表拆掉）
3. 代码围栏 ``` 成对
4. `<details>` / `</details>` 成对

用法：
    .venv\\Scripts\\python.exe devtools\\check_docs.py
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ["README.md"] + [
    os.path.join("docs", name) for name in os.listdir(os.path.join(ROOT, "docs")) if name.endswith(".md")
]

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def check_file(rel: str) -> list[str]:
    path = os.path.join(ROOT, rel)
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    bad: list[str] = []

    # 1) 代码围栏必须成对
    fences = sum(1 for line in lines if line.strip().startswith("```"))
    if fences % 2:
        bad.append(f"代码围栏 {fences} 个，不成对")

    # 2) <details> 配对
    text = "\n".join(lines)
    if text.count("<details>") != text.count("</details>"):
        bad.append("details 标签不配对")

    # 3) 相对链接必须存在
    for line_no, line in enumerate(lines, 1):
        for target in LINK_RE.findall(line):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            file_part = target.split("#", 1)[0]
            if not file_part:
                continue
            if not os.path.exists(os.path.join(ROOT, os.path.dirname(rel), file_part)):
                bad.append(f"{rel}:{line_no} 链接指向不存在的文件 {target}")

    # 4) 表格块内每行列数一致
    block: list[tuple[int, int]] = []
    for line_no, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            # 单元格里的 \| 是转义管道符（表格里写 `a | b` 必须这么写），不算分隔
            block.append((line_no, stripped.replace("\\|", "").count("|")))
            continue
        if block:
            cols = {count for _, count in block}
            if len(cols) != 1:
                bad.append(
                    f"{rel}:{block[0][0]} 起的表格列数不一致："
                    + ", ".join(f"第{ln}行 {c - 1} 列" for ln, c in block)
                )
            block = []
    return bad


def main() -> int:
    problems: list[str] = []
    for rel in FILES:
        found = check_file(rel)
        problems.extend(found)
        print(f"{'OK  ' if not found else 'FAIL'} {rel}")
    print()
    if problems:
        for item in problems:
            print(" -", item)
        print(f"\n共 {len(problems)} 个问题")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
