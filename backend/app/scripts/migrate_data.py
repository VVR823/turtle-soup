"""Isolated rehearsal only. No default paths, dotenv, production mutation or deletion.

Exit 0: rehearsal passed; 2: preserved records need human review; 1: refused/failed.
Successful output is not authorization to install it on a running website.
"""
import argparse
import hashlib
import json
import shutil
import sqlite3
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from app import db, migrations
from app.config import BACKEND_DIR, PROJECT_ROOT
from app.paths import canonical_path


class RehearsalError(RuntimeError):
    pass


def _safe_path(raw: str) -> Path:
    if not Path(raw).is_absolute():
        raise RehearsalError("All paths must be explicit absolute paths")
    path = canonical_path(raw)
    for protected in (BACKEND_DIR / "data", PROJECT_ROOT / "data"):
        protected = canonical_path(protected)
        if path == protected or path.is_relative_to(protected) or protected.is_relative_to(path):
            raise RehearsalError("Runtime directories and their ancestors are not rehearsal targets")
    if path.name.startswith(".env"):
        raise RehearsalError("Configuration files are not rehearsal targets")
    return path


def _validate_paths(source: Path, target: Path, report: Path):
    if not source.is_dir():
        raise RehearsalError("Source must be an existing isolated directory")
    if target == source or target.is_relative_to(source) or source.is_relative_to(target):
        raise RehearsalError("Source and target must be separate directories")
    if target.exists():
        raise RehearsalError("Target must be a new directory; existing output is never overwritten")
    if report.exists() or report == source or report.is_relative_to(source):
        raise RehearsalError("Report must be a new file outside the source")
    if report == target or report.is_relative_to(target) or target.is_relative_to(report):
        raise RehearsalError("Report and target must not overlap")
    for name in ("sessions.db", "sessions.db-wal", "sessions.db-shm", "sessions.json", "generated_soups.json", "verified_qa_pairs.jsonl"):
        path = _safe_path(str(source / name))
        if path.parent != source:
            raise RehearsalError("Source input must not redirect outside its directory")


def _source_manifest(source: Path) -> dict:
    # Include SHM too: directory/content preservation is stronger than a payload hash.
    result = {}
    for name in ("sessions.db", "sessions.db-wal", "sessions.db-shm", "sessions.json", "generated_soups.json", "verified_qa_pairs.jsonl"):
        path = source / name
        if path.exists():
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _backup(source: Path, destination: sqlite3.Connection):
    path = source / "sessions.db"
    if path.exists():
        started = time.monotonic()
        # Even mode=ro can create/modify a WAL shared-memory sidecar. Never
        # open SQLite in the input directory; recreate sidecars only in scratch.
        with TemporaryDirectory(prefix="turtle-soup-rehearsal-") as scratch_name:
            scratch = Path(scratch_name)
            for name in ("sessions.db", "sessions.db-wal"):
                input_path = source / name
                if input_path.exists():
                    shutil.copy2(input_path, scratch / name)
            reader = sqlite3.connect((scratch / "sessions.db").as_uri() + "?mode=ro", uri=True, timeout=5)
            try:
                def progress(_status, _remaining, _total):
                    if time.monotonic() - started > 15:
                        raise RehearsalError("Source backup exceeded rehearsal deadline")
                reader.backup(destination, pages=128, progress=progress, sleep=0.05)
            finally:
                reader.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--target-version", type=int, choices=(1, 2, 3, 4, 5), default=1)
    args = parser.parse_args(argv)
    report_path = None
    try:
        source, target, candidate_report = (_safe_path(value) for value in (args.source, args.target, args.report))
        _validate_paths(source, target, candidate_report)
        report_path = candidate_report
        before = _source_manifest(source)
        catalog = db.load_catalog(source, include_legacy_verified=True)
        legacy_path = source / "sessions.json"
        records = db.read_json(legacy_path) if legacy_path.exists() else []
        if not isinstance(records, list):
            raise RehearsalError("Legacy sessions must be a JSON array")
        if args.dry_run:
            conn = sqlite3.connect(":memory:")
        else:
            target.mkdir(parents=True, exist_ok=False)
            conn = sqlite3.connect(target / "sessions.db")
        try:
            _backup(source, conn)
            result = migrations.migrate(conn, catalog, legacy_records=records, target_version=args.target_version)
        finally:
            conn.close()
        if _source_manifest(source) != before:
            raise RehearsalError("Source changed during rehearsal; output is not approved")
        status = "needs_review" if result["issues"] else "passed"
        result.update(status=status, dryRun=args.dry_run, sourceDigests=before,
                      sourceUnchanged=True, productionReady=False)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        print(json.dumps({"status": status, "migrationVersion": result["migrationVersion"], "productionReady": False}))
        return 2 if result["issues"] else 0
    except (RehearsalError, db.DataLoadError, migrations.MigrationError, OSError, ValueError, OverflowError, sqlite3.Error):
        if report_path is not None and not report_path.exists():
            report_path.parent.mkdir(parents=True, exist_ok=True)
            with report_path.open("x", encoding="utf-8") as handle:
                json.dump({"status": "failed", "code": "rehearsal_failed", "productionReady": False}, handle)
        print('{"status":"failed","code":"rehearsal_refused_or_failed"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
