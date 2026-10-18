"""Session 存储（SQLite，标准库 sqlite3，零外部依赖）。

soup 题库来自内置 SEED_SOUPS（常驻内存）+ generated_soups.json（启动时读取）；
session 问答记录持久化到 backend/data/sessions.db（SQLite）。

为什么用 SQLite 而不是 JSON 文件：
- JSON 存储每次读写都是"全量读 → 改 → 全量写"，并发请求会互相覆盖丢数据；
- SQLite 提供事务、单写者锁与 WAL 读写协调，不是行级写锁。
"""
import json
import os
import sqlite3
import time
import uuid
import shutil
from contextlib import contextmanager
from tempfile import TemporaryDirectory
from pathlib import Path

from .schemas import ConfusionPoint, Soup
from .soups import SEED_SOUPS
from .runtime import get_runtime
from . import baselines, migrations, game_responses


class DataLoadError(RuntimeError):
    """Configured local data is malformed; never treat this as an empty catalog."""


class SessionCompatibilityError(RuntimeError):
    pass

def _data_path(name: str) -> Path:
    return get_runtime().settings.DATA_DIR / name


def ensure_dir() -> None:
    get_runtime().settings.DATA_DIR.mkdir(parents=True, exist_ok=True)


def read_json(path: str):
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return baselines.strict_json(f.read())
    except (OSError, ValueError, UnicodeError) as error:
        raise DataLoadError("Configured JSON data is unreadable or malformed") from error


def write_json(path: str, data) -> None:
    ensure_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ===================== SQLite =====================
def _connect(*, timeout: float = 10) -> sqlite3.Connection:
    ensure_dir()
    conn = sqlite3.connect(_data_path("sessions.db"), timeout=timeout)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")  # 读写并发友好（单实例足够）
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    except BaseException:
        conn.close()
        raise


# ===================== 题库（启动时加载） =====================
def _load_generated_soups(path: Path | None = None) -> list[Soup]:
    """加载 preprocess_soup.py 自动生成的汤品（收录新汤的入口）。"""
    out = []
    records = read_json(path if path is not None else _data_path("generated_soups.json"))
    if not isinstance(records, list):
        raise DataLoadError("Configured puzzle catalog must be a JSON array")
    for s in records:
        try:
            out.append(Soup(**s))
        except (ValueError, TypeError) as error:
            raise DataLoadError("Configured puzzle catalog contains an invalid record") from error
    return out


