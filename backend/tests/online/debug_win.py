"""验证新世界(winshijie)隐藏彩蛋通关条件。
走真实 /api/chat + /api/evaluate 流程，确认 isWin + 100% 通关。
"""
import urllib.request, json

LOCAL = "http://localhost:8000/api"
ONLINE = "http://47.97.33.174/api"
BASE = ONLINE  # 优先线上；改 LOCAL 可本地验证
TOKEN = {"X-Site-Token": "wenyu2026", "Content-Type": "application/json"}


def create():
    req = urllib.request.Request(BASE + "/chat", data=json.dumps(
        {"soupId": "xinshijie", "level": "xuermu"}).encode(), headers=TOKEN, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=10).read().decode())["sessionId"]


def ask(sid, q):
    req = urllib.request.Request(BASE + "/chat", data=json.dumps(
        {"sessionId": sid, "question": q}).encode(), headers=TOKEN, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())


def evaluate(sid):
    req = urllib.request.Request(BASE + "/evaluate", data=json.dumps(
        {"sessionId": sid}).encode(), headers=TOKEN, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())


def show(label, r):
    print(f"  [{label}] isWin={r.get('isWin')} isReveal={r.get('isReveal')} reply={r.get('reply')[:40]!r}")


print("== 用例1：命中通关条件（织梦者 + 还在梦里）==")
sid = create()
r = ask(sid, "我是不是还在织梦者的那个梦里")
show("win-question", r)
ev = evaluate(sid)
print(f"  复盘 completion={ev['completion']}% evaluation={ev['evaluation'][:30]!r}")

print("\n== 用例2：仅提织梦者，未提还在梦里（不应通关）==")
sid = create()
r = ask(sid, "织梦者是谁写的汤")
show("no-win", r)
print(f"  reply 全文: {r.get('reply')!r}")

print("\n== 用例3：仅提还在梦里，未提织梦者（不应通关）==")
sid = create()
r = ask(sid, "我是不是还在梦里")
show("no-win2", r)

print("\n== 用例4：其他变体（一直都在织梦者的梦里）==")
sid = create()
r = ask(sid, "我是不是一直都困在织梦者的梦境里")
show("win-variant", r)
ev = evaluate(sid)
print(f"  复盘 completion={ev['completion']}%")
