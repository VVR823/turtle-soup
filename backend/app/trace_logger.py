"""运行 trace 日志：记录 AI 主持人每道题的判定路径，便于排查与复盘。

设计原则（贴着海龟汤项目）：
- 零侵入：只在 main.py 调用 handle_host_response 之后挂一层 record()，不改动任何判定逻辑。
- 零副作用：任何异常都被静默吞掉，绝不影响主流程（答题 / 扣次 / 缓存）。
- 按 session 分文件：backend/data/traces/{session_id}.jsonl，每行一条 JSON。
- 自动轮转：单文件超过 5MB 自动改名备份，避免磁盘无限增长。
- 不含密钥：只记问题文本、判定分支、最终答案，玩家数据不外泄（目录已被 .gitignore 忽略）。
"""
import json
import threading
from datetime import datetime
from pathlib import Path

from .config import BACKEND_DIR, ENABLE_TRACE

TRACE_DIR = BACKEND_DIR / "data" / "traces"
_MAX_BYTES = 5 * 1024 * 1024  # 单文件 5MB 上限后轮转
_lock = threading.Lock()


def _classify(branch: str | None, reply: str = "") -> str:
    """把 matched_checkpoint 归成大类，方便后续统计命中分布。

    branch 为 None 时有两种情况需区分：
    - 玩家问了非是否类问题（reply 带 ⚠️/🤔/🎯/🤖 前缀）→ 流程提醒，不消耗次数
    - 其余 → 真正走了 LLM 兜底
    """
    if branch is None:
        if reply and (
            reply.startswith("⚠️")
            or reply.startswith("🤔")
            or reply.startswith("🎯")
            or reply.startswith("🤖")
        ):
            return "非是否类/提醒"
        return "LLM兜底"
    if "win" in branch or branch == "always_yes":
        return "彩蛋/特殊汤"
    if "复合" in branch or "易错" in branch:
        return "易错点/复合"
    if "类型判定" in branch:
        return "本格变格"
    if "人数判定" in branch:
        return "人数"
    if branch in ("reveal_attempt_reminder", "progress_hint"):
        return "流程兜底"
    return "RAG/Checkpoint"


def record(session_id: str, soup_id: str, question: str, host_result: dict) -> None:
    """记录一次主持人判定结果。失败静默，绝不影响主流程。"""
    if not ENABLE_TRACE or not session_id:
        return
    try:
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        line = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "session_id": session_id,
            "soup_id": soup_id,
            "question": question,
            "branch": host_result.get("matched_checkpoint"),
            "category": _classify(host_result.get("matched_checkpoint"), host_result.get("reply")),
            "reply": host_result.get("reply"),
            "is_win": host_result.get("is_win", False),
            "is_reveal": host_result.get("is_reveal", False),
        }
        path = TRACE_DIR / f"{session_id}.jsonl"
        # 单文件超上限则轮转备份，避免无限增长
        if path.exists() and path.stat().st_size > _MAX_BYTES:
            path.rename(path.with_suffix(f".{int(datetime.now().timestamp())}.jsonl.bak"))
        with _lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:
        # trace 故障绝不应影响玩家答题
        pass