def _load_verified_qa_pairs(soups: list[Soup], path: Path | None = None) -> None:
    """Preserve old input semantics ONLY during explicit isolated rehearsal.

    Runtime never calls this loader. A historic approved label is not new
    publication authority, and no source file is removed or rewritten here.
    """
    verified_file = path if path is not None else _data_path("verified_qa_pairs.jsonl")
    if not os.path.exists(verified_file):
        return
    soup_map = {s.id: s for s in soups}
    injected = 0
    with open(verified_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                pair = baselines.strict_json(line)
                if not isinstance(pair, dict):
                    raise ValueError("not an object")
            except ValueError as error:
                raise DataLoadError("Configured verified rules contain malformed JSON") from error
            soup_id = pair.get("soupId")
            cp_raw = pair.get("confusionPoint")
            if not soup_id or not cp_raw:
                raise DataLoadError("Configured verified rule is missing required fields")
            soup = soup_map.get(soup_id)
            if not soup:
                raise DataLoadError("Configured verified rule refers to an unknown puzzle")
            try:
                cp = ConfusionPoint(**cp_raw)
                if soup.confusionPoints is None:
                    soup.confusionPoints = []
                # 避免重复注入（按 feedbackId 去重已在 merge 时保证，这里再保险）
                existing_qs = {c.q for c in soup.confusionPoints}
                if cp.q not in existing_qs:
                    soup.confusionPoints.append(cp)
                    injected += 1
            except (ValueError, TypeError) as error:
                raise DataLoadError("Configured verified rule is invalid") from error


def load_catalog(data_dir: Path, *, include_runtime: bool = True, include_legacy_verified: bool = True) -> list[Soup]:
    """Explicit input directory; usable by the rehearsal CLI without dotenv."""
    soups = [Soup(**s) for s in SEED_SOUPS]
    if include_runtime:
        soups.extend(_load_generated_soups(data_dir / "generated_soups.json"))
        if include_legacy_verified:
            _load_verified_qa_pairs(soups, data_dir / "verified_qa_pairs.jsonl")
    if len({s.id for s in soups}) != len(soups):
        raise DataLoadError("Puzzle catalog has duplicate IDs")
    return soups


def get_soups() -> list[Soup]:
    runtime = get_runtime()
    with runtime.lock:
        if runtime.soups is None:
            runtime.soups = load_catalog(runtime.settings.DATA_DIR, include_runtime=runtime.settings.LOAD_RUNTIME_PUZZLES,
                include_legacy_verified=False)
        return runtime.soups


@contextmanager
def _readonly_preflight(path: Path):
    """SQLite mode=ro may write SHM. Verify a private DB+WAL copy, never source.

    This is a cold-start schema check, not a live backup or multiworker snapshot
    guarantee. Refuse if files change during copying; migrations stay offline.
    """
    sources = (path, path.with_name(path.name + "-wal"))

    def fingerprint():
        return tuple((p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ino) if p.exists() else None for p in sources)

    with TemporaryDirectory(prefix="turtle-soup-preflight-") as directory:
        before = fingerprint()
        for source, state in zip(sources, before):
            if state is not None:
                shutil.copy2(source, Path(directory) / source.name)
        if fingerprint() != before:
            raise migrations.MigrationError("Storage changed during startup preflight; retry after writers stop")
        conn = sqlite3.connect((Path(directory) / path.name).as_uri() + "?mode=ro", uri=True)
        try:
            yield conn
        finally:
            conn.close()


def initialize() -> None:
    """Initialize fresh storage or verify a migrated DB; never upgrade an old DB."""
    runtime = get_runtime()
    with runtime.lock:
        if runtime.initialized:
            return
        path = _data_path("sessions.db")
        if not path.exists() and any(_data_path(name).exists() for name in ("feedback.jsonl", "verified_qa_pairs.jsonl")):
            raise migrations.MigrationRequired("Legacy feedback/rules require explicit isolated rehearsal")
        catalog = get_soups()
        if path.exists():
            # Read-only preflight precedes WAL setup or any application writes.
            with _readonly_preflight(path) as conn:
                migrations.verify_schema(conn, required_version=2)
                runtime.soups = baselines.active_soups(conn)
        else:
            if runtime.settings.LOAD_RUNTIME_PUZZLES and _data_path("sessions.json").exists():
                raise migrations.MigrationRequired("Legacy JSON requires explicit offline migration")
            conn = _connect()
            try:
                migrations.migrate(conn, catalog, target_version=2)
                runtime.soups = baselines.active_soups(conn)
            finally:
                conn.close()
        runtime.initialized = True


def __getattr__(name: str):
    if name == "SOUPS":
        return get_soups()
    paths = {
        "DB_FILE": "sessions.db", "LEGACY_SESSIONS_FILE": "sessions.json",
        "GENERATED_FILE": "generated_soups.json", "VERIFIED_QA_FILE": "verified_qa_pairs.jsonl",
    }
    if name == "DATA_DIR":
        return get_runtime().settings.DATA_DIR
    if name in paths:
        return _data_path(paths[name])
    raise AttributeError(name)


def _match_query(soup: Soup, q: str) -> bool:
    """Public discovery searches title/surface/tags only.

    Never select by private truth: even returning a public card would reveal
    that a guessed secret exists in this puzzle. Legal reveal is separate.
    """
    haystack = " ".join([
        soup.title or "",
        soup.surface or "",
        " ".join(soup.tags or []),
    ]).lower()
    return q in haystack


def get_all_soups(difficulty=None, tag=None, q=None, unlocked_ids=None) -> list[Soup]:
    unlocked_ids = set(unlocked_ids or [])
    soups = get_soups()
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
    for s in get_soups():
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
        "puzzleVersion": row["puzzle_version"],
        "ruleVersion": row["rule_version"],
        "compatState": row["compat_state"],
        "rowVersion": row["row_version"],
    }


