"""Conservative exact identity, never a fuzzy retrieval or semantic transform."""
import re
import unicodedata

NORMALIZATION_VERSION = "exact-v1"


def normalize_exact_question(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("Exact question must be text")
    value = " ".join(unicodedata.normalize("NFC", text).split())
    value = re.sub(r"[?？]+$", "", value).strip()
    if not value:
        raise ValueError("Exact question must not be empty")
    return value
