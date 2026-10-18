"""Use actual synthetic approve/publish flow, never a hand-made published flag."""
from contextlib import closing
import sqlite3
from uuid import uuid4

import pytest

from app import baselines, db, post_publication_source as source_module
from app.candidate_review_contracts import CandidateRollback
from app.feedback_contract import PrivacyReview
from app.feedback_store import set_model_permission
from app.post_publication_contracts import PostPublicationError
from .test_candidate_review_publication import approved
from .test_rule_snapshots import rule_storage


def resolver(active):
    cls = getattr(source_module, 'PostPublicationSourceResolver', None)
    assert cls is not None, 'Publication history verifier must exist'
    return cls(active)


def source(active, cid, version):
    with closing(db._connect()) as conn, conn:
        return resolver(active).load(conn, cid, version)


def test_only_approved_candidate_is_not_post_publication_evidence(rule_storage):
    owner, run, cid, request = approved(rule_storage)
    with pytest.raises(PostPublicationError): source(rule_storage, cid, request.expectedRuleVersion)


def test_actual_publication_binds_new_version_operation_time_and_traffic(rule_storage):
    owner, run, cid, request = approved(rule_storage)
    published = owner.publish(cid, request)
    before = None
    with closing(db._connect()) as conn, conn:
        before = '\n'.join(conn.iterdump())
        created_at = conn.execute('SELECT created_at FROM rule_releases WHERE id=?', (published.publishedRuleVersion,)).fetchone()[0]
    receipt = source(rule_storage, cid, published.publishedRuleVersion)
    assert (receipt.candidateId, receipt.publicationOperationKey, receipt.publishedRuleVersion) == (cid, request.operationKey, published.publishedRuleVersion)
    assert receipt.publishedRuleVersion != request.expectedRuleVersion and receipt.publishedAt == created_at
    assert receipt.trafficClass == 'test' and len(receipt.publicationProofDigest) == 64
    with closing(db._connect()) as conn, conn: assert '\n'.join(conn.iterdump()) == before


def test_rollback_retains_historical_publication_receipt(rule_storage):
    owner, run, cid, request = approved(rule_storage)
    published = owner.publish(cid, request)
    receipt = source(rule_storage, cid, published.publishedRuleVersion)
    owner.rollback(CandidateRollback(operationKey=str(uuid4()), expectedRuleVersion=published.publishedRuleVersion,
        expectedPointerVersion=1, targetRuleVersion=request.expectedRuleVersion, reason='Synthetic rollback'))
    assert source(rule_storage, cid, published.publishedRuleVersion) == receipt


def test_privacy_permission_revocation_blocks_fresh_observation(rule_storage):
    owner, run, cid, request = approved(rule_storage)
    published = owner.publish(cid, request)
    set_model_permission(run.feedbackId, run.manifest.context.sourceFeedbackVersion,
        review=PrivacyReview(safeForModel=False, reviewNote='Synthetic revoke'))
    with pytest.raises(PostPublicationError): source(rule_storage, cid, published.publishedRuleVersion)


@pytest.mark.parametrize('event', ['candidate_published', 'rule_published'])
def test_missing_necessary_publication_audit_refuses_source(rule_storage, event):
    owner, run, cid, request = approved(rule_storage)
    published = owner.publish(cid, request)
    with closing(db._connect()) as conn, conn: conn.execute('DELETE FROM audit_events WHERE event_type=?', (event,))
    with pytest.raises(PostPublicationError): source(rule_storage, cid, published.publishedRuleVersion)


def test_corrupt_operation_receipt_cannot_be_replaced_by_status_flag(rule_storage):
    owner, run, cid, request = approved(rule_storage)
    published = owner.publish(cid, request)
    with closing(db._connect()) as conn, conn:
        conn.execute("UPDATE runtime_meta SET value_json='{}' WHERE key=?", ('candidate_operation:' + request.operationKey,))
    with pytest.raises(PostPublicationError): source(rule_storage, cid, published.publishedRuleVersion)


def test_unpublished_or_other_version_cannot_use_this_candidate_receipt(rule_storage):
    owner, run, cid, request = approved(rule_storage)
    owner.publish(cid, request)
    with pytest.raises(PostPublicationError): source(rule_storage, cid, request.expectedRuleVersion)
