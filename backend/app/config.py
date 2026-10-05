"""配置加载：模型供应商与 API Key 等环境变量。

支持多种供应商（LLM_PROVIDER 切换）：
- ollama（默认）：本地 Ollama，0 成本，OpenAI 兼容端点 http://localhost:11434/v1
- zhipu（智谱 AI，推荐）：GLM-4-Flash 永久免费，无需充值
- siliconflow（硅基流动）：部分 ≤9B 模型免费
- 其它值：走通用 OpenAI 兼容云端（如通义/DeepSeek），需自备 Key

优先读取 backend/.env，若未配置则回退读取项目根目录的 .env.local。
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# backend 目录：backend/app/config.py -> backend/app -> backend
BACKEND_DIR = Path(__file__).resolve().parent.parent
# 项目根目录：turtle-soup/
PROJECT_ROOT = BACKEND_DIR.parent

# 先加载 backend/.env（如果存在），再回退到项目根的 .env.local（不覆盖已存在的变量）
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env.local", override=False)


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default)


# 模型供应商：ollama（本地，0成本，默认） / cloud（云端 API，如通义/智谱/DeepSeek）
LLM_PROVIDER: str = _get("LLM_PROVIDER", "ollama")

# —— 本地 Ollama（默认，0 成本）——
# OpenAI 兼容端点固定在本地 11434；api_key 仅作占位（Ollama 不校验）
OLLAMA_BASE_URL: str = _get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL: str = _get("OLLAMA_MODEL", "qwen2.5:7b")

# —— 云端（可选，额度耗尽 / 上线时用）——
QWEN_API_KEY: str = _get("QWEN_API_KEY")
QWEN_BASE_URL: str = _get("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
QWEN_MODEL: str = _get("QWEN_MODEL", "qwen-turbo")

# —— 硅基流动 SiliconFlow（可选，推荐：部分 ≤9B 开源模型永久免费）——
# 平台地址 https://siliconflow.cn ；OpenAI 兼容端点。
# 选带「免费/free」标签的小模型（如 Qwen/Qwen2.5-7B-Instruct），即 0 成本、不消耗赠送额度。
SILICONFLOW_API_KEY: str = _get("SILICONFLOW_API_KEY")
SILICONFLOW_BASE_URL: str = _get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
SILICONFLOW_MODEL: str = _get("SILICONFLOW_MODEL", "Qwen/Qwen2.5-7B-Instruct")

# —— 智谱 AI（推荐：GLM-4-Flash 永久免费，注册实名即可用，无需充值）——
# 平台地址 https://open.bigmodel.cn ；OpenAI 兼容端点。
# LLM_PROVIDER=zhipu 时使用。GLM-4-Flash 永久免费、128K 上下文、30 并发，能力优于 Qwen2.5-7B。
ZHIPU_API_KEY: str = _get("ZHIPU_API_KEY")
ZHIPU_BASE_URL: str = _get("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
ZHIPU_MODEL: str = _get("ZHIPU_MODEL", "glm-4-flash")

# 允许跨域的前端来源（部署时通过环境变量 CORS_ORIGINS 传入，逗号分隔；
# 例如 "https://xxx.vercel.app,https://xxx.onrender.com"。
# 未设置时回退到本地开发默认值）。
_cors_raw = _get("CORS_ORIGINS", "")
CORS_ORIGINS: list[str] = (
    [o.strip() for o in _cors_raw.split(",") if o.strip()]
    if _cors_raw
    else [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
)

# 站点访问口令（可选）：设置后，所有 /api/*（除 /health、/api/config）都需要
# 请求头 X-Site-Token 与其一致，才能调用（主要拦截 /api/chat 的付费 LLM 额度被白嫖）。
# 留空 = 不开启口令（开发期友好）。
SITE_PASSWORD: str = _get("SITE_PASSWORD", "")

# 反馈管理后台口令（独立于站点访问口令）：设置后，调用 GET /api/feedback/admin
# 必须带一致的 X-Admin-Token 才能查看全部玩家反馈。玩家即便拿到站点口令也看不到。
# 默认留空 = 管理后台关闭（main.py 对未配置的 ADMIN_TOKEN 一律返回 503，避免误开放）。
# 需要启用管理后台时，在 backend/.env 里设置一个强口令（加一行 ADMIN_TOKEN=xxx）。
ADMIN_TOKEN: str = _get("ADMIN_TOKEN", "")

# 接口限流总开关（默认开）。本地跑回归测试/开发调试时设 0 关闭。
RATE_LIMIT_ENABLED: bool = _get("RATE_LIMIT_ENABLED", "1") == "1"

# 运行 trace 日志开关（默认开）：每次主持人的判定结果（走了哪条分支、最终答案）
# 会落盘到 backend/data/traces/{session_id}.jsonl，便于线上排查答错原因、复盘决策路径。
# 设 0 可关闭以节省磁盘。trace 不记录任何密钥，仅记录问题文本与判定分支。
ENABLE_TRACE: bool = _get("ENABLE_TRACE", "1") == "1"
