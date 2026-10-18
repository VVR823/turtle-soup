"""Fresh owned UI storage and independent synthetic corpus; not application setup.

No candidate/report/approval is seeded. The browser must submit real linked
feedback, grant privacy, start the worker, and review the resulting candidate.
"""
from uuid import uuid4


def prepare_ui_agent(settings):
    from app import baselines, db
    from app.agents.contracts import CandidateDraft
    from app.host_evidence import build_evidence_catalog
    from app.migrations import migrate
    from app.rule_contract import exact_targets_from_source, read_rule_snapshot
    from app.runtime import Runtime, runtime_context
    from app.schemas import Soup
    from eval.contracts import EvalCase, EvalPuzzle, ExpectedLabel, ReviewRecord, SourceDigest, case_digest
    from eval.grouping import audit_groups
    from eval.manifest import freeze_regression

    if (not settings.TESTING or settings.ALLOW_REAL_MODEL or settings.LLM_PROVIDER != "fake"
        or not settings.TEST_INSTANCE_ID or (settings.DATA_DIR / "sessions.db").exists()):
        raise ValueError("Agent UI fixture requires fresh explicitly owned fake storage")
    # Include only public built-ins, never runtime/verified files from a real installation.
    soups = db.load_catalog(settings.DATA_DIR, include_runtime=False)
    soup = Soup(id="synthetic-ui", title="合成修复验收（非真实模型成绩）", surface="合成问题，仅用于离线管理流程验收。",
        bottom="小明是凶手。", hidden=True, confusionPoints=[{"q": "小明是凶手吗？", "a": "不是"}])
    soups.append(soup)
    setup = Runtime(settings, soups=soups)
    with runtime_context(setup):
        db.initialize()
        conn = db._connect()
        try:
            migrate(conn, setup.soups, target_version=4)  # Explicit owned fixture only, never normal startup.
            conn.execute("INSERT INTO runtime_meta(key,value_json) VALUES('owned_ui_fixture',?)",
                (baselines.canonical_json({"instanceId": settings.TEST_INSTANCE_ID}),))
            conn.commit()
            active = baselines.active_manifest(conn)
            puzzle = active["puzzleVersions"][soup.id]
            snapshot = read_rule_snapshot(conn, puzzle, active["ruleVersion"])
            rules, _ = baselines._rule_release(conn, active["ruleVersion"])
            target = exact_targets_from_source(soup, puzzle, active["ruleVersion"], rules, "小明是凶手吗？")
            facts = build_evidence_catalog(soup, puzzle)
        finally:
            conn.close()
    # Freeze independently specified labels before constructing the scripted proposal.
    cases, sources = [], []
    for number, (question, answer) in enumerate((("小明是凶手吗？", "是"), ("小红是凶手吗？", "与此无关"))):
        group = f"owned-ui-synthetic-{number}"
        case = EvalCase(caseId=str(uuid4()), soupId=soup.id, puzzleVersion=puzzle, question=question,
            caseType="single", split="regression", sourceGroup=group, familyGroup=group,
            conversationId=None, contextIndex=None, categories=("synthetic-fixture",), visibility="public_authorized",
            origin="public_synthetic", evidenceSourceDigest=baselines.digest(group), authorRole="synthetic",
            reviewState="pending", proposedLabel=None, rawLegacyExpected=None, review=None)
        review = ReviewRecord(operatorId="synthetic-ui-only", reviewedAt="2026-10-11T00:00:00Z", caseDigest=case_digest(case),
            expectedLabel=ExpectedLabel(kind="answer", answer=answer), factIds=(facts[0].id,), humanConfirmed=True,
            reviewNote="Declared synthetic fixture, NOT genuine human annotation or model quality")
        cases.append(case.model_copy(update={"reviewState": "reviewed", "review": review}))
        sources.append(SourceDigest(sourceId=group, sourceDigest=case.evidenceSourceDigest, questionSourceGroup=group,
            origin="public_synthetic", collectedAt="2026-10-11T00:00:00Z", visibility="public_authorized", caseIds=(case.caseId,)))
    cases, sources = tuple(cases), tuple(sources)
    catalog = (EvalPuzzle(soupId=soup.id, puzzleVersion=puzzle, soupJson=baselines.canonical_json(soup.model_dump(mode="json")), ruleSnapshot=snapshot),)
    proof = audit_groups((), repair_cases=cases, source_digests=sources, source_complete=True)
    corpus = freeze_regression(cases, catalog=catalog, audit=proof, source_digests=sources, frozen_at="2026-10-11T00:00:00Z")
    draft = CandidateDraft(operation="replace", targetRuleDigest=target[0].targetRuleDigest, soupId=soup.id,
        puzzleVersion=puzzle, baseRuleVersion=active["ruleVersion"], question="小明是凶手吗？", answer="是", factIds=(facts[0].id,),
        evidenceSummary="合成模型建议：请人工核对小明身份；回归通过不等于语义正确。")
    return soups, corpus, draft
