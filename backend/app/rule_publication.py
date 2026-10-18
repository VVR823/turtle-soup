"""Internal CPU-only reviewed publication; app never constructs a default authorizer."""
from contextlib import contextmanager
import time
from uuid import uuid4

from . import audit_store, baselines, db
from .audit_events import AuditEvent, RuleBusinessDetails, RuleSuspensionDetails, RuleRollbackDetails
from .feedback_contract import FeedbackError
from .host_evidence import build_evidence_catalog
from .host_rules import decide_deterministic, question_has_static_scope
from .migrations import CHECKSUM_002
from .question_normalization import normalize_exact_question
from .rule_contract import (ExactTarget, PublicationRequest, PublishedExactRule, ReviewReceipt,
    RulePublicationResult, RollbackRequest, SuspensionRequest, exact_targets_from_source, read_rule_snapshot, rule_suspension_state)
from .runtime import get_runtime
from .schemas import HostVersions


class RulePublicationError(FeedbackError):
    def __init__(self, code, status=409):
        super().__init__(code, status)


@contextmanager
def _transaction():
    db.initialize(); conn = db._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        phase = conn.execute("SELECT checksum FROM schema_migrations WHERE version=2").fetchone()
        if phase is None or phase[0] != CHECKSUM_002:
            raise RulePublicationError("rule_publication_unavailable", 503)
        yield conn
        conn.commit()
    except RulePublicationError:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise RulePublicationError("rule_publication_unavailable", 503) from None
    finally:
        conn.close()


def enumerate_exact_targets(conn, puzzle_version, rule_version, question):
    """Only actual full literal sources, never a model-chosen path or regex match."""
    soup = baselines.session_baseline(conn, puzzle_version, rule_version)
    rules, _ = baselines._rule_release(conn, rule_version)
    return exact_targets_from_source(soup, puzzle_version, rule_version, rules, question)


def _prior_operation(conn, operation_key, payload_digest):
    row = conn.execute("SELECT value_json,row_version FROM runtime_meta WHERE key=?",
        ("rule_operation:" + operation_key,)).fetchone()
    if row is None:
        return None
    try:
        body = baselines.strict_json(row[0])
        if (type(body) is not dict or set(body) != {"schemaVersion", "payloadDigest", "result"}
            or type(body["schemaVersion"]) is not int or body["schemaVersion"] != 1
            or row[1] != 0):
            raise ValueError("Invalid operation record")
        if body["payloadDigest"] != payload_digest:
            raise RulePublicationError("rule_operation_conflict")
        result = RulePublicationResult.model_validate_json(baselines.canonical_json(body["result"]))
        if result.operationKey != operation_key:
            raise ValueError("Wrong operation identity")
        baselines._rule_release(conn, result.ruleVersion)
        return result
    except RulePublicationError:
        raise
    except Exception:
        raise RulePublicationError("rule_publication_unavailable", 503) from None


