"""Session 存储（SQLite，标准库 sqlite3，零外部依赖）。

soup 题库来自内置 SEED_SOUPS（常驻内存）+ generated_soups.json（启动时读取）；
session 问答记录持久化到 backend/data/sessions.db（SQLite）。

为什么用 SQLite 而不是 JSON 文件：
- JSON 存储每次读写都是"全量读 → 改 → 全量写"，并发请求会互相覆盖丢数据；
- SQLite 天然支持事务与行级写锁，单进程多请求下安全，且是 Python 标准库，零依赖。
"""
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

from .schemas import ConfusionPoint, Soup
from .soups import SEED_SOUPS

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
DB_FILE = DATA_DIR / "sessions.db"
# 旧版 JSON 存储（首次启动自动迁移进 SQLite 后改名为 .bak）
LEGACY_SESSIONS_FILE = DATA_DIR / "sessions.json"
# 自动抽取脚本（preprocess_soup.py）生成的汤品，收录新汤无需改代码
GENERATED_FILE = DATA_DIR / "generated_soups.json"
VERIFIED_QA_FILE = DATA_DIR / "verified_qa_pairs.jsonl"


def ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def read_json(path: str):
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read().strip()
            return json.loads(raw) if raw else []
    except Exception:
        return []


def write_json(path: str, data) -> None:
    ensure_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ===================== SQLite =====================
def _connect() -> sqlite3.Connection:
    ensure_dir()
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # 读写并发友好（单实例足够）
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_db() -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                soup_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'playing',
                questions_asked INTEGER NOT NULL DEFAULT 0,
                question_limit INTEGER,
                created_at REAL NOT NULL,
                solved_at REAL,
                given_up_at REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp REAL NOT NULL,
                is_free_reminder INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _migrate_legacy_sessions() -> None:
    """把旧版 sessions.json 一次性迁移进 SQLite（幂等：迁移成功即改名 .bak，靠文件名保证不重复执行）。

    注意：不能以"sessions.db 是否存在"作为跳过条件——_init_db 会先创建 db 文件，
    那样旧 JSON 永远不会被迁移。判断依据是旧 json 是否还在。
    """
    if not os.path.exists(LEGACY_SESSIONS_FILE):
        return
    data = read_json(LEGACY_SESSIONS_FILE)
    if not data:
        os.rename(LEGACY_SESSIONS_FILE, LEGACY_SESSIONS_FILE.with_suffix(".json.bak"))
        return
    conn = _connect()
    try:
        with conn:
            for s in data:
                conn.execute(
                    "INSERT OR IGNORE INTO sessions (id, soup_id, status, questions_asked, question_limit, created_at, solved_at, given_up_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        s.get("id"),
                        s.get("soupId", ""),
                        s.get("status", "playing"),
                        s.get("questionsAsked", 0),
                        s.get("questionLimit"),
                        s.get("createdAt", s.get("created_at", time.time())),
                        s.get("solvedAt"),
                        s.get("givenUpAt"),
                    ),
                )
                for m in s.get("messages", []):
                    conn.execute(
                        "INSERT INTO messages (session_id, role, content, timestamp, is_free_reminder) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            s.get("id"),
                            m.get("role", "user"),
                            m.get("content", ""),
                            m.get("timestamp", time.time()),
                            1 if m.get("isFreeReminder") else 0,
                        ),
                    )
        os.rename(LEGACY_SESSIONS_FILE, LEGACY_SESSIONS_FILE.with_suffix(".json.bak"))
        print(f"✅ 已迁移旧 sessions.json（{len(data)} 个会话）到 SQLite")
    finally:
        conn.close()


# ===================== 题库（启动时加载） =====================
def _load_generated_soups() -> list[Soup]:
    """加载 preprocess_soup.py 自动生成的汤品（收录新汤的入口）。"""
    out = []
    for s in read_json(GENERATED_FILE):
        try:
            out.append(Soup(**s))
        except Exception as e:  # noqa: BLE001
            print("⚠️ 跳过无法解析的生成汤品:", e)
    return out


