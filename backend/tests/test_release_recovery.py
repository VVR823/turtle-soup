"""LOCAL synthetic recovery; real SQLite/file behavior, never player storage.

Breaks caught: missing recovery tool, migrating a snapshot instead of preserving
its schema, losing uncheckpointed committed WAL, dropping sidecar/trace bytes,
or presenting a copy operation as proof that production writers have stopped.
"""
from contextlib import closing
import hashlib
import importlib
import json
import os
import sqlite3
import subprocess

import pytest

from app import migrations
from .test_migrations import old_database, puzzle


def recovery_module():
    name = "app.scripts.snapshot_recovery"
    assert importlib.util.find_spec(name) is not None, "LOCAL snapshot recovery API is missing"
    return importlib.import_module(name)


def fixture_source(tmp_path, version=4):
    source = tmp_path / "source"
    source.mkdir()
    conn = old_database(source / "sessions.db")
    migrations.migrate(conn, [puzzle()], target_version=version)
    conn.close()
    (source / "generated_soups.json").write_text(
        json.dumps([puzzle().model_dump(mode="json")]), encoding="utf-8"
    )
    (source / "audit-fallback.jsonl").write_bytes(b'{"syntheticSecret":"PRIVATE_TEST_CANARY"}\n')
    (source / "audit-gap.json").write_bytes(b'{"permanentGap":true}\n')
    (source / "traces").mkdir()
    (source / "traces" / "synthetic.jsonl").write_bytes(b'{"question":"PRIVATE_TRACE_CANARY"}\n')
    return source


def hashes(directory):
    return {file.relative_to(directory).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
            for file in directory.rglob("*") if file.is_file()}


def test_recovery_api_is_available():
    module = recovery_module()
    assert callable(module.backup)
    assert callable(module.restore)
    assert callable(module.main)


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
def test_backup_restore_preserves_actual_schema_and_private_auxiliary_bytes(tmp_path, version):
    module = recovery_module()
    source = fixture_source(tmp_path, version)
    before = hashes(source)
    artifact, restored = tmp_path / "artifact", tmp_path / "restored"
    report = module.backup(str(source), str(artifact), str(tmp_path / "backup-report.json"))
    assert hashes(source) == before
    assert report["status"] == "passed"
    assert report["migrationVersion"] == version
    assert report["sourceUnchanged"] is True
    assert report["productionReady"] is False
    assert report["quiescenceVerified"] is False
    for canary in ("Question?", "Truth", "PRIVATE_TEST_CANARY", "PRIVATE_TRACE_CANARY"):
        assert canary not in json.dumps(report)
        assert canary not in (artifact / "recovery-manifest.json").read_text(encoding="utf-8")
    artifact_before = hashes(artifact)
    result = module.restore(str(artifact), str(restored), str(tmp_path / "restore-report.json"))
    assert hashes(artifact) == artifact_before
    assert result["migrationVersion"] == version
    assert result["quiescenceVerified"] is False
    with closing(sqlite3.connect(restored / "sessions.db")) as conn, conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == version
        migrations.verify_schema(conn, required_version=version)
        assert [tuple(row) for row in conn.execute("SELECT id,content FROM messages ORDER BY id")] == [
            (41, "Question?"), (42, "是")
        ]
        assert conn.execute("SELECT questions_asked FROM sessions WHERE id='old'").fetchone()[0] == 1
    for name in ("generated_soups.json", "audit-fallback.jsonl", "audit-gap.json", "traces/synthetic.jsonl"):
        assert (restored / name).read_bytes() == (source / name).read_bytes()
    assert not (restored / "recovery-manifest.json").exists()


