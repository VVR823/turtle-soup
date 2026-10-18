"""Immutable, source-bound internal evidence. Ranking grants no answer authority."""
from dataclasses import dataclass
from typing import Literal

from .baselines import SnapshotError, canonical_json, digest
from .question_normalization import normalize_exact_question
from .schemas import Soup


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    id: str
    soupId: str
    puzzleVersion: str
    sourcePath: str
    category: Literal["truth", "checkpoint", "confusion", "symbol", "metadata"]
    payload: str


def validate_puzzle_snapshot(soup: Soup, puzzle_version: str) -> None:
    if not isinstance(soup, Soup):
        raise SnapshotError("Evidence requires a valid puzzle snapshot")
    actual = "p1:" + digest({"schemaVersion": 1, "soup": soup.model_dump(mode="json")})
    if not isinstance(puzzle_version, str) or puzzle_version != actual:
        raise SnapshotError("Evidence puzzle snapshot mismatch")


def build_evidence_catalog(soup: Soup, puzzle_version: str) -> tuple[EvidenceRecord, ...]:
    validate_puzzle_snapshot(soup, puzzle_version)
    records = []

    def append(path, category, payload):
        identity = {"soupId": soup.id, "puzzleVersion": puzzle_version, "sourcePath": path,
                    "category": category, "payload": payload}
        records.append(EvidenceRecord("f1:" + digest(identity), soup.id, puzzle_version,
                                      path, category, canonical_json(payload)))

    if soup.bottom:
        append("bottom", "truth", {"text": soup.bottom})
    for field, category in (("truthItems", "truth"), ("checkpoints", "checkpoint"),
                            ("confusionPoints", "confusion"), ("symbolMappings", "symbol")):
        for index, record in enumerate(getattr(soup, field) or ()):
            append(f"{field}[{index}]", category, record.model_dump(mode="json"))
    if soup.genre:
        append("genre", "metadata", {"genre": soup.genre})
    if soup.castCount is not None:
        append("castCount", "metadata", {"castCount": soup.castCount})
    return tuple(records)


def retrieve_evidence(soup: Soup, question: str, *, puzzle_version: str,
                      limit: int = 8) -> tuple[EvidenceRecord, ...]:
    if type(limit) is not int or not 1 <= limit <= 8:
        raise ValueError("Evidence retrieval limit must be between 1 and 8")
    query = normalize_exact_question(question).lower()
    terms = {query[i:i + 2] for i in range(len(query) - 1)
             if query[i].isalnum() and query[i + 1].isalnum()}
    if len(query) == 1 and query.isalnum():
        terms.add(query)
    ranked = []
    for index, record in enumerate(build_evidence_catalog(soup, puzzle_version)):
        score = sum(term in record.payload.lower() for term in terms)
        if score:
            ranked.append((-score, index, record))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return tuple(item[2] for item in ranked[:limit])
