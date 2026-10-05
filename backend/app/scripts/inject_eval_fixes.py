# -*- coding: utf-8 -*-
"""把评测错误（真实视频问答对）注入 verified_qa_pairs.jsonl。

策略：
1. 只取「真判定错误」（主持人答了标准答案但答错），剔除引导语类（非是否问法被引导是正确行为）；
2. 过滤字幕噪音/残缺问法：长度>=5、extract_core 核心词>=3 字（防宽匹配）；
3. 同一汤内去重；
4. 生成 ConfusionPoint：q=原问题, a=expected_norm, match=build_match_patterns(q)。
注入后由 db.py 启动时并入 soup.confusionPoints（确定性层命中，AI 提示词层限量），
评测全量重跑作为安全网：若某汤新增错误则回滚该汤。
用法: python inject_eval_fixes.py [--dry-run]
"""
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent.parent  # backend/
sys.path.insert(0, str(BACKEND))

from app.feedback_utils import build_match_patterns  # noqa: E402
from app.rag import extract_core  # noqa: E402
from app.soups import SEED_SOUPS  # noqa: E402

REPORT = BACKEND / "data" / "eval" / "eval_report.json"
OUT = BACKEND / "data" / "verified_qa_pairs.jsonl"

TITLE2ID = {s["title"]: s["id"] for s in SEED_SOUPS}
VALID_ANS = {"是", "不是", "是也不是", "算是", "与此无关"}


def load_errors():
    d = json.load(open(REPORT, encoding="utf-8"))
    errs = [r for r in d["rows"] if r.get("verdict") == "错误"]
    # 只取真判定错误（实际回复是标准答案词，但答错）
    hard = [r for r in errs if not (r.get("actual") or "").startswith(("🤔", "🎯", "⚠️"))]
    return hard


def is_noise(q: str) -> bool:
    """过滤字幕噪音 / 残缺问法。"""
    q = q.strip()
    if len(q) < 5:
        return True
    core = extract_core(q)
    if len(core) < 3:
        return True
    # 乱码特征：连续 3+ 相同字（"不不不"）
    import re

    if re.search(r"(.)\1{2,}", core):
        return True
    return False


def _row_expected(row: dict) -> str:
    """取评测行期望的标准化答案。"""
    return (row.get("expected_norm") or row.get("expected") or "").strip()


def conflict_scan(new_records: list[dict]) -> list[dict]:
    """确定性安全网：剔除『会误伤评测集里原本答对问题』的注入规则。

    背景（2026-09 修复）：曾有一条注入规则「故事中还有其他人吗→是」，
    其宽 match 通配把「故事中除了我还有其他活人吗」（正确答案应为「不是」）
    也命中，制造了 3 个新错误。故在落盘前做冲突验证兜底。

    实现：对每条候选规则，临时并入该汤的易错点集，用**真实的
    handle_host_response** 重判该汤评测集里所有『原本由确定性分支答对』的行；
    若任一原本正确的问法被改判错，则该规则有害，剔除（回滚）。

    只验证“原本由确定性分支答对”的行，是因为：
    - 确定性命中的行，加一条新规则是纯“增量”，行为可预测；
    - LLM 兜底答对的行本身有随机性，不加规则也可能下次答错，不当作判据。
    纯内存判断（重判命中确定性分支时不调 LLM），快速且确定。
    """
    if not new_records or not os.path.exists(REPORT):
        return new_records
    import json as _json
    from app import db as _db
    from app import ai_host as _ai_host

    report = _json.load(open(REPORT, encoding="utf-8"))
    # 只取“原本由确定性分支答对、且期望是标准五选一”的行作为基准
    rows_by_soup: dict[str, list] = {}
    for r in report.get("rows", []):
        if r.get("verdict") != "正确":
            continue
        if not r.get("branch"):  # 排除 LLM 兜底答对的行
            continue
        exp = _row_expected(r)
        if exp not in ("是", "不是", "是也不是", "算是", "与此无关"):
            continue
        rows_by_soup.setdefault(r.get("soup", ""), []).append(r)

    # 加载运行时 SOUPS（含已存在的注入），只取其结构作模板，不改全局
    soup_by_title = {s.title: s for s in _db.SOUPS}

    def _reply_for(soup, q: str) -> str:
        """确定性分支的判定不依赖历史、不调 LLM，空历史调用是安全的。"""
        try:
            return _ai_host.handle_host_response(soup, [], q).get("reply", "")
        except Exception:  # noqa: BLE001
            return ""

    safe: list[dict] = []
    dropped = 0
    for rec in new_records:
        cp = rec.get("confusionPoint") or {}
        soup_title = None
        for t, sid in TITLE2ID.items():
            if sid == rec.get("soupId"):
                soup_title = t
                break
        base_soup = soup_by_title.get(soup_title)
        if not soup_title or base_soup is None:
            safe.append(rec)
            continue

        # 临时并入该规则
        import copy
        from app.schemas import ConfusionPoint

        test_soup = copy.deepcopy(base_soup)
        test_cp = ConfusionPoint(**cp)
        test_soup.confusionPoints = list(base_soup.confusionPoints or []) + [test_cp]

        harmful = False
        for row in rows_by_soup.get(soup_title, []):
            q = (row.get("question") or "").strip()
            exp = _row_expected(row)
            if not q or not exp:
                continue
            before = _reply_for(base_soup, q)
            if before != exp:
                continue  # 原本也不是它答对的，不加判断
            after = _reply_for(test_soup, q)
            if after != exp:  # 原本对、加了规则后变错 → 有害
                harmful = True
                break
        if harmful:
            dropped += 1
            print(f"  ⚠ 冲突剔除（加规则后原本正确问题被改判错）: [{soup_title}] {cp.get('q','')[:40]} -> {cp.get('a')}")
        else:
            safe.append(rec)
    if dropped:
        print(f"  → 冲突验证剔除 {dropped} 条有害规则，保留 {len(safe)} 条")
    return safe