def test_recovery_includes_uncheckpointed_committed_wal_without_touching_input_shm(tmp_path):
    module = recovery_module()
    source = fixture_source(tmp_path)
    conn = sqlite3.connect(source / "sessions.db")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("UPDATE sessions SET question_limit=33 WHERE id='old'")
    conn.commit()
    assert (source / "sessions.db-wal").stat().st_size > 0
    before = hashes(source)
    try:
        module.backup(str(source), str(tmp_path / "artifact"), str(tmp_path / "backup-report.json"))
        assert hashes(source) == before
        module.restore(str(tmp_path / "artifact"), str(tmp_path / "restored"),
                       str(tmp_path / "restore-report.json"))
        with closing(sqlite3.connect(tmp_path / "restored" / "sessions.db")) as restored, restored:
            assert restored.execute("SELECT question_limit FROM sessions WHERE id='old'").fetchone()[0] == 33
        assert hashes(source) == before
    finally:
        conn.close()


@pytest.mark.parametrize("operation", ["backup", "restore"])
@pytest.mark.parametrize("collision", ["source", "child", "existing", "report-source", "report-existing", "report-target"])
def test_recovery_refuses_overwrite_and_overlapping_paths(tmp_path, operation, collision):
    module = recovery_module()
    source = fixture_source(tmp_path)
    if operation == "restore":
        module.backup(str(source), str(tmp_path / "artifact"), str(tmp_path / "first-report.json"))
        source = tmp_path / "artifact"
    target, report = tmp_path / "target", tmp_path / "report.json"
    if collision == "source":
        target = source
    elif collision == "child":
        target = source / "child"
    elif collision == "existing":
        target.mkdir()
        (target / "sentinel").write_bytes(b"keep-existing")
    elif collision == "report-source":
        report = source / "new-report.json"
    elif collision == "report-existing":
        report.write_bytes(b"keep-report")
    else:
        report = target / "new-report.json"
    before = hashes(tmp_path)
    with pytest.raises(module.RecoveryError):
        getattr(module, operation)(str(source), str(target), str(report))
    assert hashes(tmp_path) == before


@pytest.mark.parametrize("mutation", ["future", "checksum", "missing-table", "broken-db", "orphan"])
def test_backup_refuses_damaged_or_unknown_database_without_mutating_source(tmp_path, mutation):
    module = recovery_module()
    source = fixture_source(tmp_path)
    if mutation == "broken-db":
        (source / "sessions.db").write_bytes(b"NOT A DATABASE")
    else:
        with closing(sqlite3.connect(source / "sessions.db")) as conn, conn:
            if mutation == "future":
                conn.execute("INSERT INTO schema_migrations VALUES(99,'future',200)")
            elif mutation == "checksum":
                conn.execute("UPDATE schema_migrations SET checksum='wrong' WHERE version=1")
            elif mutation == "missing-table":
                conn.execute("DROP TABLE evaluations")
            else:
                conn.execute("UPDATE messages SET session_id='nonexistent' WHERE id=41")
    before = hashes(source)
    with pytest.raises(module.RecoveryError):
        module.backup(str(source), str(tmp_path / "artifact"), str(tmp_path / "report.json"))
    assert hashes(source) == before
    assert not (tmp_path / "report.json").exists()


@pytest.mark.parametrize("mutation", ["database", "sidecar", "missing", "extra", "escape", "duplicate", "false-schema", "wrong-version"])
def test_restore_refuses_tampered_backup_before_creating_target(tmp_path, mutation):
    module = recovery_module()
    source = fixture_source(tmp_path)
    artifact = tmp_path / "artifact"
    module.backup(str(source), str(artifact), str(tmp_path / "first-report.json"))
    manifest_path = artifact / "recovery-manifest.json"
    if mutation == "database":
        with closing(sqlite3.connect(artifact / "sessions.db")) as conn, conn:
            conn.execute("UPDATE sessions SET questions_asked=99 WHERE id='old'")
    elif mutation == "sidecar":
        (artifact / "audit-gap.json").write_bytes(b"tampered")
    elif mutation == "missing":
        (artifact / "audit-gap.json").unlink()
    elif mutation == "extra":
        (artifact / "extra.json").write_bytes(b"unknown")
    elif mutation == "duplicate":
        manifest_path.write_text('{"schemaVersion":1,"schemaVersion":1}', encoding="utf-8")
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if mutation == "escape":
            manifest["files"]["../escaped"] = "0" * 64
        elif mutation == "false-schema":
            manifest["schemaVersion"] = True
        else:
            manifest["migrationVersion"] = 1
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = hashes(artifact)
    with pytest.raises(module.RecoveryError):
        module.restore(str(artifact), str(tmp_path / "restored"), str(tmp_path / "report.json"))
    assert hashes(artifact) == before
    assert not (tmp_path / "restored").exists()
    assert not (tmp_path / "report.json").exists()


