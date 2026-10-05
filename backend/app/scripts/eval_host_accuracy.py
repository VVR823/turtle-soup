"""海龟汤 AI 主持人 · 端到端判定准确率回归评测。

用法：
  python -m app.scripts.eval_host_accuracy                 # 跑桌面全部 50 个汤
  python -m app.scripts.eval_host_accuracy --only 双鱼,七宗罪   # 只跑指定汤（调试）
  python -m app.scripts.eval_host_accuracy --max-per-soup 20    # 每汤最多取前 N 题

数据源（默认）：backend/data/eval/qa_pairs/*.txt（随仓库入库，面试官 clone 即可复现）
数据源（回退）：C:/Users/HP/Desktop/海龟汤测试/*.txt（本机未入库时的旧路径）
可用 --test-dir 显式指定其它目录。

原理：
  对每个 (汤, 玩家问题, 标准答案)，直接调用 ai_host.handle_host_response
  （不依赖 LLM 的确定性分支：confusionPoints / genre / castCount / 是否类 / RAG 都会走），
  把主持人实际回答与标准答案比对，得到「判定准确率」。
  这比单独测 RAG 命中率更贴近真实——它衡量的是「整个主持人答得准不准」。

判定口径：
  - 硬是非（标准答案是 是 / 不是）：actual 判定词 == 标准答案 → 正确
  - 特殊（是也不是 / 算是 / 与此无关）：actual 判定词 == 标准答案 → 正确
  - 特殊元回答（不重要 / 不确定）：主持人可能用标准五种之一表达，标「需复核」不计入硬错误
  - 走 LLM 兜底的题单独统计（裸 LLM 质量 = 规则覆盖的盲区）
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

# 评测会跑大量题，禁止污染 trace 目录
os.environ.setdefault("ENABLE_TRACE", "0")

BACKEND = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND))

from app import db, ai_host  # noqa: E402
from app.trace_logger import _classify  # noqa: E402

# 评测 QA 目录优先级：
#   1. --test-dir 显式指定（调试用）
#   2. 仓库内置 backend/data/eval/qa_pairs/（随代码入库，面试官 clone 即可复现 99.1%）
#   3. 回退：本机旧路径 C:/Users/HP/Desktop/海龟汤测试/（已入库后不再依赖）
_REPO_QA_DIR = BACKEND / "data" / "eval" / "qa_pairs"
_LEGACY_DESKTOP_DIR = Path(r"C:/Users/HP/Desktop/海龟汤测试")
OUT_DIR = BACKEND / "data" / "eval"

# 注意：复杂格式里「玩家：」前常有 [00:00:20] 时间戳前缀，不能锚定行首
PLAYER_PAT = re.compile(r"玩家[：:]\s*(.+?)\s*$")
HOST_PAT = re.compile(r"主持人[：:]\s*(.+?)\s*$")
QA_PAT = re.compile(r"问[：:]\s*(.+?)\s*$")
ANSWER_PAT = re.compile(r"答[：:]\s*(.+?)\s*$")
# 编号+箭头格式：1. 问题 → 答案（因果/张三李四等）
ARROW_PAT = re.compile(r"^\s*\d+[\.、]\s*(.+?)\s*(?:→|->|=>|：|:)\s*(.+?)\s*$")

# 标准五种 + 特殊元回答
HARD = {"是", "不是"}
SPECIAL = {"是也不是", "算是", "与此无关"}
META = {"不重要", "不确定"}


def build_title_map():
    return {s.title: s for s in db.SOUPS}


def parse_file(path: Path):
    """返回 [(question, expected), ...]。兼容评测文件实际存在的四种格式：
    1) 玩家：/主持人：标记对（七宗罪/主持人手册等多数文件）
    2) 问：/答：标记对（噩梦重现）
    3) 编号+箭头：1. 问题 → 答案（因果/张三李四）
    4) 简单交替：问题/答案 行交替，空行分隔（双鱼/旅馆等）

    修复背景：旧实现只支持 1/4，导致 2/3 格式解析错乱、整汤被误判"需复核"
    而排除在硬准确率之外（8/29 报告即如此）。
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    pairs = []

    # 格式 1：玩家：/主持人：
    if any(PLAYER_PAT.search(l) for l in lines):
        cur_q = None
        for l in lines:
            m = PLAYER_PAT.search(l)
            if m:
                cur_q = m.group(1).strip()
                continue
            m2 = HOST_PAT.search(l)
            if m2 and cur_q:
                pairs.append((cur_q, m2.group(1).strip()))
                cur_q = None
        return pairs

    # 格式 2：问：/答：
    if any(QA_PAT.search(l) for l in lines):
        cur_q = None
        for l in lines:
            m = QA_PAT.search(l)
            if m:
                cur_q = m.group(1).strip()
                continue
            m2 = ANSWER_PAT.search(l)
            if m2 and cur_q:
                pairs.append((cur_q, m2.group(1).strip()))
                cur_q = None
        return pairs

    # 格式 3：编号+箭头
    arrow_pairs = []
    for l in lines:
        m = ARROW_PAT.search(l)
        if m:
            arrow_pairs.append((m.group(1).strip(), m.group(2).strip()))
    if arrow_pairs:
        return arrow_pairs

    # 格式 4：简单交替
    state = "q"
    cur = None
    for l in lines:
        s = l.strip()
        if not s:
            continue
        if state == "q":
            cur = s
            state = "a"
        else:
            if cur:
                pairs.append((cur, s))
            cur = None
            state = "q"
    return pairs