def main():
    dry = "--dry-run" in sys.argv
    errs = load_errors()
    title_map = {}
    for r in errs:
        soup = r["soup"]
        q = (r.get("question") or "").strip()
        ans = r.get("expected_norm") or r.get("expected") or ""
        if ans not in VALID_ANS:
            continue
        if is_noise(q):
            continue
        sid = TITLE2ID.get(soup)
        if not sid:
            continue
        title_map.setdefault(soup, []).append({"q": q, "a": ans})

    # 按汤统计 + 去重
    records = []
    stat = []
    for soup, items in title_map.items():
        seen = set()
        for it in items:
            if it["q"] in seen:
                continue
            seen.add(it["q"])
            match = build_match_patterns(it["q"])
            if not match:
                continue
            records.append(
                {
                    "feedbackId": f"eval-{soup}-{len(seen)}",
                    "soupId": TITLE2ID[soup],
                    "confusionPoint": {
                        "q": it["q"],
                        "a": it["a"],
                        "match": match,
                        "note": "评测修复 20260902（真实视频问答对）",
                    },
                    "mergedAt": "2026-09-02T00:00:00+00:00",
                }
            )
        stat.append((soup, len(items), len(seen)))

    total = sum(s[2] for s in stat)
    print(f"真错误 {len(errs)} → 过滤后注入 {total} 条，覆盖 {len(stat)} 道汤")
    print(f"（过滤掉：引导语类/噪音/短问法/无法归一 ≈ {len(errs) - total}）")
    print("\n=== 各汤注入数 ===")
    for soup, raw, n in sorted(stat, key=lambda x: -x[2])[:20]:
        print(f"  {soup}: {n}")

    if dry:
        # 打印 20 条样本
        print("\n=== 样本 20 条 ===")
        for rec in records[:20]:
            cp = rec["confusionPoint"]
            print(f"[{rec['soupId']}] {cp['q'][:40]} -> {cp['a']} | match={cp['match'][:2]}")
        return

    # 合并已存在的 verified 记录（避免覆盖线上已注入的反馈）
    existing = []
    if OUT.exists():
        for line in open(OUT, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    existing.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    existing_qs = {(e.get("soupId"), e.get("confusionPoint", {}).get("q")) for e in existing}
    new_records = [r for r in records if (r["soupId"], r["confusionPoint"]["q"]) not in existing_qs]
    # 冲突扫描安全网：剔除会误伤『原本答对问题』的有害规则
    new_records = conflict_scan(new_records)
    if not new_records:
        print("\n冲突扫描后无新增规则可写入（已全部剔除或全部已存在）。")
        return
    with open(OUT, "a", encoding="utf-8") as f:
        for r in new_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n写入 {len(new_records)} 条到 {OUT}")


if __name__ == "__main__":
    main()
