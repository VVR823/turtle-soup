"""Bounded LOCAL snapshot rehearsal, not migration, deployment or stop-writer proof.

All paths must be explicit isolated directories. Existing output is never
overwritten. Input SQLite is opened only after copying to owned scratch.
"""
import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import time
from pathlib import Path

from app import baselines, migrations
from app.scripts import migrate_data


class RecoveryError(RuntimeError):
    pass


_AUXILIARY = {"sessions.json", "generated_soups.json", "verified_qa_pairs.jsonl",
              "audit-fallback.jsonl", "audit-gap.json"}
_DATABASE = {"sessions.db", "sessions.db-wal", "sessions.db-shm"}
_MANIFEST = "recovery-manifest.json"
_LIMIT_BYTES = 64 * 1024 * 1024
_LIMIT_FILES = 2000
_FAILURES = (migrate_data.RehearsalError, migrations.MigrationError, baselines.SnapshotError,
             OSError, ValueError, OverflowError, sqlite3.Error)


def _reject_redirect(path: Path):
    # lstat preserves Windows reparse-point identity, including directory junctions.
    for component in (path, *path.parents):
        if component.is_symlink() or (component.exists() and
                getattr(component.lstat(), "st_file_attributes", 0) & 0x400):
            raise RecoveryError("Redirected paths are not rehearsal inputs or outputs")


def _paths(source: str, target: str, report: str):
    for raw in (source, target, report):
        if not Path(raw).is_absolute():
            raise RecoveryError("Explicit absolute paths required")
        _reject_redirect(Path(raw))
    paths = tuple(migrate_data._safe_path(raw) for raw in (source, target, report))
    migrate_data._validate_paths(*paths)
    return paths


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _inventory(source: Path, *, artifact: bool = False) -> dict[str, str]:
    files = []
    allowed = _AUXILIARY | ({"sessions.db", _MANIFEST} if artifact else _DATABASE)
    for item in source.iterdir():
        _reject_redirect(item)
        if item.name == "traces" and item.is_dir():
            for trace in item.iterdir():
                _reject_redirect(trace)
                if not trace.is_file() or not trace.name.endswith((".jsonl", ".jsonl.bak")):
                    raise RecoveryError("Unrecognized trace input")
                files.append(trace)
        elif item.name in allowed and item.is_file():
            files.append(item)
        else:
            raise RecoveryError("Unrecognized data input")
    if not (source / "sessions.db").is_file():
        raise RecoveryError("Registered SQLite source required")
    if len(files) > _LIMIT_FILES or sum(file.stat().st_size for file in files) > _LIMIT_BYTES:
        raise RecoveryError("Source exceeds local rehearsal bounds")
    return {file.relative_to(source).as_posix(): _digest(file) for file in sorted(files)}


def _verify_database(conn: sqlite3.Connection) -> int:
    started = time.monotonic()
    conn.row_factory = sqlite3.Row
    conn.set_progress_handler(lambda: int(time.monotonic() - started > 15), 1000)
    try:
        if [row[0] for row in conn.execute("PRAGMA integrity_check")] != ["ok"]:
            raise RecoveryError("Snapshot integrity failed")
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RecoveryError("Snapshot foreign keys failed")
        version = conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
        migrations.verify_schema(conn, required_version=version)
        return version
    finally:
        conn.set_progress_handler(None, 0)


def _copy_auxiliary(source: Path, target: Path, files: dict[str, str]):
    for name in files:
        if name not in _DATABASE and name != _MANIFEST:
            output = target / name
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, output)
            if _digest(output) != files[name]:
                raise RecoveryError("Copied auxiliary bytes do not match source")


def _write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def _report(operation: str, version: int, target: Path, report: Path, count: int) -> dict:
    value = {"status": "passed", "operation": operation, "migrationVersion": version,
             "sourceUnchanged": True, "productionReady": False, "quiescenceVerified": False,
             "fileCount": count, "databaseSha256": _digest(target / "sessions.db")}
    _write_json(report, value)
    return value


def backup(source: str, target: str, report: str) -> dict:
    """Produce a new consistent local artifact; caller owns stop-writer checks."""
    try:
        source_path, target_path, report_path = _paths(source, target, report)
        before = _inventory(source_path)
        target_path.mkdir(parents=True, exist_ok=False)
        conn = sqlite3.connect(target_path / "sessions.db")
        try:
            migrate_data._backup(source_path, conn)
            version = _verify_database(conn)
        finally:
            conn.close()
        _copy_auxiliary(source_path, target_path, before)
        if _inventory(source_path) != before:
            raise RecoveryError("Source changed during snapshot")
        output = _inventory(target_path)
        _write_json(target_path / _MANIFEST, {"schemaVersion": 1, "migrationVersion": version,
                                            "files": output, "productionReady": False})
        if _inventory(source_path) != before:
            raise RecoveryError("Source changed during snapshot")
        return _report("backup", version, target_path, report_path, len(output))
    except _FAILURES as error:
        raise RecoveryError("Local backup refused or failed") from error


def _manifest(source: Path, actual: dict[str, str]) -> dict:
    manifest_path = source / _MANIFEST
    if not manifest_path.is_file() or manifest_path.stat().st_size > 512 * 1024:
        raise RecoveryError("Bounded recovery manifest required")
    value = baselines.strict_json(manifest_path.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or set(value) != {"schemaVersion", "migrationVersion", "files", "productionReady"}
            or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1
            or type(value["migrationVersion"]) is not int or value["migrationVersion"] not in (1, 2, 3, 4, 5)
            or value["productionReady"] is not False or not isinstance(value["files"], dict)):
        raise RecoveryError("Unknown recovery manifest")
    files = value["files"]
    # Compare to enumerated allowed names before ever resolving a manifest path.
    if files.keys() != (actual.keys() - {_MANIFEST}) or any(
        not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or actual[name] != digest for name, digest in files.items()
    ):
        raise RecoveryError("Recovery file set or digest mismatch")
    return value


def restore(source: str, target: str, report: str) -> dict:
    """Verify first, restore only into a NEW directory; never overwrite latest data."""
    try:
        source_path, target_path, report_path = _paths(source, target, report)
        before = _inventory(source_path, artifact=True)
        manifest = _manifest(source_path, before)
        conn = sqlite3.connect(":memory:")
        try:
            migrate_data._backup(source_path, conn)
            version = _verify_database(conn)
            if version != manifest["migrationVersion"] or _inventory(source_path, artifact=True) != before:
                raise RecoveryError("Recovery version or source changed")
            target_path.mkdir(parents=True, exist_ok=False)
            destination = sqlite3.connect(target_path / "sessions.db")
            try:
                conn.backup(destination)
                _verify_database(destination)
            finally:
                destination.close()
        finally:
            conn.close()
        _copy_auxiliary(source_path, target_path, manifest["files"])
        if _inventory(source_path, artifact=True) != before:
            raise RecoveryError("Recovery source changed")
        return _report("restore", version, target_path, report_path, len(manifest["files"]))
    except _FAILURES as error:
        raise RecoveryError("Local restore refused or failed") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("backup", "restore"))
    for name in ("source", "target", "report"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    try:
        value = (backup if args.operation == "backup" else restore)(args.source, args.target, args.report)
        print(json.dumps({"status": value["status"], "operation": value["operation"],
                          "migrationVersion": value["migrationVersion"], "productionReady": False}))
        return 0
    except RecoveryError:
        print('{"status":"failed","code":"recovery_refused_or_failed","productionReady":false}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