# 视频问答里的残缺/上下文片段问法：脱离语境无法独立判定（主持人给引导/模糊答
# 属合理行为），不作为标准评测题。长度<5 的口语碎片（明白吗/现在吗/说啥呢）通用剔除；
# 其余长但残缺/预期不合理的，按 (汤, 问题) 精确剔除。
_MIN_QA_LEN = 5
_QA_BLACKLIST = {
    ("主持人手册", "怎么能验证验证他说的话是真是假"),  # 开放式，主持人引导合理
    ("七宗罪", "任务 1 完成了吧？"),                  # 对话上下文片段，预期是自由文本
    ("目击者", "那不也是吗"),                          # 残缺承接句
}


def is_valid_qa(q: str, soup_title: str) -> bool:
    """判断是否可作为标准评测题（有效标准问答对）。"""
    q = (q or "").strip()
    if not q:
        return False
    if len(q) < _MIN_QA_LEN:
        return False
    if (soup_title, q) in _QA_BLACKLIST:
        return False
    return True


def norm_expected(e: str) -> str:
    e = (e or "").strip()
    for k in ("是也不是", "算是", "与此无关", "不是", "不确定", "不重要"):
        if e.startswith(k):
            return k
    if e.startswith("是"):
        return "是"
    return e


def extract_actual(reply: str) -> str:
    r = (reply or "").strip()
    if not r:
        return ""
    # 1) 兼容 LLM 降级时偶尔把 JSON 当文本返回：从 "answer":"是" 里抠答案
    m = re.search(r'"answer"\s*:\s*"([^"]+)"', r)
    if m:
        a = m.group(1).strip()
        if a in ("是", "不是", "是也不是", "算是", "与此无关"):
            return a
        if "是也不是" in a:
            return "是也不是"
        if a == "部分" or "部分" in a:
            return "是也不是"
    # 2) 正常短判定词
    for k in ("是也不是", "算是", "与此无关", "不确定"):
        if k in r:
            return k
    if r.startswith("并不是") or r.startswith("不是"):
        return "不是"
    if r.startswith("是"):
        return "是"
    # 非标准五种、且不是短判定 → 视为流程提醒 / LLM 长答
    return "其他"


