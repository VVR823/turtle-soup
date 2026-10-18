"""Content-addressed, immutable puzzle/rule baseline; no configuration or I/O on import."""
import hashlib
import json
import sqlite3
import time

from pydantic import ValidationError

from .schemas import Soup

RULE_FIELDS = (
    "checkpoints", "confusionPoints", "genre", "castCount", "always_yes",
    "win_condition", "special_scoring", "unlocks", "symbolMappings", "truthItems",
)


class SnapshotError(RuntimeError):
    """Stored baseline is unavailable or not verifiably intact."""


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def strict_json(raw: str):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("non-finite JSON value")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)


def store_baseline(conn: sqlite3.Connection, soups: list[Soup]) -> dict:
    if not soups or len({s.id for s in soups}) != len(soups):
        raise SnapshotError("Baseline requires a nonempty unique puzzle catalog")
    versions = {}
    rules = {}
    now = time.time()
    for soup in sorted(soups, key=lambda s: s.id):
        payload = {"schemaVersion": 1, "soup": soup.model_dump(mode="json")}
        version = "p1:" + digest(payload)
        conn.execute("INSERT INTO puzzle_versions (id,soup_id,payload_json,created_at) VALUES (?,?,?,?)",
                     (version, soup.id, canonical_json(payload), now))
        versions[soup.id] = version
        rules[soup.id] = {name: payload["soup"][name] for name in RULE_FIELDS}
    rule_payload = {"schemaVersion": 1, "rulesBySoup": rules}
    manifest = {"schemaVersion": 1, "puzzleVersions": versions, "origin": "legacy-baseline"}
    rule_id = "r1:" + digest({"rules": rule_payload, "manifest": manifest})
    conn.execute("INSERT INTO rule_releases (id,parent_id,rules_json,manifest_json,created_at) VALUES (?,NULL,?,?,?)",
                 (rule_id, canonical_json(rule_payload), canonical_json(manifest), now))
    conn.execute("INSERT INTO runtime_meta (key,value_json) VALUES ('active_baseline',?)",
                 (canonical_json({"schemaVersion": 1, "ruleVersion": rule_id}),))
    return {"ruleVersion": rule_id, "puzzleVersions": versions}


def session_soup(conn: sqlite3.Connection, version: str) -> Soup:
    try:
        row = conn.execute("SELECT soup_id,payload_json FROM puzzle_versions WHERE id=?", (version,)).fetchone()
        if row is None:
            raise SnapshotError("Puzzle snapshot is missing")
        payload = strict_json(row[1])
        if not isinstance(payload, dict) or set(payload) != {"schemaVersion", "soup"} or payload["schemaVersion"] != 1:
            raise SnapshotError("Unknown puzzle snapshot schema")
        if "p1:" + digest(payload) != version:
            raise SnapshotError("Puzzle snapshot digest mismatch")
        if not isinstance(payload["soup"], dict) or set(payload["soup"]) != set(Soup.model_fields):
            raise SnapshotError("Incomplete or unknown puzzle fields")
        soup = Soup.model_validate(payload["soup"])
        if soup.id != row[0]:
            raise SnapshotError("Puzzle snapshot identity mismatch")
        return soup
    except (ValueError, TypeError, KeyError, sqlite3.Error, ValidationError) as error:
        raise SnapshotError("Invalid puzzle snapshot") from error


def _rule_release(conn: sqlite3.Connection, rule_version: str) -> tuple[dict, dict]:
    try:
        row = conn.execute("SELECT rules_json,manifest_json,parent_id FROM rule_releases WHERE id=?", (rule_version,)).fetchone()
        if row is None:
            raise SnapshotError("Rule snapshot is missing")
        rules, manifest = strict_json(row[0]), strict_json(row[1])
        if isinstance(rules, dict) and rules.get("schemaVersion") == 2:
            if len(row[0].encode("utf-8")) > 2097152 or len(row[1].encode("utf-8")) > 2097152:
                raise SnapshotError("Exact-rule proof exceeds bounded snapshot")
            if "r1:" + digest({"rules": rules, "manifest": manifest}) != rule_version:
                raise SnapshotError("Rule snapshot digest mismatch")
            from .rule_contract import _validate_schema2
            _validate_schema2(conn, rules, manifest, row[2])
            return rules, manifest
        if set(rules) != {"schemaVersion", "rulesBySoup"} or rules["schemaVersion"] != 1:
            raise SnapshotError("Unknown rule snapshot schema")
        if set(manifest) != {"schemaVersion", "puzzleVersions", "origin"} or manifest["schemaVersion"] != 1:
            raise SnapshotError("Unknown rule manifest schema")
        if "r1:" + digest({"rules": rules, "manifest": manifest}) != rule_version:
            raise SnapshotError("Rule snapshot digest mismatch")
        versions = manifest["puzzleVersions"]
        if not isinstance(versions, dict) or not versions or set(versions) != set(rules["rulesBySoup"]):
            raise SnapshotError("Rule/puzzle manifest mismatch")
        if any(not isinstance(value, dict) or set(value) != set(RULE_FIELDS)
               for value in rules["rulesBySoup"].values()):
            raise SnapshotError("Incomplete or unknown rule fields")
        return rules, manifest
    except (ValueError, TypeError, KeyError, AttributeError, sqlite3.Error) as error:
        raise SnapshotError("Invalid rule release") from error


def session_baseline(conn: sqlite3.Connection, puzzle_version: str, rule_version: str) -> Soup:
    soup = session_soup(conn, puzzle_version)
    rules, manifest = _rule_release(conn, rule_version)
    expected = {name: soup.model_dump(mode="json")[name] for name in RULE_FIELDS}
    if (manifest["puzzleVersions"].get(soup.id) != puzzle_version
            or rules["rulesBySoup"].get(soup.id) != expected):
        raise SnapshotError("Session rule/puzzle snapshot mismatch")
    return soup


def active_manifest(conn: sqlite3.Connection) -> dict:
    try:
        pointer = conn.execute("SELECT value_json FROM runtime_meta WHERE key='active_baseline'").fetchone()
        if pointer is None:
            raise SnapshotError("Active baseline is missing")
        active = strict_json(pointer[0])
        if set(active) != {"schemaVersion", "ruleVersion"} or active["schemaVersion"] != 1:
            raise SnapshotError("Unknown active baseline schema")
        rules, manifest = _rule_release(conn, active["ruleVersion"])
        for soup_id, version in manifest["puzzleVersions"].items():
            soup = session_soup(conn, version)
            expected = {name: soup.model_dump(mode="json")[name] for name in RULE_FIELDS}
            if soup.id != soup_id or expected != rules["rulesBySoup"][soup_id]:
                raise SnapshotError("Rule/puzzle snapshot mismatch")
        return {"ruleVersion": active["ruleVersion"], "puzzleVersions": manifest["puzzleVersions"]}
    except (ValueError, TypeError, KeyError, AttributeError, sqlite3.Error) as error:
        raise SnapshotError("Invalid active baseline") from error


def active_soups(conn: sqlite3.Connection) -> list[Soup]:
    manifest = active_manifest(conn)
    return [session_soup(conn, version) for _, version in sorted(manifest["puzzleVersions"].items())]
