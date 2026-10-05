# 线上验证脚本（部署后手动跑）

这些脚本直接请求**线上服务器**（`http://47.97.33.174`，带 `X-Site-Token: wenyu2026`），
不属于日常 pytest 套件（pytest 收集时会忽略本目录——conftest 里用 `collect_ignore` 排除）。

日常 QA 回归（织梦者/信/新人/双鱼/旅馆等）已全部转为 `tests/` 下的 pytest 用例，
本目录只保留"必须打真实线上"的验证脚本。

```bash
# 在 backend/ 下，用 venv 逐个跑（需要真实网络 + 线上服务存活）：
venv/Scripts/python.exe tests/online/test_online_compound.py
venv/Scripts/python.exe tests/online/test_online_shuangyu.py
venv/Scripts/python.exe tests/online/debug_win.py
```

| 脚本 | 验证内容 |
| --- | --- |
| test_online_compound.py | 线上织梦者复合陈述判定 |
| test_online_shuangyu.py | 线上双鱼贴汤底完成度 |
| debug_win.py | 线上新世界通关条件（isWin + 100%） |
