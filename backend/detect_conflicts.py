"""新汤易错点冲突检测（静态 + 运行模拟，零第三方依赖，纯标准库）。

原理：每道汤的每条 confusionPoint 都带一个"标准问法" cp['q']。
玩家按这个问法提问时，主持人应该命中这条 cp 本身、答出作者标的 a。
但若另一条 cp 的正则"字面更具体"、把这句话抢走了，且答案不同 —— 就是标答打架冲突。

复刻 ai_host.match_confusion_point 的纯逻辑（不 import 整个 ai_host，避免拖进 LLM 链）。
"""
import sys
import re
import json
import difflib

sys.path.insert(0, "app")
from soups import SEED_SOUPS  # dict 列表

# ---------- 复刻 ai_host 的纯匹配逻辑（与 ai_host.py:439 一致） ----------
def _pattern_literal_len(pat: str) -> int:
    specials = set(".*+?|()^{}$")
    count = 0
    i = 0
    n = len(pat)
    while i < n:
        ch = pat[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "[":
            j = pat.find("]", i)
            i = n if j == -1 else j + 1
            continue
        if ch == "{":
            j = pat.find("}", i)
            i = n if j == -1 else j + 1
            continue
        if ch == "(":
            j = pat.find(")", i)
            i = n if j == -1 else j + 1
            continue
        if ch in specials:
            i += 1
            continue
        count += 1
        i += 1
    return count


def split_clauses(question: str):
    clauses = [c.strip() for c in re.split(r"[，。,；;、]", question) if c.strip()]
    return clauses if clauses else [question]


def _sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _cp_targets_whole_question(cp: dict, question: str) -> bool:
    q = question.strip()
    cq = (cp.get("q") or "").strip()
    if not cq:
        return False
    if cq == q or cq in q or q in cq:
        return True
    return _sim(q, cq) >= 0.85


def match_confusion_point(soup: dict, question: str):
    cps = soup.get("confusionPoints") or []
    best_cp = None
    best_score = (-1, -1)
    clauses = split_clauses(question)
    for clause in clauses:
        for cp in cps:
            for pat in (cp.get("match") or []):
                try:
                    m = re.search(pat, clause)
                except re.error:
                    continue
                if not m:
                    continue
                literal = _pattern_literal_len(pat)
                span = m.end() - m.start()
                score = (literal, span)
                if score > best_score:
                    best_score = score
                    best_cp = cp
    if not best_cp:
        for cp in cps:
            if _cp_targets_whole_question(cp, question):
                best_cp = cp
                break
    return best_cp


# ---------- 主检测 ----------
NEW_IDS = {
    "16ceng-gongyu", "aji-hua", "baba", "caimingzi", "chengfa-tongzhidan", "chongying",
    "chu-lazhu", "cunzhong-guishi", "daojiqi-7tian", "gaiwolaile", "hongyi", "huiguniang-guize",
    "huxi", "juren", "maihuocha", "manderla", "mengyan-caiwu", "muzhe", "piaoliuping",
    "qiguai-bama", "qimo-kaoshi", "santian", "sushe-guize", "tonghua-xiaozhen", "xiangcun-guai",
    "xiaobudian", "xiongmei", "xueyuan-guize", "xunren-qishi", "yeye-dihou", "zhuchiren-shouce",
}

report = []
for d in SEED_SOUPS:
    cps = d.get("confusionPoints") or []
    if not cps:
        continue
    conflicts = []
    for cp_i in cps:
        best = match_confusion_point(d, cp_i["q"])
        if best is None:
            conflicts.append({
                "type": "self_miss",
                "q": cp_i["q"],
                "a": cp_i["a"],
                "note": cp_i.get("note"),
                "msg": "这条易错点的标准问法，自己的 match 正则一个都匹配不上（正则写漏/写错）",
            })
        elif best is not cp_i:
            if best["a"] == cp_i["a"]:
                continue  # 答案相同，被抢走也不影响回答，无害，跳过
            conflicts.append({
                "type": "stolen",
                "q": cp_i["q"],
                "a": cp_i["a"],
                "note": cp_i.get("note"),
                "hit_q": best["q"],
                "hit_a": best["a"],
                "hit_note": best.get("note"),
                "msg": f"玩家按这个问法问，会被另一条更‘具体’的易错点抢答：本应答「{cp_i['a']}」，实际答「{best['a']}」",
            })
    if conflicts:
        report.append({
            "id": d["id"],
            "title": d["title"],
            "is_new": d["id"] in NEW_IDS,
            "cp_total": len(cps),
            "conflict_count": len(conflicts),
            "conflicts": conflicts,
        })


# ---------- 第二层：同事实异答（两条问法去虚词后高度相似，却答案不同） ----------
# 复现“爷爷的低吼”类冲突：同一件事三种问法三种答案。
STOP = set("吗呢了的是不你我说他她它请问有没有是否到底究竟真的其实那个这哪谁什么怎么为何什")


def core(q: str) -> str:
    return "".join(ch for ch in q if ch not in STOP)


same_fact_report = []
for d in SEED_SOUPS:
    cps = d.get("confusionPoints") or []
    n = len(cps)
    if n < 2:
        continue
    hits = []
    for i in range(n):
        for j in range(i + 1, n):
            if cps[i]["a"] == cps[j]["a"]:
                continue
            ca, cb = core(cps[i]["q"]), core(cps[j]["q"])
            if not ca or not cb:
                continue
            if _sim(ca, cb) >= 0.8:
                hits.append({
                    "q1": cps[i]["q"], "a1": cps[i]["a"],
                    "q2": cps[j]["q"], "a2": cps[j]["a"],
                    "msg": f"两条问法指向同一事实却答案不同：『{cps[i]['q']}』→{cps[i]['a']}  vs  『{cps[j]['q']}』→{cps[j]['a']}",
                })
    if hits:
        same_fact_report.append({
            "id": d["id"], "title": d["title"],
            "is_new": d["id"] in NEW_IDS, "hits": hits,
        })

new_conf = [r for r in report if r["is_new"]]
old_conf = [r for r in report if not r["is_new"]]
print(f"=== 扫描 {len(SEED_SOUPS)} 道汤，发现 {len(report)} 道存在易错点冲突 ===")
print(f"  新汤（31 道内）冲突：{len(new_conf)} 道")
print(f"  老汤（顺带扫描）冲突：{len(old_conf)} 道")
print()
for r in new_conf:
    print(f"### [{r['id']}] {r['title']}  （共 {r['cp_total']} 条易错点，{r['conflict_count']} 处冲突）")
    for c in r["conflicts"]:
        if c["type"] == "stolen":
            print(f"  [抢答] 问「{c['q']}」本应答「{c['a']}」 -> 被「{c['hit_q']}」抢走答「{c['hit_a']}」")
        else:
            print(f"  [自失配] 问「{c['q']}」标答「{c['a']}」但 match 正则一个都匹配不上")
    print()

with open("conflict_report.json", "w", encoding="utf-8") as f:
    json.dump({"stolen": new_conf + old_conf, "same_fact": same_fact_report}, f, ensure_ascii=False, indent=2)
print("已写出 conflict_report.json")

print()
print("=" * 30)
print("第二层：同事实异答（含爷爷汤类）")
print("=" * 30)
sf_new = [r for r in same_fact_report if r["is_new"]]
sf_old = [r for r in same_fact_report if not r["is_new"]]
print(f"  新汤：{len(sf_new)} 道 | 老汤：{len(sf_old)} 道")
for r in same_fact_report:
    tag = "【新】" if r["is_new"] else "【旧】"
    print(f"\n{tag} [{r['id']}] {r['title']}  （{len(r['hits'])} 对冲突）")
    for h in r["hits"]:
        print(f"  × {h['msg']}")
