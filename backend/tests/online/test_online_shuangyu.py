"""线上验证双鱼贴汤底完成度（部署后）"""
import sys, json, urllib.request
sys.path.insert(0, "D:/CODE/turtle-soup/backend")
from app.soups import SEED_SOUPS

soup = next(s for s in SEED_SOUPS if s["id"] == "shuangyu-yupei")
summary = soup["bottomSummary"]

base = "http://47.97.33.174/api"
headers = {"X-Site-Token": "wenyu2026", "Content-Type": "application/json"}

def post(path, data):
    req = urllib.request.Request(base + path, data=json.dumps(data).encode(), headers=headers, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())

r = post("/chat", {"soupId": "shuangyu-yupei", "level": "xuermu"})
sid = r["sessionId"]
print("会话:", sid)

# 模拟玩家把完整汤底贴进聊天框
r2 = post("/chat", {"sessionId": sid, "question": summary})
print("贴汤底回复(前40):", r2["reply"][:40], "| 免费提醒:", r2.get("isFreeReminder"))

ev = post("/evaluate", {"sessionId": sid})
print("完成度:", ev.get("completion"))
print("已覆盖:", ev.get("keyPointsCovered"))
print("缺失:", ev.get("keyPointsMissing"))

# 顺便验证几个主持人题无回归
for q in ["故事中存在外星人或者高维生物吗", "爸妈是被杀的吗", "04年的妻子死了吗"]:
    rr = post("/chat", {"soupId": "shuangyu-yupei", "level": "xuermu", "question": q})
    print(f"  [{q}] -> {rr['reply']}")
