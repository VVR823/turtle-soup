"""为缺测汤自动构建评测问答集。

背景：题库 66 道中 26 道没有评测文件（其中新世界为彩蛋/无判定点，豁免）。
本脚本从 soups.py 的 checkpoints（aliases 问法 + answer 预期）和
confusionPoints（q/a 标准对）自动生成标准问答对，写入 data/eval/qa_pairs/{title}.txt，
与既有 40 道评测文件同格式（玩家：/主持人：），供 eval_host_accuracy.py 直接消费。

用法：
  python -m app.scripts.gen_missing_qa           # 全量补齐缺测汤
  python -m app.scripts.gen_missing_qa --only 火车,二十   # 只补指定汤
"""
import argparse
import ast
import os
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent.parent
SOUPS_PY = BACKEND / "app" / "soups.py"
QA_DIR = BACKEND / "data" / "eval" / "qa_pairs"

# 开放式疑问词：这类问法主持人会引导改问（无法用是/不是回答），不能作为标准评测题
_OPEN_KEYWORDS = [
    "什么", "谁", "哪个", "哪些", "哪里", "去哪", "为什么", "怎么",
    "如何", "为啥", "多少", "几个", "多久", "介绍", "告诉", "详细",
    "具体", "描述", "说说", "讲讲", "解释", "哪儿",
]


def _is_yes_no_question(q: str) -> bool:
    """只保留主持人能判定为"是/不是类"的标准问法（与 ai_host.is_yes_no_question 口径一致）。

    规则：
    1. 太短（<4 字）的裸关键词（如"古曼童""供奉"）不算问题，过滤；
    2. 含开放式疑问词（什么/谁/为什么…）的过滤（主持人会引导改问）；
    3. 含强疑问标志（是不是/是否/有没有/能不能/可不可以/会不会/能否）→ 保留；
    4. 句尾 吗/么/？ → 保留。
    """
    q = (q or "").strip()
    if len(q) < 4:
        return False
    if any(kw in q for kw in _OPEN_KEYWORDS):
        return False
    if re.search(r"(是不是|是否|有没有|能不能|可不可以|会不会|能否|有木有)", q):
        return True
    if q.endswith(("吗", "么", "？", "?")):
        return True
    return False


def load_soups() -> dict:
    """用 AST 解析 soups.py 的 SEED_SOUPS（dict 列表），返回 {title: soup}。"""
    src = SOUPS_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    soups = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        d = {}
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                try:
                    d[k.value] = ast.literal_eval(v)
                except Exception:  # 非字面量（如嵌套表达式）跳过
                    d[k.value] = None
        if d.get("title"):
            soups[d["title"]] = d
    return soups


def answer_str(ans) -> str:
    """checkpoints.answer 可能是 bool 或字符串 → 统一为标准判定词。"""
    if ans is True:
        return "是"
    if ans is False:
        return "不是"
    if isinstance(ans, str):
        a = ans.strip()
        for k in ("是也不是", "算是", "与此无关", "不是", "不确定", "不重要"):
            if a.startswith(k):
                return k
        if a.startswith("是"):
            return "是"
        return a
    return str(ans)


def build_pairs(soup: dict) -> list[tuple[str, str]]:
    """从 checkpoints.aliases + confusionPoints 生成 (question, expected) 列表。

    只保留主持人能用"是/不是"正确判定的标准问法（_is_yes_no_question 过滤），
    避免把裸关键词、开放式问法写进评测集拉低准确率。
    """
    pairs = []
    seen = set()

    def _add(q: str, a: str):
        q = (q or "").strip()
        if not q or q in seen or not _is_yes_no_question(q):
            return
        seen.add(q)
        pairs.append((q, a))

    for cp in soup.get("checkpoints") or []:
        a = answer_str(cp.get("answer"))
        for alias in cp.get("aliases") or []:
            _add(alias, a)
    for cf in soup.get("confusionPoints") or []:
        _add(cf.get("q"), answer_str(cf.get("a")))
    return pairs


def write_qa_file(title: str, pairs: list[tuple[str, str]]) -> Path:
    lines = [title, "=" * 80, ""]
    lines.append("【评测集来源】自动生成：由题库 checkpoints/confusionPoints 构建（标准问答对）")
    lines.append("=" * 80)
    lines.append("")
    for q, a in pairs:
        lines.append(f"玩家：{q}")
        lines.append(f"主持人：{a}")
        lines.append("")
    fp = QA_DIR / f"{title}.txt"
    fp.write_text("\n".join(lines), encoding="utf-8")
    return fp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="只补指定汤（逗号分隔，默认补全部缺测）")
    args = ap.parse_args()
    only_set = {x.strip() for x in args.only.split(",") if x.strip()}

    QA_DIR.mkdir(parents=True, exist_ok=True)
    soups = load_soups()
    have = {f[:-4] for f in os.listdir(QA_DIR) if f.endswith(".txt")}
    missing = [t for t in soups if t not in have]
    if only_set:
        missing = [t for t in missing if t in only_set]

    total = 0
    for t in sorted(missing):
        s = soups[t]
        cps = s.get("checkpoints") or []
        cfs = s.get("confusionPoints") or []
        if not cps and not cfs:
            print(f"[豁免] {t} - 无 checkpoints/confusionPoints（彩蛋/特殊汤），跳过")
            continue
        pairs = build_pairs(s)
        fp = write_qa_file(t, pairs)
        total += len(pairs)
        print(f"[生成] {t}: {len(pairs)} 题 -> {fp.relative_to(BACKEND)}")
    print(f"\n共生成 {total} 题，写入 {QA_DIR}")


if __name__ == "__main__":
    main()
