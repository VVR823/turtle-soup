"""加汤强制标准校验：确保每道非彩蛋汤都正确标注 genre 与 castCount。

用法：
    python backend/validate_soups.py
退出码 0 = 全部合规；1 = 存在不合规汤（应阻断部署）。

规则（见 .workbuddy/memory/MEMORY.md 加汤强制标准第 5、6 条）：
- 非 always_yes 的汤必须 genre in ("本格","变格")
- 非 always_yes 的汤必须 castCount 为 int 且 >= 1
- always_yes 彩蛋汤（如新世界）不强制这两项（其永远答"是"，不依赖字段）
"""

import sys
import os

# soups.py 位于 backend/app/ 下
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))

from soups import SEED_SOUPS  # noqa: E402


def main() -> int:
    problems = []
    total = 0
    checked = 0

    for s in SEED_SOUPS:
        total += 1
        title = s.get("title", "<无标题>")
        always_yes = s.get("always_yes", False)

        if always_yes:
            # 彩蛋汤：不强制 genre / castCount
            print(f"[跳过] {title}（always_yes 彩蛋，不强制字段）")
            continue

        checked += 1
        genre = (s.get("genre") or "").strip()
        cc = s.get("castCount", None)

        if genre not in ("本格", "变格"):
            problems.append(f"  ✗ {title}: genre 必填 '本格'/'变格'，当前={genre!r}")
        if not isinstance(cc, int) or cc < 1:
            problems.append(f"  ✗ {title}: castCount 必填正整数，当前={cc!r}")

        if genre in ("本格", "变格") and isinstance(cc, int) and cc >= 1:
            print(f"[OK]   {title}: genre={genre}, castCount={cc}")

    print("-" * 50)
    print(f"共 {total} 道汤，校验 {checked} 道非彩蛋汤")
    if problems:
        print(f"发现 {len(problems)} 处不合规：")
        for p in problems:
            print(p)
        print("\n⛔ 存在不合规汤，请修正后再部署。")
        return 1

    print("✅ 全部合规，可部署。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