@pytest.mark.parametrize("input_kind", ["missing-db", "unknown-file", "unknown-directory", "env", "trace-nested"])
def test_backup_refuses_unrecognized_data_instead_of_silently_dropping_it(tmp_path, input_kind):
    module = recovery_module()
    source = fixture_source(tmp_path)
    if input_kind == "missing-db":
        (source / "sessions.db").unlink()
    elif input_kind == "unknown-directory":
        (source / "unknown").mkdir()
    elif input_kind == "trace-nested":
        (source / "traces" / "nested").mkdir()
    else:
        (source / (".env" if input_kind == "env" else "unknown.json")).write_bytes(b"PRIVATE_UNKNOWN")
    before = hashes(source)
    with pytest.raises(module.RecoveryError):
        module.backup(str(source), str(tmp_path / "artifact"), str(tmp_path / "report.json"))
    assert hashes(source) == before
    assert not (tmp_path / "artifact").exists()


def test_backup_refuses_source_changes_during_real_copy(tmp_path, monkeypatch):
    module = recovery_module()
    source = fixture_source(tmp_path)
    original_copy = module.shutil.copy2

    def changing_copy(*args, **kwargs):
        result = original_copy(*args, **kwargs)
        (source / "audit-gap.json").write_bytes(b"SOURCE_CHANGED_DURING_COPY")
        return result

    monkeypatch.setattr(module.shutil, "copy2", changing_copy)
    with pytest.raises(module.RecoveryError):
        module.backup(str(source), str(tmp_path / "artifact"), str(tmp_path / "report.json"))
    assert not (tmp_path / "report.json").exists()
    assert (source / "audit-gap.json").read_bytes() == b"SOURCE_CHANGED_DURING_COPY"


@pytest.mark.parametrize("operation", ["backup", "restore"])
def test_recovery_refuses_real_runtime_paths_without_reading_them(tmp_path, operation):
    module = recovery_module()
    from app.config import BACKEND_DIR
    with pytest.raises(module.RecoveryError):
        getattr(module, operation)(str(BACKEND_DIR / "data"), str(tmp_path / "target"),
                                   str(tmp_path / "report.json"))
    assert not (tmp_path / "target").exists()


def test_cli_fixed_failure_does_not_expose_private_paths(tmp_path, capsys):
    module = recovery_module()
    assert module.main(["backup", "--source", "relative-PRIVATE_PATH", "--target", str(tmp_path / "target"),
                        "--report", str(tmp_path / "report.json")]) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {"status": "failed", "code": "recovery_refused_or_failed",
                                        "productionReady": False}


@pytest.mark.parametrize("operation", ["backup", "restore"])
def test_recovery_detects_corrupted_auxiliary_copy_not_just_unchanged_input(tmp_path, monkeypatch, operation):
    module = recovery_module()
    source = fixture_source(tmp_path)
    if operation == "restore":
        module.backup(str(source), str(tmp_path / "artifact"), str(tmp_path / "first-report.json"))
        source = tmp_path / "artifact"
    before = hashes(source)
    original_copy = module.shutil.copy2

    def corrupted_copy(src, dst, *args, **kwargs):
        result = original_copy(src, dst, *args, **kwargs)
        if str(dst).endswith("audit-gap.json"):
            with open(dst, "wb") as handle:
                handle.write(b"COPIED_BYTES_DO_NOT_MATCH_SOURCE")
        return result

    monkeypatch.setattr(module.shutil, "copy2", corrupted_copy)
    with pytest.raises(module.RecoveryError):
        getattr(module, operation)(str(source), str(tmp_path / "target"), str(tmp_path / "report.json"))
    assert hashes(source) == before
    assert not (tmp_path / "report.json").exists()