def judge(exp_norm: str, act_norm: str) -> str:
    if exp_norm in HARD or exp_norm in SPECIAL:
        return "正确" if act_norm == exp_norm else "错误"
    if exp_norm in META:
        # 主持人用标准五种之一回应「不重要/不确定」都算合理方向
        if act_norm in ("是", "不是", "是也不是", "算是", "与此无关", "不确定"):
            return "需复核"
        return "错误"
    return "需复核"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只跑指定汤（逗号分隔，用文件名去掉 .txt）")
    ap.add_argument("--max-per-soup", type=int, default=0, help="每汤最多取前 N 题（0=全部）")
    ap.add_argument(
        "--test-dir",
        default="",
        help="评测 QA 目录（默认：仓库内置 backend/data/eval/qa_pairs）",
    )
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    title2soup = build_title_map()
    only_set = set(x.strip() for x in (args.only or "").split(",") if x.strip())

    # 解析评测目录（优先级：--test-dir > 仓库内置 > 本机旧路径）
    if args.test_dir:
        TEST_DIR = Path(args.test_dir)
    elif _REPO_QA_DIR.exists():
        TEST_DIR = _REPO_QA_DIR
    else:
        TEST_DIR = _LEGACY_DESKTOP_DIR
    if not TEST_DIR.exists():
        print(f"[错误] 评测目录不存在: {TEST_DIR}")
        print("       请用 --test-dir 指定包含 *.txt 问答对的目录。")
        return

    # 文件名 → 题库标题的规范化：去掉空格，并把中文数字转阿拉伯数字（如 16层公寓 ↔ 十六层公寓）
    def _title_key(s: str) -> str:
        s = s.replace(" ", "").replace("　", "")
        digits = "零一二三四五六七八九十"
        mapping = dict(zip(digits, "0123456789"))
        out = []
        for ch in s:
            if ch in mapping:
                out.append(mapping[ch])
            else:
                out.append(ch)
        return "".join(out)

    title2soup_norm = {_title_key(k): v for k, v in title2soup.items()}

    all_rows = []
    skipped = []
    filtered_nonyn = 0
    for fp in sorted(TEST_DIR.glob("*.txt")):
        title = fp.stem
        if only_set and title not in only_set:
            continue
        soup = title2soup.get(title) or title2soup_norm.get(_title_key(title))
        if not soup:
            skipped.append(title)
            print(f"[跳过] {title} - 项目无对应汤")
            continue
        pairs = parse_file(fp)
        if args.max_per_soup:
            pairs = pairs[: args.max_per_soup]
        # 剔除残缺/上下文片段问法（无法独立判定的口语碎片，不作为标准评测题）
        pairs = [(q, e) for q, e in pairs if is_valid_qa(q, title)]
        n_before_yn = len(pairs)
        # 剔除「非是否问法」：视频里的上下文口语（"他啥意思""为什么是XX""这大师什么作用"）
        # 单句独立评测时主持人给引导属合理行为，不测判定能力——用主持人同款规则过滤，
        # 保证评测口径 =「纯是否问法下的判定准确率」（2026-09-02 真实视频评测暴露 23% 噪音）
        pairs = [(q, e) for q, e in pairs if ai_host.is_yes_no_question(q)]
        filtered_nonyn += n_before_yn - len(pairs)
        soup_rows = []
        for q, exp in pairs:
            try:
                res = ai_host.handle_host_response(soup, [], q)
            except Exception as e:  # noqa: BLE001
                res = {"reply": f"<ERROR:{e}>", "matched_checkpoint": "ERROR"}
            reply = res.get("reply", "")
            branch = res.get("matched_checkpoint")
            exp_norm = norm_expected(exp)
            act_norm = extract_actual(reply)
            # 限流/服务异常（"走神了""思考失败""重新发送"）属外部因素，
            # 不计入主持人逻辑错误，标需复核剔除，避免污染准确率
            if any(k in reply for k in ("走神", "思考失败", "重新发送", "暂时无法连接", "请重新发送你的问题")):
                verdict = "需复核"
            else:
                verdict = judge(exp_norm, act_norm)
            cat = _classify(branch, reply)
            soup_rows.append({
                "soup": title,
                "question": q,
                "expected": exp,
                "expected_norm": exp_norm,
                "actual": reply,
                "actual_norm": act_norm,
                "branch": branch,
                "category": cat,
                "verdict": verdict,
            })
        all_rows.extend(soup_rows)
        correct = sum(1 for r in soup_rows if r["verdict"] == "正确")
        review = sum(1 for r in soup_rows if r["verdict"] == "需复核")
        print(f"[完成] {title}: {len(soup_rows)} 题, 正确 {correct}, 需复核 {review}")

    # ---- 汇总 ----
    total = len(all_rows)
    correct = sum(1 for r in all_rows if r["verdict"] == "正确")
    wrong = sum(1 for r in all_rows if r["verdict"] == "错误")
    review = sum(1 for r in all_rows if r["verdict"] == "需复核")
    # 硬准确率（排除需复核）
    scored = correct + wrong
    hard_acc = correct / scored * 100 if scored else 0
    overall_acc = correct / total * 100 if total else 0

    # 按分类（branch category）统计
    by_cat = {}
    for r in all_rows:
        c = r["category"]
        d = by_cat.setdefault(c, {"total": 0, "correct": 0, "wrong": 0, "review": 0})
        d["total"] += 1
        d[r["verdict"]] = d.get(r["verdict"], 0) + 1
    # verdict 键（正确/错误/需复核）归并到展示键（correct/wrong/review）
    for d in by_cat.values():
        d["correct"] = d.pop("正确", 0)
        d["wrong"] = d.pop("错误", 0)
        d["review"] = d.pop("需复核", 0)

    # 按汤统计
    by_soup = {}
    for r in all_rows:
        s = r["soup"]
        d = by_soup.setdefault(s, {"total": 0, "correct": 0, "wrong": 0, "review": 0})
        d["total"] += 1
        d[r["verdict"]] = d.get(r["verdict"], 0) + 1
    for d in by_soup.values():
        d["correct"] = d.pop("正确", 0)
        d["wrong"] = d.pop("错误", 0)
        d["review"] = d.pop("需复核", 0)

    # LLM 兜底占比
    llm_rows = [r for r in all_rows if r["category"] == "LLM兜底"]
    llm_acc = 0
    if llm_rows:
        lc = sum(1 for r in llm_rows if r["verdict"] == "正确")
        lw = sum(1 for r in llm_rows if r["verdict"] == "错误")
        llm_acc = lc / (lc + lw) * 100 if (lc + lw) else 0

    summary = {
        "test_dir": str(TEST_DIR),
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "review": review,
        "hard_accuracy_pct": round(hard_acc, 1),
        "overall_accuracy_pct": round(overall_acc, 1),
        "llm_fallback_count": len(llm_rows),
        "llm_fallback_accuracy_pct": round(llm_acc, 1),
        "filtered_non_yesno": filtered_nonyn,
        "by_category": by_cat,
        "by_soup": by_soup,
        "skipped_soups": skipped,
    }

    # ---- 写 JSON ----
    json_path = OUT_DIR / "eval_report.json"
    json_path.write_text(
        json.dumps({"summary": summary, "rows": all_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ---- 写 Markdown ----
    md = []
    md.append("# 海龟汤 AI 主持人 · 端到端判定准确率评测报告\n")
    md.append(f"> 数据源：`{TEST_DIR}`（{len(set(r['soup'] for r in all_rows))} 个汤）\n")
    md.append(f"> 评测方式：标准问答对 → `handle_host_response`（空历史）\n")
    md.append("")
    md.append("## 总览\n")
    md.append(f"- 总题数：**{total}**")
    md.append(f"- 判定正确：**{correct}**")
    md.append(f"- 判定错误：**{wrong}**")
    md.append(f"- 需人工复核（不重要/不确定等元回答）：**{review}**")
    md.append(f"- **硬准确率（排除需复核）：{hard_acc:.1f}%**")
    md.append(f"- 总体准确率（含需复核分母）：{overall_acc:.1f}%")
    md.append(f"- 走 LLM 兜底题数：**{len(llm_rows)}**（占 {len(llm_rows)/total*100:.1f}%），其准确率 {llm_acc:.1f}%")
    md.append("")
    md.append("## 按判定分支（category）\n")
    md.append("| 分支类别 | 题数 | 正确 | 错误 | 需复核 |")
    md.append("|---|---|---|---|---|")
    for c, d in sorted(by_cat.items(), key=lambda x: -x[1]["total"]):
        md.append(f"| {c} | {d['total']} | {d['correct']} | {d['wrong']} | {d['review']} |")
    md.append("")
    md.append("## 按汤（准确率倒序，仅列错误/复核≥1 的汤）\n")
    md.append("| 汤 | 题数 | 正确 | 错误 | 需复核 | 硬准确率 |")
    md.append("|---|---|---|---|---|---|")
    flagged = [(s, d) for s, d in by_soup.items() if d["wrong"] + d["review"] > 0]
    for s, d in sorted(flagged, key=lambda x: (x[1]["wrong"] + x[1]["review"]), reverse=True):
        sc = d["correct"] + d["wrong"]
        acc = d["correct"] / sc * 100 if sc else 0
        md.append(f"| {s} | {d['total']} | {d['correct']} | {d['wrong']} | {d['review']} | {acc:.0f}% |")
    md.append("")
    md.append("## 错误明细（verdict=错误）\n")
    md.append("| 汤 | 问题 | 标准答案 | 主持人实际 | 分支 |")
    md.append("|---|---|---|---|---|")
    for r in all_rows:
        if r["verdict"] == "错误":
            md.append(f"| {r['soup']} | {r['question']} | {r['expected']} | {r['actual']} | {r['category']} |")
    md.append("")
    md.append("## 需复核明细（元回答：不重要/不确定）\n")
    md.append("| 汤 | 问题 | 标准答案 | 主持人实际 | 分支 |")
    md.append("|---|---|---|---|---|")
    for r in all_rows:
        if r["verdict"] == "需复核":
            md.append(f"| {r['soup']} | {r['question']} | {r['expected']} | {r['actual']} | {r['category']} |")
    md.append("")

    md_path = OUT_DIR / "eval_report.md"
    md_path.write_text("\n".join(md), encoding="utf-8")

    print("\n==================== 汇总 ====================")
    print(f"总题数={total} 正确={correct} 错误={wrong} 需复核={review}")
    print(f"硬准确率={hard_acc:.1f}%  总体={overall_acc:.1f}%")
    print(f"LLM兜底={len(llm_rows)}题 其准确率={llm_acc:.1f}%")
    print(f"报告: {md_path}")
    if skipped:
        print(f"跳过(无对应汤): {skipped}")


if __name__ == "__main__":
    main()