def _load_verified_qa_pairs(soups: list[Soup]) -> None:
    """把管理员审批通过的反馈 QA 对注入到对应汤的 confusionPoints 末尾。

    每晚 0 点 merge_verified_qa.py 生成 data/verified_qa_pairs.jsonl；
    后端启动时读入，让主持人无需重启即可继承已验证的正确答案。
    """
    if not os.path.exists(VERIFIED_QA_FILE):
        return
    soup_map = {s.id: s for s in soups}
    injected = 0
    with open(VERIFIED_QA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                pair = json.loads(line)
            except json.JSONDecodeError:
                continue
            soup_id = pair.get("soupId")
            cp_raw = pair.get("confusionPoint")
            if not soup_id or not cp_raw:
                continue
            soup = soup_map.get(soup_id)
            if not soup:
                continue
            try:
                cp = ConfusionPoint(**cp_raw)
                if soup.confusionPoints is None:
                    soup.confusionPoints = []
                # 避免重复注入（按 feedbackId 去重已在 merge 时保证，这里再保险）
                existing_qs = {c.q for c in soup.confusionPoints}
                if cp.q not in existing_qs:
                    soup.confusionPoints.append(cp)
                    injected += 1
            except Exception as e:  # noqa: BLE001
                print(f"⚠️ 跳过无法解析的 verified QA 对（soup={soup_id}）:", e)
    if injected:
        print(f"✅ 已注入 {injected} 条玩家验证的正确 QA 对到 confusionPoints")


# 启动时合并：内置手写题库 SEED_SOUPS + 自动抽取生成的 generated_soups.json
SOUPS: list[Soup] = [Soup(**s) for s in SEED_SOUPS] + _load_generated_soups()

# 再把审批通过的反馈 QA 对注入进去
_load_verified_qa_pairs(SOUPS)

# 初始化数据库 + 旧数据迁移（首次启动自动执行）
_init_db()
_migrate_legacy_sessions()


def _match_query(soup: Soup, q: str) -> bool:
    """判断汤品是否命中搜索词（标题/汤面/标签/汤底摘要/完整汤底）。

    新收录的汤（SEED_SOUPS 或 generated_soups.json）都会进入 SOUPS，
    因此只要命中合并后的列表即可被搜到，无需额外改动。
    """
    haystack = " ".join([
        soup.title or "",
        soup.surface or "",
        " ".join(soup.tags or []),
        soup.bottomSummary or "",
        soup.bottom or "",
    ]).lower()
    return q in haystack


def get_all_soups(difficulty=None, tag=None, q=None, unlocked_ids=None) -> list[Soup]:
    unlocked_ids = set(unlocked_ids or [])
    soups = SOUPS
    # 隐藏彩蛋汤默认不展示，除非在 unlocked_ids 中
    soups = [s for s in soups if not s.hidden or s.id in unlocked_ids]
    if q and q.strip():
        ql = q.strip().lower()
        soups = [s for s in soups if _match_query(s, ql)]
    if difficulty:
        soups = [s for s in soups if s.difficulty == difficulty]
    if tag:
        soups = [s for s in soups if tag in s.tags]
    return soups


def get_soup_by_id(sid: str):
    for s in SOUPS:
        if s.id == sid:
            return s
    return None


# ===================== Session CRUD =====================
def _session_row_to_dict(row: sqlite3.Row, messages: list[dict]) -> dict:
    return {
        "id": row["id"],
        "soupId": row["soup_id"],
        "status": row["status"],
        "messages": messages,
        "questionsAsked": row["questions_asked"],
        "questionLimit": row["question_limit"],
        "createdAt": row["created_at"],
        "solvedAt": row["solved_at"],
        "givenUpAt": row["given_up_at"],
    }


def create_session(soup_id: str, question_limit=None) -> dict:
    now = time.time()
    session_id = str(uuid.uuid4())
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO sessions (id, soup_id, status, questions_asked, question_limit, created_at) "
                "VALUES (?, ?, 'playing', 0, ?, ?)",
                (session_id, soup_id, question_limit, now),
            )
    finally:
        conn.close()
    return {
        "id": session_id,
        "soupId": soup_id,
        "status": "playing",
        "messages": [],
        "questionsAsked": 0,
        "questionLimit": question_limit,
        "createdAt": now,
        "solvedAt": None,
        "givenUpAt": None,
    }


def save_message(session_id: str, role: str, content: str, is_free_reminder: bool = False) -> None:
    """追加一条消息；user 消息且非免费提醒时 question_asked +1（原子事务，并发安全）。"""
    conn = _connect()
    try:
        with conn:
            row = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                return
            conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp, is_free_reminder) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, time.time(), 1 if is_free_reminder else 0),
            )
            if role == "user" and not is_free_reminder:
                conn.execute(
                    "UPDATE sessions SET questions_asked = questions_asked + 1 WHERE id = ?",
                    (session_id,),
                )
    finally:
        conn.close()


def get_session(session_id: str):
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        msgs = conn.execute(
            "SELECT role, content, timestamp, is_free_reminder FROM messages "
            "WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        messages = [
            {
                "role": m["role"],
                "content": m["content"],
                "timestamp": m["timestamp"],
                "isFreeReminder": bool(m["is_free_reminder"]),
            }
            for m in msgs
        ]
        return _session_row_to_dict(row, messages)
    finally:
        conn.close()


def update_session_status(session_id: str, status: str) -> None:
    conn = _connect()
    try:
        with conn:
            if status == "solved":
                conn.execute(
                    "UPDATE sessions SET status = ?, solved_at = ? WHERE id = ?",
                    (status, time.time(), session_id),
                )
            elif status == "given_up":
                conn.execute(
                    "UPDATE sessions SET status = ?, given_up_at = ? WHERE id = ?",
                    (status, time.time(), session_id),
                )
            else:
                conn.execute(
                    "UPDATE sessions SET status = ? WHERE id = ?",
                    (status, session_id),
                )
    finally:
        conn.close()
