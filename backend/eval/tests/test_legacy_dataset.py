"""Explicit legacy copies retain every physical input, never filtered accuracy."""
import hashlib
from pathlib import Path

import pytest


def source(path, *, format="qa"):
    from eval.legacy import LegacySource
    return LegacySource(path=path, sourceId="owned-copy-1", soupId="eval-synthetic",
        puzzleVersion="p1:" + "a" * 64, format=format, sourceGroup="old-batch-1")


@pytest.mark.parametrize("format,raw,rows", [
    ("player_host", "[00:00:20] 玩家：谁？\n主持人：不确定\n", 2),
    ("qa", "问：谁？\n答：不重要\n", 2),
    ("arrow", "1. 谁？ → 不确定\n", 1),
    ("alternating", "谁？\n不重要\n\n", 3),
])
def test_all_formats_preserve_short_non_yes_no_and_meta_claim(tmp_path, format, raw, rows):
    from eval.legacy import parse_legacy_copy
    path = tmp_path / "legacy.txt"; path.write_bytes(raw.encode("utf-8")); before = path.read_bytes()
    imported = parse_legacy_copy(source(path, format=format))
    assert imported.complete is True and imported.physicalRows == rows and imported.issues == ()
    assert imported.sourceDigest == hashlib.sha256(before).hexdigest()
    assert len(imported.cases) == 1 and imported.cases[0].question == "谁？"
    assert imported.cases[0].rawLegacyExpected in {"不确定", "不重要"}
    assert imported.cases[0].proposedLabel is None and imported.cases[0].review is None
    assert imported.cases[0].split == "regression" and imported.cases[0].authorRole == "legacy"
    assert path.read_bytes() == before


def test_duplicate_physical_pairs_have_distinct_stable_identity(tmp_path):
    from eval.legacy import parse_legacy_copy
    path = tmp_path / "duplicates.txt"; path.write_text("问：有灯吗？\n答：是\n问：有灯吗？\n答：是\n", encoding="utf-8")
    first = parse_legacy_copy(source(path)); again = parse_legacy_copy(source(path))
    assert len(first.cases) == 2 and first.cases[0].caseId != first.cases[1].caseId
    assert tuple(c.caseId for c in first.cases) == tuple(c.caseId for c in again.cases)
    assert first.cases[0].proposedLabel.answer == "是" and first.cases[0].reviewState == "pending"


@pytest.mark.parametrize("tail,code", [
    (b"unmatched header\n", "dataset_line_invalid"),
    ("问：遗留问题？\n".encode(), "dataset_pair_incomplete"),
    (b"\xff\n", "dataset_utf8_invalid"),
    ("问：尾巴？".encode(), "dataset_partial_tail"),
])
def test_valid_pairs_are_retained_but_bad_tail_blocks_completeness(tmp_path, tail, code, capsys):
    from eval.legacy import parse_legacy_copy
    path = tmp_path / "tail.txt"; path.write_bytes("问：原问题？\n答：是\n".encode() + tail); before = path.read_bytes()
    result = parse_legacy_copy(source(path))
    assert len(result.cases) == 1 and result.complete is False
    assert code in {issue.code for issue in result.issues}
    assert all(issue.lineNumber >= 3 and len(issue.sourceDigest) == 64 for issue in result.issues)
    assert "原问题" not in capsys.readouterr().out and path.read_bytes() == before


def test_unmatched_question_is_not_overwritten_by_next_question(tmp_path):
    from eval.legacy import parse_legacy_copy
    path = tmp_path / "orphan.txt"; path.write_text("问：被漏掉？\n问：下一条？\n答：不是\n", encoding="utf-8")
    result = parse_legacy_copy(source(path))
    assert result.complete is False and len(result.cases) == 1
    assert result.cases[0].question == "下一条？"
    assert any(i.lineNumber == 1 and i.code == "dataset_pair_incomplete" for i in result.issues)


def test_line_limit_retains_explicit_issue_without_partial_question(tmp_path):
    from eval.legacy import parse_legacy_copy
    path = tmp_path / "long.txt"; path.write_bytes(b"x" * 32769 + b"\n")
    result = parse_legacy_copy(source(path, format="arrow"))
    assert not result.complete and result.cases == ()
    assert result.issues[0].code == "dataset_line_limit"


