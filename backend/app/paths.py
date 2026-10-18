"""Filesystem identity used by settings and test guards; no content I/O."""
import os
import re
from pathlib import Path


def _strip_windows_namespace(value: str) -> str:
    # pathlib resolves os.devnull to a device; pytest's log sink needs it.
    if value.rstrip("\\/").lower() == "\\\\.\\nul":
        return "\\\\.\\NUL"
    if value[:8].lower() == "\\\\?\\unc\\":
        return "\\\\" + value[8:]
    if value.startswith(("\\\\?\\", "\\\\.\\")):
        tail = value[4:]
        if not re.match(r"^[A-Za-z]:[\\/]", tail):
            raise ValueError("Device namespace is not a supported data/file path")
        return tail
    return value


def canonical_path(path, *, resolve: bool = True) -> Path:
    raw = os.fsdecode(path)
    if os.name == "nt":
        raw = _strip_windows_namespace(raw)
    result = Path(raw).resolve() if resolve else Path(os.path.abspath(raw))
    if os.name == "nt":
        return Path(_strip_windows_namespace(str(result)))
    return result
