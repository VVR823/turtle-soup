"""Literal coverage targets and authored fact proposals, not quality scores."""
import pytest

from .test_dataset_grouping import sources


def six_catalog(base):
    from app.baselines import RULE_FIELDS, canonical_json, digest
    from app.rule_contract import RuleSnapshot
    from app.schemas import Soup
    from eval.contracts import EvalPuzzle
    puzzles = []
    for index in range(6):
        soup = Soup.model_validate_json(base[0].soupJson).model_copy(update={"id": f"synthetic-{index}"})
        raw = soup.model_dump(mode="json"); p1 = "p1:" + digest({"schemaVersion": 1, "soup": raw})
        rules = {"schemaVersion": 1, "rulesBySoup": {soup.id: {f: raw[f] for f in RULE_FIELDS}}}
        manifest = {"schemaVersion": 1, "puzzleVersions": {soup.id: p1}, "origin": "legacy-baseline"}
        r1 = "r1:" + digest({"rules": rules, "manifest": manifest})
        puzzles.append(EvalPuzzle(soupId=soup.id, puzzleVersion=p1, soupJson=canonical_json(raw),
            ruleSnapshot=RuleSnapshot(soupId=soup.id, puzzleVersion=p1, ruleVersion=r1, exactRules=(),
                releaseRulesJson=canonical_json(rules), releaseManifestJson=canonical_json(manifest))))
    return tuple(puzzles)


def request110(catalog):
    from app.host_evidence import build_evidence_catalog
    from app.schemas import Soup
    from eval.drafts import DraftEntry, DraftRequest
    puzzles = six_catalog(catalog); entries = []
    for n in range(110):
        index = n % 6; puzzle = puzzles[index]
        kind = "single" if n < 60 else ("context" if n < 90 else "control")
        group = f"context-{(n - 60) // 3}" if kind == "context" else f"question-{n}"
        if kind == "context": puzzle = puzzles[((n - 60) // 3) % 6]
        fact = build_evidence_catalog(Soup.model_validate_json(puzzle.soupJson), puzzle.puzzleVersion)[0].id
        entries.append(DraftEntry(soupId=puzzle.soupId, question=f"Owned synthetic question {n}?", caseType=kind,
            sourceGroup=group, familyGroup=group, conversationId=group if kind == "context" else None,
            contextIndex=(n - 60) % 3 + 1 if kind == "context" else None, categories=(kind,), proposedLabel=None,
            factIds=(fact,)))
    return DraftRequest(catalog=puzzles, entries=tuple(entries), authorBatchId="synthetic-110-test-only", collectedAt="2026-10-09T00:00:00Z")


def audited(cases, *, source_complete=True):
    from eval.grouping import audit_groups
    return audit_groups(cases, repair_cases=(), source_digests=sources(cases), source_complete=source_complete)


def test_pending_110_has_literal_scale_and_no_human_confirmation(catalog):
    from eval.drafts import build_pending_draft
    from eval.inventory import inventory
    cases = build_pending_draft(request110(catalog)); counted = inventory(cases, audit=audited(cases), source_digests=sources(cases))
    assert len(cases) == 110
    assert (counted.inputCount, counted.singleCount, counted.singleSoupCount, counted.contextGroupCount,
        counted.contextDecisionCount, counted.controlCount) == (110, 60, 6, 10, 30, 20)
    assert counted.pendingCount == 110 and counted.eligibleCount == 0
    assert (counted.deficits.single, counted.deficits.soups, counted.deficits.contextGroups, counted.deficits.controls) == (0, 0, 0, 0)
    assert all(c.authorRole == "ai_draft" and c.review is None and c.split == "holdout_candidate" for c in cases)
    assert "accuracy" not in counted.model_dump_json()


def test_missing_inputs_and_partial_context_report_actual_shortfall(catalog):
    from eval.drafts import build_pending_draft
    from eval.inventory import inventory
    cases = build_pending_draft(request110(catalog))
    selected = cases[:59] + cases[60:89] + cases[90:109]
    counted = inventory(selected, audit=audited(selected), source_digests=sources(selected))
    assert counted.inputCount == 107 and counted.singleCount == 59 and counted.controlCount == 19
    assert counted.contextGroupCount == 9 and counted.contextDecisionCount == 29
    assert (counted.deficits.single, counted.deficits.contextGroups, counted.deficits.controls) == (1, 1, 1)
    assert counted.issueCount >= 1 and counted.eligibleCount == 0


def test_draft_roundtrip_retains_proposed_fact_ids_and_change_invalidates_receipt(catalog):
    from eval.drafts import build_pending_draft
    from eval.contracts import EvalCase, case_digest
    request = request110(catalog); cases = build_pending_draft(request)
    assert cases[0].model_dump(mode="json").get("proposedFactIds") == list(request.entries[0].factIds)
    assert EvalCase.model_validate_json(cases[0].model_dump_json()).proposedFactIds == cases[0].proposedFactIds
    assert case_digest(cases[0].model_copy(update={"proposedFactIds": ()})) != case_digest(cases[0])
    assert tuple(c.caseId for c in cases) == tuple(c.caseId for c in build_pending_draft(request))


@pytest.mark.parametrize("change", ["foreign-fact", "unknown-soup", "duplicate-entry", "coerced-time"])
def test_draft_builder_refuses_foreign_or_ambiguous_authoring(catalog, change):
    from eval.contracts import DatasetError
    from eval.drafts import build_pending_draft
    request = request110(catalog)
    if change == "foreign-fact": entries = (request.entries[0].model_copy(update={"factIds": ("f1:" + "b" * 64,)}),) + request.entries[1:]
    elif change == "unknown-soup": entries = (request.entries[0].model_copy(update={"soupId": "foreign"}),) + request.entries[1:]
    elif change == "duplicate-entry": entries = request.entries + (request.entries[0],)
    else: entries = request.entries
    request = request.model_copy(update={"entries": entries, **({"collectedAt": "today"} if change == "coerced-time" else {})})
    with pytest.raises(DatasetError): build_pending_draft(request)


def test_public_synthetic_cannot_satisfy_real_coverage_targets(pending):
    from eval.contracts import EvalCase
    from eval.grouping import audit_groups
    from eval.inventory import inventory
    body = pending.model_dump(mode="python"); body.update(origin="public_synthetic", authorRole="synthetic", split="dev", visibility="public_authorized")
    c = EvalCase.model_validate(body)
    report = audit_groups((), repair_cases=(c,), source_digests=sources((c,)), source_complete=True)
    counted = inventory((c,), audit=report, source_digests=sources((c,)))
    assert counted.inputCount == 1 and counted.singleCount == 0 and counted.singleSoupCount == 0
    assert counted.deficits.single == 60 and counted.deficits.soups == 6 and counted.eligibleCount == 0


def test_inventory_does_not_reuse_audit_after_omitting_case(catalog):
    from eval.contracts import DatasetError
    from eval.drafts import build_pending_draft
    from eval.inventory import inventory
    cases = build_pending_draft(request110(catalog)); original = audited(cases)
    with pytest.raises(DatasetError): inventory(cases[:-1], audit=original, source_digests=sources(cases))
