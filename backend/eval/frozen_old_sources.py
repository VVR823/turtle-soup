"""Verified whole TS01 source bytes in private owner modules, never a new host."""
import hashlib
import json
import random
import sys
from importlib.machinery import ModuleSpec
from importlib.util import module_from_spec
from pathlib import Path
from uuid import uuid4

from .contracts import DatasetError
from .legacy import _read_copy, checked_path

_ARCHIVE_ROOT = Path(__file__).with_name("frozen_ts01_sources")
_DIGEST = "255afe9f471ce2316734f0a9c9e30793dbd978ece9ba223d7d7bf53e7ffb6898"
_NAMES = ("backend/app/__init__.py", "backend/app/ai_host.py", "backend/app/rag.py",
    "backend/app/prompts.py", "backend/app/schemas.py", "backend/app/config.py",
    "backend/app/runtime.py", "backend/app/paths.py", "backend/app/rate_limit.py",
    "backend/app/testing.py", "backend/requirements.txt")
_ORDER = ("schemas", "paths", "config", "runtime", "rate_limit", "prompts", "rag", "testing", "ai_host")


def _verified_sources():
    """Validate every selected byte before permitting any old module execution."""
    try:
        from app.baselines import strict_json
        root = checked_path(_ARCHIVE_ROOT)
        if not root.is_dir() or root.is_symlink():
            raise ValueError("Fixed archive directory required")
        manifest = strict_json(_read_copy(checked_path(root / "source-manifest.json")))
        if (type(manifest) is not dict or type(manifest.get("schemaVersion")) is not int
            or manifest["schemaVersion"] != 1 or manifest.get("baselineId") != "ts01-captured-working-tree"
            or manifest.get("digest") != _DIGEST or manifest.get("pristineCommitAttested") is not False
            or manifest.get("productionStateAttested") is not False):
            raise ValueError("Fixed manifest identity required")
        records = manifest.get("sources")
        if (type(records) is not list or len(records) != len(_NAMES)
            or any(type(item) is not dict or tuple(item) != ("path", "sha256", "bytes")
                or item["path"] != name for item, name in zip(records, _NAMES))
            or hashlib.sha256(json.dumps(records, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest() != _DIGEST):
            raise ValueError("Original byte identity required")
        payloads = {}
        for item in records:
            filename = checked_path(root / (item["path"][8:] + ".raw"))
            raw = _read_copy(filename)
            if len(raw) != item["bytes"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise ValueError("Original bytes required")
            payloads[item["path"]] = (filename, raw)
        return records, payloads
    except Exception:
        raise DatasetError("eval_frozen_source_invalid") from None


def frozen_old_source_identity():
    records, _ = _verified_sources()
    return {"baselineId": "ts01-captured-working-tree", "digest": _DIGEST, "sources": records}


class FrozenOldModules:
    """Own module registrations only; the later driver owns its model resources."""
    def __init__(self):
        self._modules = {}
        self.closed = False

    def close(self):
        for name, module in reversed(tuple(self._modules.items())):
            if sys.modules.get(name) is module:
                del sys.modules[name]
        self.closed = True
        return True

    def _register(self, name, *, package=False, filename=None):
        if name in sys.modules:
            raise ValueError("Owner namespace collision")
        module = module_from_spec(ModuleSpec(name, loader=None, is_package=package))
        if filename is not None:
            module.__file__ = str(filename)
        sys.modules[name] = module
        self._modules[name] = module
        parent, _, child = name.rpartition(".")
        if parent in self._modules:
            setattr(self._modules[parent], child, module)
        return module


def load_frozen_old_modules(*, seed=0):
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise DatasetError("eval_frozen_source_invalid")
    _, payloads = _verified_sources()
    owned = FrozenOldModules()
    prefix = "eval._frozen_ts01_" + uuid4().hex
    try:
        owned._register(prefix, package=True)
        filename, raw = payloads["backend/app/__init__.py"]
        package = owned._register(prefix + ".app", package=True, filename=filename)
        exec(compile(raw, str(filename), "exec"), package.__dict__)
        loaded = {}
        for name in _ORDER:
            filename, raw = payloads["backend/app/" + name + ".py"]
            module = owned._register(prefix + ".app." + name, filename=filename)
            # Compile the already-verified bytes, not a second path read.
            exec(compile(raw, str(filename), "exec"), module.__dict__)
            loaded[name] = module
        owned.host = loaded["ai_host"]
        owned.config = loaded["config"]
        owned.runtime = loaded["runtime"]
        owned.rag = loaded["rag"]
        owned.schemas = loaded["schemas"]
        owned.host.random = random.Random(seed)
        return owned
    except BaseException as error:
        owned.close()
        if isinstance(error, KeyboardInterrupt):
            raise
        raise DatasetError("eval_frozen_source_invalid") from None
