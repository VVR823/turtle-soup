"""LLM 兜底能力对比：同一批「玩家自然问法」，测三个模型的判定准确率。
题目是评测集之外的真实玩家问法，标准答案按汤底人工标注。"""
import json
import time
import urllib.request

API_KEY = None
# 从 backend/.env 读 key
with open(r"D:/CODE/turtle-soup/backend/.env", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line.startswith("SILICONFLOW_API_KEY="):
            API_KEY = line.split("=", 1)[1].strip()

MODELS = {
    "Qwen2.5-7B(现用,免费)": "Qwen/Qwen2.5-7B-Instruct",
    "Qwen3-8B(免费候选)": "Qwen/Qwen3-8B",
    "DeepSeek-V3(付费候选)": "deepseek-ai/DeepSeek-V3",
}

# (汤名, 玩家问法, 标准答案) —— 标准答案按汤底人工标注
CASES = [
    ("张三李四", "李四的时间是倒着走的吗", "是"),
    ("张三李四", "故事里有穿越元素吗", "是"),
    ("张三李四", "有平行世界吗", "不是"),
    ("张三李四", "天花板上的字是未来的自己写的吗", "是"),
    ("张三李四", "张三和李四是同一个人吗", "不是"),
    ("双鱼", "主角是从未来穿越回来的吗", "是"),
    ("双鱼", "玉佩能复制人吗", "是"),
    ("双鱼", "妈妈是正常人吗", "不是"),
    ("七宗罪", "故事里有恶魔吗", "是"),
    ("七宗罪", "这是本格推理吗", "不是"),
    ("爷爷的低吼", "爷爷是死了吗", "是也不是"),
    ("爷爷的低吼", "爷爷是活死人吗", "是"),
    ("盲人", "主角是盲人吗", "是"),
    ("盲人", "主角是被贼杀死的吗", "不是"),
    ("盲人", "狗在吃主角的尸体吗", "是"),
    ("旅馆", "旅馆里只有七个人吗", "是"),
    ("旅馆", "这是变格吗", "不是"),
    ("二十", "闺蜜是被丈夫杀的吗", "是"),
    ("二十", "故事里有魔法吗", "是"),
    ("二十", "哭声是生物发出的吗", "不是"),
    ("美人鱼", "故事里真的发生了魔法吗", "不是"),
    ("美人鱼", "这是变格吗", "不是"),
    ("信", "信是主角写的吗", "是"),
    ("噩梦重现", "父母是被复仇者杀的吗", "是"),
]

SYSTEM_PROMPT = "你是海龟汤主持人。玩家向你提问，你根据汤底真相，只能回答：是、不是、是也不是、算是、与此无关。绝不能透露汤底。只输出一个词。"


def load_soup(title):
    import sys
    sys.path.insert(0, r"D:/CODE/turtle-soup/backend")
    from app.soups import SEED_SOUPS
    return next(s for s in SEED_SOUPS if s["title"] == title)


def ask(model, surface, bottom, question):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"汤面：{surface}\n\n汤底真相（保密）：{bottom}\n\n玩家的提问：{question}"},
        ],
        "temperature": 0.1,
        "max_tokens": 20,
    }
    req = urllib.request.Request(
        "https://api.siliconflow.cn/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read())
    return d["choices"][0]["message"]["content"].strip()


def norm(ans):
    a = (ans or "").strip().lower()
    if "是也不是" in a or "一半" in a or "部分" in a:
        return "是也不是"
    if "算是" in a or "基本" in a or "差不多" in a:
        return "算是"
    if "与此无关" in a or "无关" in a or "不确定" in a:
        return "与此无关"
    if "不是" in a or "不对" in a or "否" in a:
        return "不是"
    if a.startswith("是"):
        return "是"
    return a


results = {k: {"correct": 0, "total": 0, "detail": []} for k in MODELS}
for title, q, exp in CASES:
    s = load_soup(title)
    for label, model in MODELS.items():
        try:
            raw = ask(model, s["surface"][:200], s["bottom"][:800], q)
            ans = norm(raw)
        except Exception as e:  # noqa: BLE001
            raw, ans = f"<ERR {e}>", "ERR"
        ok = ans == exp
        results[label]["total"] += 1
        if ok:
            results[label]["correct"] += 1
        results[label]["detail"].append((title, q, exp, ans, raw[:20]))
        time.sleep(0.4)  # 免费模型限速

print("=" * 60)
for label, r in results.items():
    acc = r["correct"] / r["total"] * 100 if r["total"] else 0
    print(f"{label}: {r['correct']}/{r['total']} = {acc:.0f}%")
print("=" * 60)
for label, r in results.items():
    print(f"\n--- {label} 错题 ---")
    for title, q, exp, ans, raw in r["detail"]:
        if ans != exp:
            print(f"  [{title}] {q} | 期望{exp} -> 答{ans} ({raw})")
