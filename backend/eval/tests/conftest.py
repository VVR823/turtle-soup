"""Pure evaluation fixtures; repository root guards remain installed."""
import pytest


@pytest.fixture
def catalog():
    from app.baselines import RULE_FIELDS, canonical_json, digest
    from app.rule_contract import RuleSnapshot
    from app.schemas import Soup
    from eval.contracts import EvalPuzzle
    soup = Soup(id="eval-synthetic", title="Synthetic", surface="A light went out.",
                bottom="A keeper switched off the lighthouse light.", genre="本格", castCount=1)
    payload = soup.model_dump(mode="json")
    p1 = "p1:" + digest({"schemaVersion": 1, "soup": payload})
    rules = {"schemaVersion": 1, "rulesBySoup": {soup.id: {name: payload[name] for name in RULE_FIELDS}}}
    manifest = {"schemaVersion": 1, "puzzleVersions": {soup.id: p1}, "origin": "legacy-baseline"}
    r1 = "r1:" + digest({"rules": rules, "manifest": manifest})
    snapshot = RuleSnapshot(ruleVersion=r1, puzzleVersion=p1, soupId=soup.id, exactRules=(),
                            releaseRulesJson=canonical_json(rules), releaseManifestJson=canonical_json(manifest))
    return (EvalPuzzle(soupId=soup.id, puzzleVersion=p1, soupJson=canonical_json(payload), ruleSnapshot=snapshot),)


@pytest.fixture
def pending(catalog):
    from eval.contracts import EvalCase, ExpectedLabel
    return EvalCase(caseId="d0000000-0000-4000-8000-000000000001", soupId="eval-synthetic",
        puzzleVersion=catalog[0].puzzleVersion, question="Was the light switched off?", caseType="single",
        split="holdout_candidate", sourceGroup="new-batch-1", familyGroup="light-switch-1",
        conversationId=None, contextIndex=None, categories=("literal",), visibility="private",
        origin="new_authoring", evidenceSourceDigest="a" * 64, authorRole="ai_draft", reviewState="pending",
        proposedLabel=ExpectedLabel(kind="answer", answer="是"), rawLegacyExpected=None, review=None)


@pytest.fixture
def reviewed(pending, catalog):
    from app.host_evidence import build_evidence_catalog
    from app.schemas import Soup
    from eval.contracts import ReviewRecord, case_digest
    facts = build_evidence_catalog(Soup.model_validate_json(catalog[0].soupJson), catalog[0].puzzleVersion)
    # Synthetic test attestation, never an actual human label or quality claim.
    receipt = ReviewRecord(operatorId="synthetic-test-only", reviewedAt="2026-10-09T00:00:00Z",
        caseDigest=case_digest(pending), expectedLabel=pending.proposedLabel, factIds=(facts[0].id,),
        reviewNote="Synthetic fixture cites the keeper switching off the light.", humanConfirmed=True)
    return pending.model_copy(update={"reviewState": "reviewed", "review": receipt})
