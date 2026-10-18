"""Declared synthetic statistical volume in nonce-owned UI storage only.

Not production traffic, real users, approvals, model outputs or quality evidence.
No database path CLI option, migration, deletion, network call or model import.
"""
import json
import os
import sqlite3
import time
from pathlib import Path
from uuid import UUID, NAMESPACE_URL, uuid5


def seed_owned_metrics_volume(data_dir: Path, instance_id: str):
    from app import baselines, migrations
    if str(UUID(instance_id)) != instance_id:
        raise ValueError("Owned canonical UI nonce required")
    conn = sqlite3.connect((data_dir / "sessions.db").resolve().as_uri() + "?mode=rw", uri=True, timeout=0.5)
    try:
        row = conn.execute("SELECT value_json FROM runtime_meta WHERE key='owned_ui_fixture'").fetchone()
        if row is None or baselines.strict_json(row[0]) != {"instanceId": instance_id}:
            raise ValueError("Database does not belong to this UI fixture")
        migrations.verify_schema(conn, required_version=4)
        manifest = baselines.active_manifest(conn)
        soups = sorted(manifest["puzzleVersions"])[:4]
        if len(soups) != 4:
            raise ValueError("Four public fixture sources required")
        start = int(time.time() // 86400) * 86400 - 26 * 86400
        conn.execute("BEGIN IMMEDIATE")
        for index in range(105):
            soup_id = soups[index % 4]
            identity = str(uuid5(NAMESPACE_URL, f"turtle-soup/declared-metrics-ui/{instance_id}/{index}"))
            conn.execute("INSERT OR IGNORE INTO sessions(id,soup_id,created_at,puzzle_version,rule_version,compat_state,traffic_class) VALUES(?,?,?,?,?,'compatible','real')",
                (identity, soup_id, start + (index // 4) * 86400 + 100,
                    manifest["puzzleVersions"][soup_id], manifest["ruleVersion"]))
        conn.commit()
        return {"schemaVersion": 1, "evidenceKind": "declared_synthetic_ui_volume", "sessionRows": 105,
            "firstSoupId": soups[0], "start": start - 86400, "end": time.time() + 1}
    finally:
        conn.close()


if __name__ == "__main__":
    from app.test_server import fixture_settings
    if os.environ.get("TURTLE_SOUP_TESTING") != "1" or os.environ.get("TURTLE_SOUP_UI_TESTING") != "1":
        raise RuntimeError("Explicit owned synthetic UI mode required")
    settings = fixture_settings(Path(os.environ["TURTLE_SOUP_DATA_DIR"]), os.environ)
    print(json.dumps(seed_owned_metrics_volume(settings.DATA_DIR, settings.TEST_INSTANCE_ID)))