def test_file_limit_refuses_without_partial_output(tmp_path):
    from eval.contracts import DatasetError
    from eval.legacy import parse_legacy_copy
    path = tmp_path / "large.txt"
    with path.open("wb") as stream: stream.truncate(100 * 1024 * 1024 + 1)
    with pytest.raises(DatasetError) as error: parse_legacy_copy(source(path))
    assert error.value.code == "dataset_source_limit"


def test_more_than_5000_pairs_refuses_instead_of_truncating(tmp_path):
    from eval.contracts import DatasetError
    from eval.legacy import parse_legacy_copy
    path = tmp_path / "many.txt"; path.write_text("问：谁？\n答：是\n" * 5001, encoding="utf-8")
    with pytest.raises(DatasetError) as error: parse_legacy_copy(source(path))
    assert error.value.code == "dataset_source_limit"


def test_source_change_between_complete_reads_refuses(tmp_path, monkeypatch):
    from eval.contracts import DatasetError
    from eval.legacy import parse_legacy_copy
    path = tmp_path / "changing.txt"; original = "问：谁？\n答：是\n".encode(); path.write_bytes(original)
    real_open = Path.open; calls = 0
    class ChangeAfterRead:
        def __init__(self, handle): self.handle = handle
        def __enter__(self): return self.handle
        def __exit__(self, *args):
            self.handle.close()
            with real_open(path, "wb") as stream: stream.write("问：谁？\n答：不是\n".encode())
    def opening(self, *args, **kwargs):
        nonlocal calls
        handle = real_open(self, *args, **kwargs)
        if self == path and args and args[0] == "rb":
            calls += 1
            if calls == 1: return ChangeAfterRead(handle)
        return handle
    monkeypatch.setattr(Path, "open", opening)
    with pytest.raises(DatasetError) as error: parse_legacy_copy(source(path))
    assert error.value.code == "dataset_source_changed" and calls >= 1


@pytest.mark.parametrize("unsafe", ["relative", "runtime", "env", "alias", "format"])
def test_parser_refuses_implicit_private_alias_and_unsupported_inputs(tmp_path, unsafe):
    from eval.contracts import DatasetError
    from eval.legacy import parse_legacy_copy
    path = tmp_path / "copy.txt"; path.write_text("问：谁？\n答：是\n", encoding="utf-8")
    if unsafe == "relative": path = Path("copy.txt")
    if unsafe == "runtime": path = Path(__file__).resolve().parents[3] / "backend" / "data" / "never-read.txt"
    if unsafe == "env": path = tmp_path / ".env.copy"; path.write_text("private-synthetic", encoding="utf-8")
    if unsafe == "alias": path = tmp_path / "child" / ".." / "copy.txt"
    with pytest.raises((DatasetError, ValueError)):
        parse_legacy_copy(source(path, format="auto" if unsafe == "format" else "qa"))


def test_empty_answer_stays_visible_but_copy_is_incomplete(tmp_path):
    from eval.legacy import parse_legacy_copy
    path = tmp_path / "empty-answer.txt"; path.write_text("问：谁？\n答：\n", encoding="utf-8")
    result = parse_legacy_copy(source(path))
    assert len(result.cases) == 1 and result.cases[0].rawLegacyExpected == ""
    assert result.cases[0].review is None and result.complete is False
    assert any(i.code == "dataset_pair_incomplete" and i.lineNumber == 2 for i in result.issues)


def test_configuration_filename_case_alias_is_refused_without_reading(tmp_path):
    from eval.contracts import DatasetError
    from eval.legacy import parse_legacy_copy
    path = tmp_path / ".ENV.synthetic"; path.write_text("问：谁？\n答：是\n", encoding="utf-8")
    with pytest.raises(DatasetError): parse_legacy_copy(source(path))


def test_structural_marker_removal_does_not_rewrite_question_or_free_text_claim(tmp_path):
    from eval.legacy import parse_legacy_copy
    path = tmp_path / "raw-spaces.txt"; path.write_text("问：  谁？  \n答：可能是，而且因为其他事\n", encoding="utf-8")
    result = parse_legacy_copy(source(path))
    assert result.cases[0].question == " 谁？  "
    assert result.cases[0].rawLegacyExpected == "可能是，而且因为其他事"
    assert result.cases[0].proposedLabel is None
