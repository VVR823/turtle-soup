"""自然问法评测（治本机制第一环）：
对每道汤，用 LLM 从汤底生成 8 条「玩家可能问的是/不是问题 + 标准答案」，
再跑完整主持人判定链路，统计每道汤的真实答对率，输出错题清单。
这些自然问法入库后即成为永久评测集（natural_qa/），以后任何改动都能暴露真实体验回归。
用法：python gen_natural_qa.py [--limit 汤数] [--per 每汤题数]
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))

from app import db, ai_host  # noqa: E402

os.environ.setdefault("ENABLE_TRACE", "0")


# —— 判定辅助（内联，避免依赖 eval_host_accuracy）——
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
    for k in ("是也不是", "算是", "与此无关", "不确定"):
        if k in r:
            return k
    if r.startswith("并不是") or r.startswith("不是"):
        return "不是"
    if r.startswith("是"):
        return "是"
    return "其他"


def judge(exp_norm: str, act_norm: str) -> str:
    if exp_norm in ("是", "不是", "是也不是", "算是", "与此无关"):
        return "正确" if act_norm == exp_norm else "错误"
    if exp_norm in ("不重要", "不确定"):
        return "需复核" if act_norm in ("是", "不是", "是也不是", "算是", "与此无关", "不确定") else "错误"
    return "需复核"

# 从 backend/.env 读 SiliconFlow key（服务器上已有）
API_KEY = ""
for line in (BACKEND / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line.startswith("SILICONFLOW_API_KEY="):
        API_KEY = line.split("=", 1)[1].strip()
MODEL = os.environ.get("NATURAL_QA_MODEL", "Qwen/Qwen2.5-7B-Instruct")

GEN_PROMPT = (
    "你是海龟汤资深玩家，刚刚看完一道汤的【汤底真相】。"
    "请像真实玩家一样，提出 {n} 个可以用「是/不是/是也不是/算是/与此无关」回答的问题，"
    "并给出标准答案。问题要覆盖汤底的关键情节，问法要口语化、多样（不要全部是「X是Y吗」，"
    "可以穿插「有X吗」「X会Y吗」「X发生在Z吗」「是不是X」「X真的Y了吗」等句式）。"
    "只输出 JSON 数组，不要任何其他文字：[{{\"q\": \"问题\", \"a\": \"标准答案\"}}]"
)


def gen_questions(surface, bottom, n=8):
    import urllib.request
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "只输出 JSON，不输出其他内容。"},
            {"role": "user", "content": f"汤面：{surface}\n\n汤底真相：{bottom}\n\n" + GEN_PROMPT.format(n=n)},
        ],
        "temperature": 0.7,
        "max_tokens": 1500,
    }
    req = urllib.request.Request(
        "https://api.siliconflow.cn/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.loads(r.read())
            text = d["choices"][0]["message"]["content"].strip()
            # 提取 JSON（容错：去掉 markdown 代码块）
            if text.startswith("```"):
                text = text.split("```")[1].lstrip("json").strip()
            start, end = text.find("["), text.rfind("]")
            if start >= 0 and end > start:
                items = json.loads(text[start:end + 1])
                return [x for x in items if isinstance(x, dict) and x.get("q") and x.get("a")]
            return []
        except Exception as e:  # noqa: BLE001
            print(f"  生成失败重试({attempt+1}): {e}")
            time.sleep(2)
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 道汤（0=全部）")
    ap.add_argument("--per", type=int, default=8, help="每汤生成题数")
    ap.add_argument("--only", default="", help="只处理指定汤（逗号分隔）")
    args = ap.parse_args()

    out_dir = BACKEND / "data" / "eval" / "natural_qa"
    out_dir.mkdir(parents=True, exist_ok=True)

    soups = [s for s in db.SOUPS if not s.hidden]
    if args.only:
        only_set = {x.strip() for x in args.only.split(",") if x.strip()}
        soups = [s for s in soups if s.title in only_set]
    if args.limit:
        soups = soups[: args.limit]

    report = {"total_soups": 0, "total_questions": 0, "correct": 0, "wrong": 0, "per_soup": []}
    for s in soups:
        qas = gen_questions(s.surface, s.bottom, args.per)
        if not qas:
            print(f"[无生成] {s.title}")
            continue
        soup_correct = 0
        wrongs = []
        for item in qas:
            q, exp = item["q"].strip(), item["a"].strip()
            try:
                res = ai_host.handle_host_response(s, [], q)
                reply = res.get("reply", "")
            except Exception as e:  # noqa: BLE001
                reply = f"<ERR:{e}>"
            exp_norm = norm_expected(exp)
            act_norm = extract_actual(reply)
            verdict = judge(exp_norm, act_norm)
            if verdict == "正确":
                soup_correct += 1
            else:
                wrongs.append({"q": q, "exp": exp, "act": reply[:40], "branch": res.get("matched_checkpoint"), "verdict": verdict})
            time.sleep(0.3)  # 免费模型限速
        total = len(qas)
        acc = soup_correct / total * 100 if total else 0
        report["total_soups"] += 1
        report["total_questions"] += total
        report["correct"] += soup_correct
        report["wrong"] += len(wrongs)
        report["per_soup"].append({"soup": s.title, "total": total, "correct": soup_correct, "acc": round(acc, 0), "wrongs": wrongs})
        print(f"[{s.title}] {soup_correct}/{total} = {acc:.0f}%  {'❌' if wrongs else '✅'}")

    # 落盘
    report["overall_acc"] = round(report["correct"] / report["total_questions"] * 100, 1) if report["total_questions"] else 0
    (out_dir / "natural_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n====================")
    print(f"汤数={report['total_soups']} 题数={report['total_questions']} 正确={report['correct']} 错误={report['wrong']}")
    print(f"真实答对率(自然问法)={report['overall_acc']}%")
    print(f"报告: {out_dir / 'natural_report.json'}")


if __name__ == "__main__":
    main()
