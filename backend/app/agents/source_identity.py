"""Trusted source identity, not an OS sandbox or arbitrary Python attestation.

Fixed registered modules only. Compare currently loaded native function code
with the source being signed, reject post-load edits, then pin the full bytes
for this process. No file reads, application initialization or imports of the
registry occur until the server explicitly requests a repair suite identity.
"""
import hashlib
import importlib
import inspect
import sys
from threading import Lock
from types import CodeType, FunctionType

from .. import _PROCESS_SOURCE_STARTED_NS
from .contracts import AgentError

_LOCK = Lock()
_PINNED = {}


def _code_tree(code):
    yield code
    for value in code.co_consts:
        if isinstance(value, CodeType):
            yield from _code_tree(value)


def _native_functions(module):
    for value in vars(module).values():
        if isinstance(value, FunctionType) and value.__module__ == module.__name__:
            yield inspect.unwrap(value)
        elif isinstance(value, type) and value.__module__ == module.__name__:
            for member in vars(value).values():
                if isinstance(member, (classmethod, staticmethod)):
                    member = member.__func__
                members = (member.fget, member.fset, member.fdel) if isinstance(member, property) else (member,)
                for function in members:
                    if isinstance(function, FunctionType):
                        yield inspect.unwrap(function)


def verified_process_sources(root, names):
    """No caller/model paths: names originate solely in the fixed registry."""
    sources = {}
    with _LOCK:
        for name in names:
            path = (root / name).resolve()
            relative = path.relative_to(root.parent)
            module_name = ".".join(relative.with_suffix("").parts)
            if module_name.endswith(".__init__"):
                module_name = module_name[:-9]
            module = importlib.import_module(module_name)
            if (path != path.__class__(module.__file__).resolve()
                or path.stat().st_mtime_ns > _PROCESS_SOURCE_STARTED_NS):
                raise AgentError("agent_source_reload_required", 409)
            payload = path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            key = str(path)
            if key in _PINNED and _PINNED[key] != digest:
                raise AgentError("agent_source_reload_required", 409)
            # compile does not execute source. Compare loaded functions rather
            # than a .pyc that another process could have replaced. Decorated
            # native functions are unwrapped; generated/test hook code is not
            # claimed as OS isolation and has no authority from model JSON.
            compiled = compile(payload, str(path), "exec", dont_inherit=True, optimize=sys.flags.optimize)
            codes = {}
            for code in _code_tree(compiled):
                codes.setdefault(code.co_qualname, []).append(code)
            for function in _native_functions(module):
                actual = function.__code__
                if actual.co_filename != str(path):
                    continue
                if actual not in codes.get(actual.co_qualname, ()):
                    raise AgentError("agent_source_reload_required", 409)
            sources[name] = digest
        # Failed captures must not partially pin an invalid registry.
        _PINNED.update({str((root / name).resolve()): digest for name, digest in sources.items()})
    return sources