@pytest.mark.parametrize("kind", ["bytes", "files"])
def test_backup_local_bounds_fail_before_copying_or_hashing_oversize_payload(tmp_path, kind):
    module = recovery_module()
    source = fixture_source(tmp_path)
    if kind == "bytes":
        with (source / "audit-fallback.jsonl").open("wb") as handle:
            handle.truncate(64 * 1024 * 1024 + 1)
    else:
        for number in range(2001):
            (source / "traces" / f"{number}.jsonl").write_bytes(b"{}\n")
    with pytest.raises(module.RecoveryError):
        module.backup(str(source), str(tmp_path / "target"), str(tmp_path / "report.json"))
    assert not (tmp_path / "target").exists()


@pytest.mark.parametrize("link_kind", ["database", "trace", "source-root", "target-root"])
def test_recovery_rejects_real_links_without_reading_the_redirected_payload(tmp_path, link_kind):
    module = recovery_module()
    source = fixture_source(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.jsonl").write_bytes(b"OUTSIDE_PRIVATE_CANARY")
    target = tmp_path / "target"
    if link_kind == "database":
        (source / "sessions.db").rename(outside / "sessions.db")
        link, destination, is_dir = source / "sessions.db", outside / "sessions.db", False
    elif link_kind == "trace":
        link, destination, is_dir = source / "traces" / "escaped.jsonl", outside / "secret.jsonl", False
    elif link_kind == "source-root":
        link, destination, is_dir = tmp_path / "alias", source, True
        source = link
    else:
        link, destination, is_dir = tmp_path / "target-alias", outside, True
        target = link / "new-target"
    try:
        os.symlink(destination, link, target_is_directory=is_dir)
    except OSError:
        pytest.skip("Native symlink creation unavailable; no redirect test success claimed")
    before = hashes(outside)
    with pytest.raises(module.RecoveryError):
        module.backup(str(source), str(target), str(tmp_path / "report.json"))
    assert hashes(outside) == before
    assert not (tmp_path / "report.json").exists()


def test_cli_actual_success_uses_explicit_new_outputs_and_safe_metadata(tmp_path, capsys):
    module = recovery_module()
    source = fixture_source(tmp_path)
    assert module.main(["backup", "--source", str(source), "--target", str(tmp_path / "artifact"),
                        "--report", str(tmp_path / "report.json")]) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "passed", "operation": "backup",
                                                 "migrationVersion": 4, "productionReady": False}
    assert module.main(["restore", "--source", str(tmp_path / "artifact"),
                        "--target", str(tmp_path / "restored"), "--report", str(tmp_path / "restore-report.json")]) == 0
    assert json.loads(capsys.readouterr().out)["operation"] == "restore"


@pytest.mark.skipif(os.name != "nt", reason="Native NTFS junction boundary")
@pytest.mark.parametrize("junction_kind", ["source", "target", "trace"])
def test_recovery_rejects_ntfs_directory_junctions(tmp_path, junction_kind):
    module = recovery_module()
    source = fixture_source(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.jsonl").write_bytes(b"OUTSIDE_JUNCTION_CANARY")
    target = tmp_path / "target"
    if junction_kind == "source":
        link, destination = tmp_path / "alias", source
        source = link
    elif junction_kind == "target":
        link, destination = tmp_path / "alias", outside
        target = link / "new-target"
    else:
        # Empty the owned synthetic trace directory by moving only its one file,
        # then remove only that known empty directory before making a junction.
        (source / "traces" / "synthetic.jsonl").rename(source / "verified_qa_pairs.jsonl")
        (source / "traces").rmdir()
        link, destination = source / "traces", outside
    completed = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(destination)],
                               capture_output=True, timeout=10, check=False)
    assert completed.returncode == 0, "Native owned-junction fixture creation failed"
    before = hashes(outside)
    with pytest.raises(module.RecoveryError):
        module.backup(str(source), str(target), str(tmp_path / "report.json"))
    assert hashes(outside) == before
    assert not (tmp_path / "report.json").exists()
