"""Isolated import CLI has no default source or overwrite permission."""
import hashlib
import json
import sqlite3

import pytest

from app import migrations
from app.config import BACKEND_DIR, PROJECT_ROOT
from .test_feedback_import import legacy
from .test_migrations import puzzle


def owned_source(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    conn = sqlite3.connect(source / "sessions.db")
    migrations.migrate(conn, [puzzle()], target_version=2); conn.close()
    (source / "feedback.jsonl").write_text(json.dumps(legacy(), ensure_ascii=False) + "\n", encoding="utf-8")
    return source


def hashes(source):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source.iterdir() if path.is_file()}


@pytest.mark.parametrize("dry_run", [False, True], ids=["new-target", "dry-run"])
def test_cli_new_copy_retains_all_source_bytes(tmp_path, dry_run, capsys):
    from app.scripts.import_feedback import main
    source = owned_source(tmp_path); target = tmp_path / "new-output"; report = tmp_path / "report.json"
    before = hashes(source)
    args = ["--source", str(source), "--target", str(target), "--report", str(report)]
    if dry_run:
        args.append("--dry-run")
    assert main(args) == 0
    assert hashes(source) == before and report.exists()
    assert json.loads(report.read_text())["productionReady"] is False
    if dry_run:
        assert not target.exists()
    else:
        conn = sqlite3.connect(target / "sessions.db")
        assert conn.execute("SELECT COUNT(*) FROM feedback_items").fetchone()[0] == 1
        conn.close()
    assert "PRIVATE" not in capsys.readouterr().out


@pytest.mark.parametrize("case", ["existing-target", "existing-report", "target-inside-source", "report-inside-source"])
def test_cli_refuses_overwrite_and_overlap_before_source_changes(tmp_path, case):
    from app.scripts.import_feedback import main
    source = owned_source(tmp_path); target = tmp_path / "output"; report = tmp_path / "report.json"
    if case == "existing-target":
        target.mkdir(); (target / "keep.txt").write_text("keep")
    elif case == "existing-report":
        report.write_text("keep")
    elif case == "target-inside-source":
        target = source / "output"
    else:
        report = source / "report.json"
    before = hashes(source)
    assert main(["--source", str(source), "--target", str(target), "--report", str(report)]) == 1
    assert hashes(source) == before
    if case == "existing-target":
        assert (target / "keep.txt").read_text() == "keep"
    if case == "existing-report":
        assert report.read_text() == "keep"


def test_cli_requires_explicit_paths_without_defaults():
    from app.scripts.import_feedback import main
    with pytest.raises(SystemExit) as caught:
        main([])
    assert caught.value.code == 2


@pytest.mark.parametrize("protected", [BACKEND_DIR / "data", PROJECT_ROOT / "data", PROJECT_ROOT])
def test_cli_runtime_or_ancestor_identity_refused_without_opening_player_inputs(tmp_path, protected):
    from app.scripts.import_feedback import main
    target, report = tmp_path / "output", tmp_path / "report.json"
    assert main(["--source", str(protected), "--target", str(target), "--report", str(report)]) == 1
    assert not target.exists()


def test_cli_source_file_symlink_alias_cannot_import_outside_its_copy(tmp_path):
    from app.scripts.import_feedback import main
    source = owned_source(tmp_path); path = source / "feedback.jsonl"
    outside = tmp_path / "outside-feedback.jsonl"; outside.write_bytes(path.read_bytes())
    path.unlink()
    try:
        path.symlink_to(outside)
    except OSError:
        pytest.skip("OS symlink privilege unavailable; no ACL changes")
    before = hashes(source); target, report = tmp_path / "output", tmp_path / "report.json"
    assert main(["--source", str(source), "--target", str(target), "--report", str(report)]) == 1
    assert not target.exists() and hashes(source) == before


def test_cli_bad_row_needs_review_retains_safe_report_and_source(tmp_path, capsys):
    from app.scripts.import_feedback import main
    source = owned_source(tmp_path)
    with (source / "feedback.jsonl").open("ab") as stream:
        stream.write(b'{"PRIVATE synthetic partial":')
    before = hashes(source); target, report = tmp_path / "output", tmp_path / "report.json"
    assert main(["--source", str(source), "--target", str(target), "--report", str(report)]) == 2
    saved = json.loads(report.read_text())
    assert saved["imported"] == 1 and saved["needsReview"] and len(saved["badRows"]) == 1
    assert "PRIVATE" not in report.read_text() + capsys.readouterr().out
    assert hashes(source) == before


def test_cli_uncheckpointed_source_wal_and_shm_are_unchanged(tmp_path):
    from app.scripts.import_feedback import main
    source = owned_source(tmp_path); conn = sqlite3.connect(source / "sessions.db")
    conn.execute("PRAGMA journal_mode=WAL"); conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("UPDATE runtime_meta SET row_version=row_version+1"); conn.commit()
    before = hashes(source)
    assert "sessions.db-wal" in before and "sessions.db-shm" in before
    try:
        assert main(["--source", str(source), "--target", str(tmp_path / "output"),
            "--report", str(tmp_path / "report.json")]) == 0
        assert hashes(source) == before
    finally:
        conn.close()


def test_cli_path_resolution_alias_must_be_refused_before_backup(tmp_path, monkeypatch):
    from app.scripts import import_feedback
    source = owned_source(tmp_path); alias = tmp_path / "alias-source"
    original = import_feedback._safe_path
    def resolving(value):
        return source if value == str(alias) else original(value)
    monkeypatch.setattr(import_feedback, "_safe_path", resolving)
    before = hashes(source); target = tmp_path / "output"
    assert import_feedback.main(["--source", str(alias), "--target", str(target),
        "--report", str(tmp_path / "report.json")]) == 1
    assert not target.exists() and hashes(source) == before