def create_session(soup_id: str, question_limit=None) -> dict:
    initialize()  # First explicit CLI/embedded CRUD call, never module import.
    now = time.time()
    session_id = str(uuid.uuid4())
    conn = _connect()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            baseline = baselines.active_manifest(conn)
            from .rule_contract import rule_suspension_state
            if rule_suspension_state(conn, baseline["ruleVersion"]):
                raise GameConflict("rule_version_suspended")
            version = baseline["puzzleVersions"].get(soup_id)
            if version is None:
                raise baselines.SnapshotError("Puzzle is not in the active baseline")
            conn.execute(
                """INSERT INTO sessions (id,soup_id,status,questions_asked,question_limit,created_at,
                   puzzle_version,rule_version,compat_state,last_activity_at,traffic_class)
                   VALUES (?,?,'playing',0,?,?,?,?,'compatible',?,?)""",
                (session_id, soup_id, question_limit, now, version, baseline["ruleVersion"], now,
                 "test" if get_runtime().settings.TESTING else "real"),
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
    """Retired: a single-message writer cannot uphold paired turn invariants."""
    raise GameConflict("atomic_writer_required")


def get_session(session_id: str):
    initialize()
    conn = _connect()
    try:
        # A deferred read transaction pins one WAL snapshot across session,
        # messages and evaluation without blocking the concurrent model writer.
        conn.execute("BEGIN")
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        msgs = conn.execute(
            "SELECT role, content, timestamp, is_free_reminder, turn_id FROM messages "
            "WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        messages = [
            {
                "role": m["role"],
                "content": m["content"],
                "timestamp": m["timestamp"],
                "isFreeReminder": bool(m["is_free_reminder"]),
                # Already-public chat acknowledgement identity, never private HostResult.
                # Unlinked legacy rows remain unlinked; do not guess adjacent turns.
                **({"turnId": m["turn_id"]} if m["turn_id"] is not None else {}),
            }
            for m in msgs
        ]
        result = _session_row_to_dict(row, messages)
        from .rule_contract import rule_suspension_state
        result["ruleSuspended"] = (rule_suspension_state(conn, row["rule_version"])
            if row["compat_state"] == "compatible" else False)
        evaluation = conn.execute("SELECT * FROM evaluations WHERE session_id=?", (session_id,)).fetchone()
        result["evaluation"] = game_responses.evaluation_response(evaluation, row) if evaluation is not None else None
        return result
    finally:
        conn.rollback()
        conn.close()


def require_compatible(session: dict) -> None:
    if session.get("compatState") != "compatible":
        raise SessionCompatibilityError("Legacy session requires manual compatibility review")


def get_session_soup(session: dict) -> Soup:
    require_compatible(session)
    conn = _connect()
    try:
        soup = baselines.session_baseline(conn, session["puzzleVersion"], session["ruleVersion"])
        if soup.id != session["soupId"]:
            raise baselines.SnapshotError("Session/puzzle identity mismatch")
        return soup
    finally:
        conn.close()


def update_session_status(session_id: str, status: str) -> None:
    """Retired: only fenced finish/evaluation transactions may end a game."""
    raise GameConflict("atomic_writer_required")


# Approved storage interfaces remain db.*; transaction implementation has no
# import-time database/config access and keeps model orchestration out of CRUD.
from .game_store import (  # noqa: E402
    GameConflict, GameNotFound, TurnReplay, TurnReservation,
    create_game_once, reserve_turn, finish_turn, get_turn_response,
    expire_reserved_turns, require_atomic_writer, evaluate_once, get_evaluation,
    get_private_host_history,
)