class RulePublisher:
    def __init__(self, *, authorizer):
        if not callable(authorizer):
            raise TypeError("A trusted server authorizer is required")
        self._authorizer = authorizer

    def rollback(self, *, target_rule_version, expected_rule_version, expected_pointer_version,
        operation_key, reason, block_rule_version=None):
        try:
            checked = RollbackRequest(operationKey=operation_key, targetRuleVersion=target_rule_version,
                expectedRuleVersion=expected_rule_version, expectedPointerVersion=expected_pointer_version,
                reason=reason, blockRuleVersion=block_rule_version)
        except Exception:
            raise RulePublicationError("rule_request_invalid", 422) from None
        with _transaction() as conn:
            return self.rollback_in_transaction(conn, checked)

    def rollback_in_transaction(self, conn, request):
        """Use caller-owned transaction; never initialize, commit or open storage."""
        if not conn.in_transaction:
            raise RulePublicationError("rule_publication_unavailable", 503)
        try:
            checked = RollbackRequest.model_validate_json(request.model_dump_json(warnings="error"))
        except Exception:
            raise RulePublicationError("rule_request_invalid", 422) from None
        payload_digest = baselines.digest({"action": "rollback", "request": checked.model_dump(mode="json")})
        prior = _prior_operation(conn, checked.operationKey, payload_digest)
        if prior is not None:
            return prior
        pointer = conn.execute("SELECT value_json,row_version FROM runtime_meta WHERE key='active_baseline'").fetchone()
        active = baselines.active_manifest(conn)
        if (active["ruleVersion"] != checked.expectedRuleVersion or pointer[1] != checked.expectedPointerVersion
            or checked.expectedPointerVersion == 9223372036854775807):
            raise RulePublicationError("rule_pointer_conflict")
        _, target_manifest = baselines._rule_release(conn, checked.targetRuleVersion)
        for p1 in target_manifest["puzzleVersions"].values():
            read_rule_snapshot(conn, p1, checked.targetRuleVersion)
        if rule_suspension_state(conn, checked.targetRuleVersion):
            raise RulePublicationError("rule_version_suspended")
        marker_version = None
        if checked.blockRuleVersion is not None:
            rule_suspension_state(conn, checked.blockRuleVersion)
            marker_key = "rule_suspension:" + checked.blockRuleVersion[3:]
            marker = conn.execute("SELECT row_version FROM runtime_meta WHERE key=?", (marker_key,)).fetchone()
            if marker is not None and marker[0] == 9223372036854775807:
                raise RulePublicationError("rule_suspension_conflict")
            marker_version = 0 if marker is None else marker[0] + 1
            value = baselines.canonical_json(dict(schemaVersion=1, ruleVersion=checked.blockRuleVersion,
                suspended=True, reason=checked.reason))
            if marker is None:
                conn.execute("INSERT INTO runtime_meta(key,value_json) VALUES(?,?)", (marker_key, value))
            else:
                changed = conn.execute("UPDATE runtime_meta SET value_json=?,row_version=row_version+1 WHERE key=? AND row_version=?",
                    (value, marker_key, marker[0]))
                if changed.rowcount != 1:
                    raise RulePublicationError("rule_suspension_conflict")
        changed = conn.execute("UPDATE runtime_meta SET value_json=?,row_version=row_version+1 "
            "WHERE key='active_baseline' AND row_version=? AND value_json=?",
            (baselines.canonical_json({"schemaVersion": 1, "ruleVersion": checked.targetRuleVersion}),
             checked.expectedPointerVersion, pointer[0]))
        if changed.rowcount != 1:
            raise RulePublicationError("rule_pointer_conflict")
        result = RulePublicationResult(operationKey=checked.operationKey, ruleVersion=checked.targetRuleVersion,
            pointerVersion=checked.expectedPointerVersion + 1, markerVersion=marker_version)
        conn.execute("INSERT INTO runtime_meta(key,value_json) VALUES(?,?)", ("rule_operation:" + checked.operationKey,
            baselines.canonical_json(dict(schemaVersion=1, payloadDigest=payload_digest, result=result.model_dump(mode="json")))))
        details = RuleRollbackDetails(operationKey=checked.operationKey, fromRuleVersion=checked.expectedRuleVersion,
            toRuleVersion=checked.targetRuleVersion, pointerVersion=result.pointerVersion,
            blockedRuleVersion=checked.blockRuleVersion, markerVersion=marker_version, reason=checked.reason,
            trafficClass="test" if get_runtime().settings.TESTING else "real")
        audit_store.insert_business_event(conn, AuditEvent(eventId=str(uuid4()), eventType="rule_rolled_back",
            createdAt=time.time(), details=details))
        return result

    def set_rule_suspension(self, rule_version, *, expected_marker_version, suspended, reason, operation_key):
        try:
            checked = SuspensionRequest(operationKey=operation_key, ruleVersion=rule_version,
                expectedMarkerVersion=expected_marker_version, suspended=suspended, reason=reason)
        except Exception:
            raise RulePublicationError("rule_request_invalid", 422) from None
        payload_digest = baselines.digest({"action": "suspension", "request": checked.model_dump(mode="json")})
        with _transaction() as conn:
            baselines._rule_release(conn, checked.ruleVersion)
            if _prior_operation(conn, checked.operationKey, payload_digest) is not None:
                return
            marker_key = "rule_suspension:" + checked.ruleVersion[3:]
            old = conn.execute("SELECT row_version FROM runtime_meta WHERE key=?", (marker_key,)).fetchone()
            rule_suspension_state(conn, checked.ruleVersion)  # fail closed on corrupt existing state
            current_version = None if old is None else old[0]
            if current_version != checked.expectedMarkerVersion or current_version == 9223372036854775807:
                raise RulePublicationError("rule_suspension_conflict")
            value = baselines.canonical_json(dict(schemaVersion=1, ruleVersion=checked.ruleVersion,
                suspended=checked.suspended, reason=checked.reason))
            marker_version = 0 if old is None else current_version + 1
            if old is None:
                conn.execute("INSERT INTO runtime_meta(key,value_json) VALUES(?,?)", (marker_key, value))
            else:
                changed = conn.execute("UPDATE runtime_meta SET value_json=?,row_version=row_version+1 WHERE key=? AND row_version=?",
                    (value, marker_key, current_version))
                if changed.rowcount != 1:
                    raise RulePublicationError("rule_suspension_conflict")
            pointer_version = conn.execute("SELECT row_version FROM runtime_meta WHERE key='active_baseline'").fetchone()[0]
            result = RulePublicationResult(operationKey=checked.operationKey, ruleVersion=checked.ruleVersion,
                pointerVersion=pointer_version, markerVersion=marker_version)
            conn.execute("INSERT INTO runtime_meta(key,value_json) VALUES(?,?)", ("rule_operation:" + checked.operationKey,
                baselines.canonical_json(dict(schemaVersion=1, payloadDigest=payload_digest, result=result.model_dump(mode="json")))))
            details = RuleSuspensionDetails(operationKey=checked.operationKey, ruleVersion=checked.ruleVersion,
                markerVersion=marker_version, action="suspended" if checked.suspended else "resumed", reason=checked.reason,
                trafficClass="test" if get_runtime().settings.TESTING else "real")
            audit_store.insert_business_event(conn, AuditEvent(eventId=str(uuid4()), eventType="rule_suspension",
                createdAt=time.time(), details=details))

    def publish(self, request):
        try:
            checked = PublicationRequest.model_validate_json(request.model_dump_json())
        except Exception:
            raise RulePublicationError("rule_request_invalid", 422) from None
        with _transaction() as conn:
            return self.publish_in_transaction(conn, checked)

    def publish_in_transaction(self, conn, request):
        """Use caller-owned transaction and the explicit server authorizer."""
        # Bind draft/report/candidate to the recorded human receipt, validate
        # the exact replacement target, then insert the immutable release and
        # CAS the active pointer with operation receipt/audit atomically.
        if not conn.in_transaction:
            raise RulePublicationError("rule_publication_unavailable", 503)
        try:
            checked = PublicationRequest.model_validate_json(request.model_dump_json(warnings="error"))
        except Exception:
            raise RulePublicationError("rule_request_invalid", 422) from None
        draft = checked.changeDraft
        draft_digest = baselines.digest(draft.model_dump(mode="json"))
        try:
            receipt = self._authorizer(conn, checked)
            receipt = ReviewReceipt.model_validate_json(receipt.model_dump_json())
        except Exception:
            raise RulePublicationError("rule_review_required") from None
        if (receipt.draftDigest != draft_digest or receipt.candidateDigest != checked.candidateDigest
            or receipt.regressionReportId != checked.regressionReportId
            or receipt.puzzleVersion != draft.puzzleVersion or receipt.baseRuleVersion != draft.baseRuleVersion
            or draft.baseRuleVersion != checked.expectedRuleVersion
            or not receipt.answerSupported or not receipt.contextIndependent):
            raise RulePublicationError("rule_review_required")
        payload_digest = baselines.digest({"action": "publish", "request": checked.model_dump(mode="json"),
            "review": receipt.model_dump(mode="json")})
        old_result = _prior_operation(conn, checked.operationKey, payload_digest)
        if old_result is not None:
            return old_result
        pointer = conn.execute("SELECT value_json,row_version FROM runtime_meta WHERE key='active_baseline'").fetchone()
        active = baselines.active_manifest(conn)
        if (active["ruleVersion"] != checked.expectedRuleVersion or pointer[1] != checked.expectedPointerVersion
            or checked.expectedPointerVersion == 9223372036854775807):
            raise RulePublicationError("rule_pointer_conflict")
        if rule_suspension_state(conn, checked.expectedRuleVersion):
            raise RulePublicationError("rule_version_suspended")
        soup = baselines.session_baseline(conn, draft.puzzleVersion, checked.expectedRuleVersion)
        if (active["puzzleVersions"].get(soup.id) != draft.puzzleVersion
            or not question_has_static_scope(soup, draft.question)):
            raise RulePublicationError("rule_context_requires_human")
        facts = {record.id for record in build_evidence_catalog(soup, draft.puzzleVersion)}
        if not set(draft.factIds) <= facts:
            raise RulePublicationError("rule_fact_requires_human")
        targets = enumerate_exact_targets(conn, draft.puzzleVersion, checked.expectedRuleVersion, draft.question)
        if draft.op == "replace":
            if len(targets) != 1 or targets[0].targetRuleDigest != draft.targetRuleDigest:
                raise RulePublicationError("rule_target_conflict")
        elif targets or decide_deterministic(soup, draft.question, [], versions=HostVersions(
            puzzleVersion=draft.puzzleVersion, ruleVersion=checked.expectedRuleVersion)) is not None:
            raise RulePublicationError("rule_target_conflict")
        old_rules, _ = baselines._rule_release(conn, checked.expectedRuleVersion)
        new_rule = PublishedExactRule(**draft.model_dump(), candidateDigest=checked.candidateDigest,
            reportDigest=receipt.reportDigest, reviewReceipt=receipt)
        exact_by_soup = {identity: list(old_rules.get("exactQaBySoup", {}).get(identity, []))
            for identity in active["puzzleVersions"]}
        exact_by_soup[soup.id] = [item for item in exact_by_soup[soup.id]
            if item["canonicalQuestionKey"] != draft.canonicalQuestionKey] + [new_rule.model_dump(mode="json")]
        exact_by_soup[soup.id].sort(key=lambda item: item["canonicalQuestionKey"])
        rules = dict(schemaVersion=2, rulesBySoup=old_rules["rulesBySoup"], exactQaBySoup=exact_by_soup)
        manifest = dict(schemaVersion=2, puzzleVersions=active["puzzleVersions"],
            parentRuleVersion=checked.expectedRuleVersion, origin="reviewed-exact-rule")
        rule_version = "r1:" + baselines.digest({"rules": rules, "manifest": manifest})
        now = time.time()
        conn.execute("INSERT INTO rule_releases(id,parent_id,rules_json,manifest_json,created_at) VALUES(?,?,?,?,?)",
            (rule_version, checked.expectedRuleVersion, baselines.canonical_json(rules), baselines.canonical_json(manifest), now))
        read_rule_snapshot(conn, draft.puzzleVersion, rule_version)
        changed = conn.execute("UPDATE runtime_meta SET value_json=?,row_version=row_version+1 "
            "WHERE key='active_baseline' AND row_version=? AND value_json=?",
            (baselines.canonical_json({"schemaVersion": 1, "ruleVersion": rule_version}),
             checked.expectedPointerVersion, pointer[0]))
        if changed.rowcount != 1:
            raise RulePublicationError("rule_pointer_conflict")
        result = RulePublicationResult(operationKey=checked.operationKey, ruleVersion=rule_version,
            pointerVersion=checked.expectedPointerVersion + 1)
        conn.execute("INSERT INTO runtime_meta(key,value_json) VALUES(?,?)", ("rule_operation:" + checked.operationKey,
            baselines.canonical_json(dict(schemaVersion=1, payloadDigest=payload_digest, result=result.model_dump(mode="json")))))
        details = RuleBusinessDetails(operationKey=checked.operationKey, action="published",
            fromRuleVersion=checked.expectedRuleVersion, toRuleVersion=rule_version, pointerVersion=result.pointerVersion,
            soupId=soup.id, **receipt.model_dump(exclude={"puzzleVersion", "baseRuleVersion", "status"}),
            trafficClass="test" if get_runtime().settings.TESTING else "real")
        audit_store.insert_business_event(conn, AuditEvent(eventId=str(uuid4()), eventType="rule_published",
            createdAt=now, details=details))
        return result
