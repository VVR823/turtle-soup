"""运行 trace 日志：记录 AI 主持人每道题的判定路径，便于排查与复盘。

设计原则（贴着海龟汤项目）：
- 零侵入：只在 main.py 调用 handle_host_response 之后挂一层 record()，不改动任何判定逻辑。
- 不改变业务：异常只报告固定故障码与关联哈希，绝不重新答题或扣次。
- 按 session 分文件：backend/data/traces/{session_id}.jsonl，每行一条 JSON。
- 自动轮转：单文件超过 5MB 自动改名备份，避免磁盘无限增长。
- 私密诊断：包含玩家问题/展示回复，默认关闭；.gitignore 不是安全隔离或脱敏。
- 请求审计独立于此开关，不复制这里的文本。
"""
import json
import threading
import hashlib
import sys
from datetime import datetime
from .runtime import get_runtime
from .schemas import HostResult
_MAX_BYTES = 5 * 1024 * 1024  # 单文件 5MB 上限后轮转
_lock = threading.Lock()


def _classify(host: HostResult) -> str:
    """把 matched_checkpoint 归成大类，方便后续统计命中分布。

    branch 为 None 时有两种情况需区分：
    - 玩家问了非是否类问题（reply 带 ⚠️/🤔/🎯/🤖 前缀）→ 流程提醒，不消耗次数
    - 其余 → 真正走了 LLM 兜底
    """
    if host.kind == "system_error":
        return "模型异常"
    if host.kind == "reminder":
        return "非是否类/提醒"
    if host.source == "llm":
        return "LLM兜底"
    branch = host.matchedCheckpoint
    if branch is None:
        return "未分类确定性判定"
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


def record(session_id: str, soup_id: str, question: str, host_result: HostResult) -> None:
    """记录私密诊断；失败可见但不影响已提交的业务结果。"""
    runtime = get_runtime()
    if not runtime.settings.ENABLE_TRACE or not session_id:
        return
    try:
        TRACE_DIR = runtime.settings.DATA_DIR / "traces"
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        line = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "session_id": session_id,
            "soup_id": soup_id,
            "question": question,
            "branch": host_result.get("matched_checkpoint"),
            "category": _classify(host_result),
            "reply": host_result.get("reply"),
            "is_win": host_result.get("is_win", False),
            "is_reveal": host_result.get("is_reveal", False),
            "kind": host_result.kind,
            "source": host_result.source,
            "answer": host_result.answer,
            "chargeable": host_result.chargeable,
            "errorCode": host_result.errorCode,
            "versions": host_result.versions.model_dump(mode="json"),
        }
        path = TRACE_DIR / f"{session_id}.jsonl"
        # 单文件超上限则轮转备份，避免无限增长
        if path.exists() and path.stat().st_size > _MAX_BYTES:
            path.rename(path.with_suffix(f".{int(datetime.now().timestamp())}.jsonl.bak"))
        with _lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:
        from .audit_context import current_attempt
        collector = current_attempt()
        if collector is not None:
            collector.note_metadata_gap()
        print("diagnostic_trace_failed session_hash=" + hashlib.sha256(session_id.encode()).hexdigest()[:16], file=sys.stderr)
