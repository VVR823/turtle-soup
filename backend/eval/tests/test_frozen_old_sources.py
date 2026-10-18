"""Actual fixed old algorithms; synthetic inputs are not quality labels."""
import sys
import builtins
import hashlib
import json
import os
import shutil

import pytest

from eval.contracts import DatasetError


def test_actual_old_host_keeps_negation_loss_in_keyword_rag():
    # Replacing this loader with new exact host/rules hides the baseline defect.
    from eval.frozen_old_sources import load_frozen_old_modules
    owned = load_frozen_old_modules(seed=5)
    assert owned is not None, "Fixed old algorithm was not loaded"
    try:
        soup = owned.schemas.Soup(id="synthetic-old-door", title="Synthetic", surface="A door.",
            bottom="A door exists.", checkpoints=[{"key": "门", "answer": True}])
        result = owned.host.handle_host_response(soup, [], "没有门吗")
        assert result["reply"] == "是" and result["matched_checkpoint"] == "门"
        assert owned.rag.extract_core("没有门吗") == "门"
    finally:
        assert owned.close()


@pytest.mark.parametrize("damage", ["bytes", "forged_manifest", "missing", "hardlink"])
def test_bad_archive_is_rejected_before_any_old_code_runs(tmp_path, monkeypatch, damage):
    # A self-consistent forged manifest or skipped file hash must not execute code.
    import eval.frozen_old_sources as source
    archive = tmp_path / "owned-archive"
    shutil.copytree(source._ARCHIVE_ROOT, archive)
    payload = archive / "app" / "ai_host.py.raw"
    marker = b'\nsetattr(__import__("builtins"), "_a46_payload_executed", True)\n'
    if damage in {"bytes", "forged_manifest"}:
        payload.write_bytes(payload.read_bytes() + marker)
        if damage == "forged_manifest":
            manifest_path = archive / "source-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for record in manifest["sources"]:
                if record["path"] == "backend/app/ai_host.py":
                    record.update(sha256=hashlib.sha256(payload.read_bytes()).hexdigest(), bytes=payload.stat().st_size)
            manifest["digest"] = hashlib.sha256(json.dumps(manifest["sources"], separators=(",", ":")).encode()).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif damage == "missing":
        payload.unlink()  # Only this pytest-owned copy, never original archive.
    else:
        os.link(payload, archive / "owned-second-link.raw")
    monkeypatch.setattr(source, "_ARCHIVE_ROOT", archive)
    monkeypatch.delattr(builtins, "_a46_payload_executed", raising=False)
    before = set(sys.modules)
    with pytest.raises(DatasetError, match="eval_frozen_source_invalid"):
        source.load_frozen_old_modules()
    assert not hasattr(builtins, "_a46_payload_executed")
    assert not {name for name in set(sys.modules) - before if name.startswith("eval._frozen_ts01_")}


def test_import_failure_removes_only_owned_partial_modules(monkeypatch):
    # A failed final old-module import must not leave previous owner modules behind.
    from app import ai_host as modern_host
    from eval.frozen_old_sources import load_frozen_old_modules
    original_import = builtins.__import__
    def fail_external(name, *args, **kwargs):
        if name == "langchain_openai":
            raise ImportError("Synthetic external dependency failure")
        return original_import(name, *args, **kwargs)
    before = set(sys.modules)
    monkeypatch.setattr(builtins, "__import__", fail_external)
    with pytest.raises(DatasetError, match="eval_frozen_source_invalid"):
        load_frozen_old_modules()
    assert sys.modules["app.ai_host"] is modern_host
    assert not {name for name in set(sys.modules) - before if name.startswith("eval._frozen_ts01_")}


def test_loader_does_not_accept_caller_module_or_source_path(tmp_path):
    from eval.frozen_old_sources import load_frozen_old_modules
    with pytest.raises(TypeError):
        load_frozen_old_modules(source_path=tmp_path)


