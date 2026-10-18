"""Explicit stopped-copy parsing, independent of the old accuracy classifier."""
import hashlib
import io
import re
from pathlib import Path
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, StrictInt
from app.baselines import canonical_json
from app.paths import canonical_path
from .contracts import DatasetError, DatasetIssue, Digest, EvalCase, ExpectedLabel, Identity, PuzzleVersion, StrictDatasetModel
from app.schemas import AnswerType
from typing import get_args

MAX_SOURCE_BYTES = 100 * 1024 * 1024
MAX_LINE_BYTES = 32768
MAX_CASES = 5000
MAX_PHYSICAL_ROWS = 20000


class LegacySource(StrictDatasetModel):
    path: Path
    sourceId: Identity
    soupId: Identity
    puzzleVersion: PuzzleVersion
    format: Literal["player_host", "qa", "arrow", "alternating"]
    sourceGroup: Identity


class LegacyImport(StrictDatasetModel):
    cases: Annotated[tuple[EvalCase, ...], Field(max_length=MAX_CASES)]
    issues: Annotated[tuple[DatasetIssue, ...], Field(max_length=MAX_CASES)]
    physicalRows: Annotated[StrictInt, Field(ge=0, le=MAX_PHYSICAL_ROWS)]
    sourceDigest: Digest
    complete: bool


def checked_path(path: Path) -> Path:
    """No defaults, content scans, aliases, runtime ancestors, dotenv or desktop."""
    try:
        if not isinstance(path, Path) or not path.is_absolute() or canonical_path(path) != path.absolute() or path.is_symlink():
            raise ValueError("Explicit non-aliased path required")
        root = Path(__file__).resolve().parents[2]
        for protected in (root / "backend" / "data", root / "data", Path.home() / "Desktop"):
            protected = canonical_path(protected)
            if path == protected or path.is_relative_to(protected) or protected.is_relative_to(path):
                raise ValueError("Protected path")
        if any(part.lower().startswith(".env") for part in path.parts):
            raise ValueError("Configuration input refused")
        return path
    except Exception:
        raise DatasetError("dataset_source_invalid") from None


def _fingerprint(path):
    stat = path.stat()
    if not path.is_file() or stat.st_nlink != 1:
        raise DatasetError("dataset_source_invalid")
    if stat.st_size > MAX_SOURCE_BYTES:
        raise DatasetError("dataset_source_limit")
    return stat.st_size, stat.st_mtime_ns, stat.st_ino


def _read_copy(path):
    before = _fingerprint(path)
    with path.open("rb") as stream:
        raw = stream.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise DatasetError("dataset_source_limit")
    if _fingerprint(path) != before:
        raise DatasetError("dataset_source_changed")
    with path.open("rb") as stream:
        after = stream.read(MAX_SOURCE_BYTES + 1)
    if _fingerprint(path) != before or raw != after:
        raise DatasetError("dataset_source_changed")
    return raw


def parse_legacy_copy(source: LegacySource) -> LegacyImport:
    try:
        source = LegacySource.model_validate(source.model_dump(mode="python"))
        path = checked_path(source.path)
        raw = _read_copy(path)
        source_digest = hashlib.sha256(raw).hexdigest()
        cases, issues, pending = [], [], None
        rows = 0
        stream = io.BytesIO(raw)
        marker = ("玩家", "主持人") if source.format == "player_host" else ("问", "答")
        patterns = tuple(re.compile(r"^\s*(?:\[\d{2}:\d{2}:\d{2}\]\s*)?" + word + r"[：:] ?(.*)$") for word in marker)

        def issue(code, number, physical):
            if len(issues) >= MAX_CASES:
                raise DatasetError("dataset_source_limit")
            issues.append(DatasetIssue(code=code, lineNumber=number, sourceDigest=hashlib.sha256(physical).hexdigest()))

        def pair(question, answer, qnumber, anumber, qraw, araw):
            if len(cases) >= MAX_CASES:
                raise DatasetError("dataset_source_limit")
            if not answer.strip():
                issue("dataset_pair_incomplete", anumber, araw)
            identity = str(uuid5(NAMESPACE_URL, canonical_json({"sourceId": source.sourceId, "digest": source_digest,
                "questionLine": qnumber, "answerLine": anumber, "questionLineDigest": hashlib.sha256(qraw).hexdigest(),
                "answerLineDigest": hashlib.sha256(araw).hexdigest()})))
            proposed = ExpectedLabel(kind="answer", answer=answer) if answer in get_args(AnswerType) else None
            try:
                cases.append(EvalCase(caseId=identity, soupId=source.soupId, puzzleVersion=source.puzzleVersion,
                    question=question, caseType="single", split="regression", sourceGroup=source.sourceGroup,
                    familyGroup=source.sourceGroup + ":legacy" if len(source.sourceGroup) <= 193 else source.sourceGroup,
                    conversationId=None, contextIndex=None, categories=("legacy_unreviewed",), visibility="private",
                    origin="legacy", evidenceSourceDigest=source_digest, authorRole="legacy", reviewState="pending",
                    proposedLabel=proposed, rawLegacyExpected=answer, review=None))
            except ValueError:
                issue("dataset_case_invalid", qnumber, qraw)

        while True:
            line = stream.readline(MAX_LINE_BYTES + 1)
            if not line: break
            rows += 1
            if rows > MAX_PHYSICAL_ROWS: raise DatasetError("dataset_source_limit")
            number = rows
            if len(line) > MAX_LINE_BYTES:
                physical_hash = hashlib.sha256(line)
                while not line.endswith(b"\n"):
                    line = stream.readline(MAX_LINE_BYTES + 1)
                    if not line: break
                    physical_hash.update(line)
                if len(issues) >= MAX_CASES: raise DatasetError("dataset_source_limit")
                issues.append(DatasetIssue(code="dataset_line_limit", lineNumber=number, sourceDigest=physical_hash.hexdigest()))
                continue
            if not line.endswith(b"\n"):
                issue("dataset_partial_tail", number, line)
                continue
            try:
                text = line.decode("utf-8").removesuffix("\n").removesuffix("\r")
            except UnicodeError:
                issue("dataset_utf8_invalid", number, line)
                continue
            if not text.strip(): continue
            if source.format == "arrow":
                match = re.fullmatch(r"\s*\d+[.、] ?(.+?)\s*(?:→|->|=>) ?(.+)", text)
                if not match: issue("dataset_line_invalid", number, line)
                else: pair(match[1], match[2], number, number, line, line)
            elif source.format == "alternating":
                if pending is None: pending = (text, number, line)
                else:
                    pair(pending[0], text, pending[1], number, pending[2], line); pending = None
            else:
                question, answer = patterns[0].fullmatch(text), patterns[1].fullmatch(text)
                if question:
                    if pending is not None: issue("dataset_pair_incomplete", pending[1], pending[2])
                    pending = (question[1], number, line)
                elif answer and pending is not None:
                    pair(pending[0], answer[1], pending[1], number, pending[2], line); pending = None
                else:
                    issue("dataset_line_invalid", number, line)
        if pending is not None: issue("dataset_pair_incomplete", pending[1], pending[2])
        return LegacyImport(cases=tuple(cases), issues=tuple(issues), physicalRows=rows,
                            sourceDigest=source_digest, complete=not issues)
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("dataset_source_invalid") from None
