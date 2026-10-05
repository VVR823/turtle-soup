#!/usr/bin/env python3
"""把管理员审批通过的反馈合并到主持人知识库。

每晚 0 点由 crontab 调用一次：
    0 0 * * * cd /opt/turtle-soup/backend && /opt/turtle-soup/backend/venv/bin/python -m app.scripts.merge_verified_qa

逻辑：
1. 读取 feedback.jsonl，筛选 status=approved 且 mergedAt 为空的记录；
2. 把 expectedAnswer 标准化为 5 种标准答案之一；
3. 生成 ConfusionPoint 并追加到 data/verified_qa_pairs.jsonl；
4. 回写 feedback.jsonl，标记 mergedAt（避免重复合并）。

重启后端或 db.py 启动时会自动把 verified_qa_pairs.jsonl 注入到对应 soup.confusionPoints。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# 让脚本无论是 `python -m app.scripts.merge_verified_qa` 还是直接运行都能 import app.*
backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.feedback_utils import build_match_patterns, normalize_expected_answer  # noqa: E402


def _load_jsonl(path: str) -> list[dict]:
    records = []
    if not os.path.exists(path):
        return records
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _save_jsonl(path: str, records: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp_path, path)


def _build_confusion_point(record: dict) -> dict | None:
    """把一条 approved 反馈转成 ConfusionPoint。"""
    q = (record.get("question") or "").strip()
    expected = (record.get("expectedAnswer") or "").strip()
    if not q or not expected:
        return None

    answer = normalize_expected_answer(expected)
    if answer is None:
        # 无法自动标准化：把原样作为 note，但不生成可命中规则，避免污染主持人判断
        return None

    match_patterns = build_match_patterns(q)
    note = f"玩家反馈 #{record.get('id', '')[:8]}"
    reason = record.get("reason")
    if reason:
        note += f"：{reason}"

    return {
        "q": q,
        "a": answer,
        "match": match_patterns,
        "note": note,
    }


def run_merge(feedback_path: str, verified_qa_path: str) -> int:
    """执行合并。返回本次新合并的条数。"""
    feedbacks = _load_jsonl(feedback_path)
    verified = _load_jsonl(verified_qa_path)
    existing_feedback_ids = {v.get("feedbackId") for v in verified}

    merged_count = 0
    now = datetime.now(timezone.utc).isoformat()

    for r in feedbacks:
        if r.get("status") != "approved":
            continue
        if r.get("mergedAt"):
            continue
        fid = r.get("id")
        if not fid or fid in existing_feedback_ids:
            continue

        cp = _build_confusion_point(r)
        if cp is None:
            continue

        verified.append(
            {
                "feedbackId": fid,
                "soupId": r.get("soupId"),
                "confusionPoint": cp,
                "mergedAt": now,
            }
        )
        r["mergedAt"] = now
        r["mergedAnswer"] = cp["a"]
        merged_count += 1

    if merged_count:
        _save_jsonl(verified_qa_path, verified)
        _save_jsonl(feedback_path, feedbacks)
        # 合并后必须重启后端，否则内存里的 SOUPS 不会重新加载 verified_qa_pairs。
        # 本地开发环境无 systemctl 会静默失败，不影响手动测试。
        try:
            subprocess.run(
                ["systemctl", "restart", "turtle-backend"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:  # noqa: BLE001
            pass

    return merged_count


def cleanup_old_sessions(days_ended: int = 7, days_stale_playing: int = 30) -> int:
    """清理旧会话数据（sessions.db 只增不减，无功能在读，纯死数据）。

    - 已结束（solved/given_up）：以其**结束时间**（solved_at/given_up_at）为准，
      超过 days_ended 天 → 删（不能用 created_at：一个 40 天前创建、今天刚结束的
      会话，created_at 虽旧但玩家可能还在看，用创建时间会误删）；
    - playing 但超过 days_stale_playing 天没动静的僵尸会话（玩家中途关页面）→ 删；
    - 正在玩的新会话不受影响。
    先删关联 messages 再删 sessions（表无外键级联）。
    返回删除的会话数。不触发后端重启（数据独立，get_session 实时读库）。
    """
    db_file = backend_dir / "data" / "sessions.db"
    if not os.path.exists(db_file):
        return 0
    import sqlite3
    import time

    now = time.time()
    ended_cutoff = now - days_ended * 86400
    stale_cutoff = now - days_stale_playing * 86400
    conn = sqlite3.connect(db_file, timeout=10)
    try:
        with conn:
            # 已结束会话：结束时间（优先 solved_at，其次 given_up_at）早于 ended_cutoff 才删
            conn.execute(
                """DELETE FROM messages WHERE session_id IN (
                    SELECT id FROM sessions WHERE
                        (status IN ('solved','given_up')
                         AND COALESCE(solved_at, given_up_at, created_at) < ?)
                        OR (status = 'playing' AND created_at < ?)
                )""",
                (ended_cutoff, stale_cutoff),
            )
            cur = conn.execute(
                """DELETE FROM sessions WHERE
                    (status IN ('solved','given_up')
                     AND COALESCE(solved_at, given_up_at, created_at) < ?)
                    OR (status = 'playing' AND created_at < ?)""",
                (ended_cutoff, stale_cutoff),
            )
        return cur.rowcount
    finally:
        conn.close()


def main() -> int:
    """命令行入口：默认路径指向 backend/data/。"""
    here = Path(__file__).resolve().parent.parent.parent
    feedback_path = str(here / "data" / "feedback.jsonl")
    verified_path = str(here / "data" / "verified_qa_pairs.jsonl")
    count = run_merge(feedback_path, verified_path)
    cleaned = cleanup_old_sessions()
    print(f"[{datetime.now(timezone.utc).isoformat()}] 合并完成：新增 {count} 条已验证 QA 对；清理旧会话 {cleaned} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
