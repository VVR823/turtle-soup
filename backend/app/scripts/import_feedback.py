"""Explicit stopped-copy feedback rehearsal; never migrates running data."""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from app import migrations
from app.feedback_import import FeedbackImportError, checked_source, import_feedback_jsonl
from app.scripts.migrate_data import RehearsalError, _backup, _safe_path, _validate_paths, _source_manifest


def _argument_path(raw):
    path = _safe_path(raw)
    if path != Path(raw).absolute():
        raise RehearsalError("Rehearsal path aliases are not accepted")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "target", "report"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        source, target, report = (_argument_path(value) for value in (args.source, args.target, args.report))
        _validate_paths(source, target, report)
        for name in ("sessions.db", "sessions.db-wal", "sessions.db-shm", "feedback.jsonl"):
            _argument_path(str(source / name))
        feedback = source / "feedback.jsonl"
        checked_source(feedback)
        before = _source_manifest(source)
        before_feedback = checked_source(feedback)
        digest = hashlib.sha256()
        with feedback.open("rb") as stream:
            for block in iter(lambda: stream.read(65536), b""):
                digest.update(block)
        if checked_source(feedback) != before_feedback:
            raise FeedbackImportError("feedback_source_changed")
        source_digest = digest.hexdigest()
        if not args.dry_run:
            target.mkdir(parents=True, exist_ok=False)
        conn = sqlite3.connect(":memory:" if args.dry_run else target / "sessions.db")
        try:
            _backup(source, conn)  # Only scratch SQLite opens source DB/WAL copies.
            migrations.verify_schema(conn, required_version=2)
            result = import_feedback_jsonl(conn, feedback, source_digest=source_digest)
        finally:
            conn.close()
        if _source_manifest(source) != before or checked_source(feedback) != before_feedback:
            raise FeedbackImportError("feedback_source_changed")
        output = result.model_dump(mode="json")
        output.update(dryRun=args.dry_run, sourceUnchanged=True, sourceDigests=before)
        report.parent.mkdir(parents=True, exist_ok=True)
        with report.open("x", encoding="utf-8") as stream:
            json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        print(json.dumps({"status": "needs_review" if result.needsReview else "passed", "productionReady": False}))
        return 2 if result.needsReview else 0
    except (FeedbackImportError, RehearsalError, migrations.MigrationError, OSError, ValueError, sqlite3.Error):
        # Retain any partial new output for diagnosis; never erase source/target.
        print('{"status":"failed","code":"feedback_import_refused_or_failed","productionReady":false}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
