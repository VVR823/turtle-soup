"""线上验证用户截图的复合陈述"""
import sys
import requests

BASE = 'http://47.97.33.174'
TOKEN = 'wenyu2026'

q = "主角被妻子催眠、小珊是主角的情人/出轨对象、妻子是催眠师、幽灵不是真幽灵，是催眠幻象、星期一/星期二是梦境"

sid = requests.post(
    f'{BASE}/api/chat',
    headers={'X-Site-Token': TOKEN},
    json={'soupId': 'zhimengzhe', 'level': 'tianyi'},
    timeout=30,
).json()['sessionId']

r = requests.post(
    f'{BASE}/api/chat',
    headers={'X-Site-Token': TOKEN},
    json={'sessionId': sid, 'question': q},
    timeout=30,
).json()

print("输入:", q)
print("回复:", r.get('reply'))
print("matchedCheckpoint:", r.get('matchedCheckpoint'))

if r.get('reply') == '是':
    print("✅ 已修复")
    sys.exit(0)
else:
    print("❌ 未修复")
    sys.exit(1)