def test_verified_identity_is_available_without_executing_any_old_module():
    # An identity helper must verify real bytes, not load a default legacy runtime.
    from eval.frozen_old_sources import frozen_old_source_identity
    before = set(sys.modules)
    identity = frozen_old_source_identity()
    assert identity["baselineId"] == "ts01-captured-working-tree"
    assert identity["digest"] == "255afe9f471ce2316734f0a9c9e30793dbd978ece9ba223d7d7bf53e7ffb6898"
    assert len(identity["sources"]) == 11
    assert not {name for name in set(sys.modules) - before if name.startswith("eval._frozen_ts01_")}


def test_cancelled_import_cleans_partial_owner_and_preserves_interrupt(monkeypatch):
    # Catching only Exception leaks modules; swallowing cancellation hides a stop.
    import eval.frozen_old_sources as source
    original_compile = builtins.compile
    def cancelled_compile(raw, filename, mode):
        if str(filename).endswith("rate_limit.py.raw"):
            raise KeyboardInterrupt()
        return original_compile(raw, filename, mode)
    monkeypatch.setattr(source, "compile", cancelled_compile, raising=False)
    before = set(sys.modules)
    with pytest.raises(KeyboardInterrupt):
        source.load_frozen_old_modules()
    assert not {name for name in set(sys.modules) - before if name.startswith("eval._frozen_ts01_")}


def test_close_does_not_remove_replacement_module_owned_by_someone_else(monkeypatch):
    # Cleanup by name alone can remove a later owner instead of our registration.
    from types import ModuleType
    from eval.frozen_old_sources import load_frozen_old_modules
    owner = load_frozen_old_modules()
    replacement = ModuleType(owner.host.__name__)
    monkeypatch.setitem(sys.modules, owner.host.__name__, replacement)
    try:
        assert owner.close()
        assert sys.modules[owner.host.__name__] is replacement
    finally:
        owner.close()


def test_owner_close_preserves_other_old_owner_and_modern_app():
    # Sharing/removing global modules would destroy another baseline evaluation.
    from app import ai_host as modern_host
    from eval.frozen_old_sources import load_frozen_old_modules
    before = dict(sys.modules)
    first = load_frozen_old_modules(seed=9)
    second = load_frozen_old_modules(seed=9)
    assert first is not None and second is not None, "Two independent owners required"
    try:
        assert first.host is not second.host and first.runtime is not second.runtime
        assert first.host.random is not second.host.random
        assert first.host.random.random() == second.host.random.random()
        assert first.close() and first.close()
        assert sys.modules[second.host.__name__] is second.host
        assert second.host.is_yes_no_question("有门吗")
        assert sys.modules["app.ai_host"] is modern_host
        for name, module in before.items():
            if name == "app" or name.startswith("app."):
                assert sys.modules.get(name) is module
    finally:
        assert first.close() and second.close()
    assert first.host.__name__ not in sys.modules and second.host.__name__ not in sys.modules


@pytest.mark.parametrize("seed", [True, -1, 2**63, 1.0, "1", None])
def test_invalid_seed_is_rejected_before_loading(seed):
    # bool/int coercion, oversized or caller-owned identity must not enter code.
    from eval.frozen_old_sources import load_frozen_old_modules
    before = set(sys.modules)
    with pytest.raises(DatasetError, match="eval_frozen_source_invalid"):
        load_frozen_old_modules(seed=seed)
    assert not {name for name in set(sys.modules) - before if name.startswith("eval._frozen_ts01_")}


def test_loading_and_deterministic_query_do_not_construct_http_or_load_dotenv(monkeypatch):
    # An unsafe _get_llm/config import cannot silently reach personal config/cloud.
    import httpx
    import dotenv
    from eval.frozen_old_sources import load_frozen_old_modules
    def forbidden(*args, **kwargs):
        raise AssertionError("No HTTP/config construction permitted")
    monkeypatch.setattr(httpx, "Client", forbidden)
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    monkeypatch.setattr(dotenv, "dotenv_values", forbidden)
    owned = load_frozen_old_modules(seed=1)
    assert owned is not None, "Fixed owner required"
    try:
        assert owned.runtime._standalone is None
        soup = owned.schemas.Soup(id="synthetic-local", title="Synthetic", surface="Empty.",
            bottom="Empty.", genre="本格")
        assert owned.host.handle_host_response(soup, [], "这是本格吗")["reply"] == "是"
        assert owned.runtime._standalone is None
    finally:
        assert owned.close()
