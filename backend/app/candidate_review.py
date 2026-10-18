"""Private server review, immutable proof preparation and human receipt storage.

Pure helpers grant no authority. Store mutations load the actual immutable rows
and recheck live privacy/source/code/suite/corpus in their owned transaction.
Typed self-consistency alone never grants permission or proves semantic truth.
"""
from contextlib import contextmanager
import base64
import math
import re
from uuid import uuid4

from . import audit_store, baselines
from .agents.contracts import AgentCheckpoint, AgentError, CandidateRecord, FinishAction, RegressionReport, checked_model, draft_digest
from .agents.store import AgentStore, FinishRecord, RunRecord
from .candidate_review_contracts import (CandidateApprove, CandidateReject, CandidatePublish, CandidateRollback, CandidateOldTarget, CandidateReviewDetail,
    CandidateReviewError, CandidateReviewMaterial, CandidateSourceContext, CandidateOperationResult, CandidateReviewIntent,
    CandidateOperationReceipt, ReviewState, AgentRunPage, AgentRunSummary, checked_candidate_request)
from .rule_contract import ChangeDraft, PublicationRequest, ReviewReceipt, read_rule_snapshot


def validate_candidate_report(candidate, report, run):
    """Revalidate three independently stored bodies, including original run scope."""
    try:
        candidate = checked_model(CandidateRecord, candidate)
        report = checked_model(RegressionReport, report)
        run = checked_model(RunRecord, run, max_bytes=1048576)
        context = run.manifest.context
        draft = candidate.draft
        if (run.state != "awaiting_review" or candidate.runId != run.id or report.runId != run.id
            or report.reportId != candidate.regressionReportId or report.status != "complete"
            or report.draftDigest != draft_digest(draft)
            or candidate.reportDigest != baselines.digest(report.model_dump(mode="json"))
            or report.contextDigest != run.manifest.contextDigest
            or report.suiteManifestDigest != run.manifest.suiteManifestDigest
            or (report.puzzleVersion, report.baseRuleVersion) != (draft.puzzleVersion, draft.baseRuleVersion)
            or (draft.soupId, draft.puzzleVersion, draft.baseRuleVersion) !=
                (context.soupId, context.observedPuzzleVersion, context.baseRuleVersion)
            or not set(draft.factIds) <= {fact.id for fact in context.factScope}
            or (run.manifest.trafficClass == "real" and report.evidenceKind != "deterministic_regression")):
            raise ValueError("Stored candidate/report/run binding mismatch")
        return candidate, report, run
    except Exception:
        raise CandidateReviewError("candidate_proof_invalid", 409) from None


def publication_draft(candidate, confirmations):
    """Map exact candidate content to the different publication digest domain.

    No ReviewReceipt, database state or approval is created here. The caller's
    fresh proof/operation checks remain mandatory even with valid confirmations.
    """
    confirmations = checked_candidate_request(CandidateApprove, confirmations)
    try:
        candidate = checked_model(CandidateRecord, candidate)
        draft = candidate.draft
        return ChangeDraft(op=draft.operation, canonicalQuestionKey=draft.canonicalQuestionKey,
            question=draft.question, answer=draft.answer, factIds=draft.factIds,
            targetRuleDigest=draft.targetRuleDigest, puzzleVersion=draft.puzzleVersion,
            baseRuleVersion=draft.baseRuleVersion, confirmedContext=confirmations.contextIndependent)
    except Exception:
        raise CandidateReviewError("candidate_proof_invalid", 409) from None


class CandidateReviewStore:
    """Existing003-only private snapshots; construction grants no model access.

    This read path preserves the original immutable run/finish. Human mutations
    use a separate review ledger; a detail proof never supplies confirmations.
    """
    def __init__(self, runtime):
        self.runtime = runtime
        self.agent_store = AgentStore(runtime, authorize_create=lambda context: False)

    @contextmanager
    def _transaction(self, *, write=False, fresh_authority=None):
        # The list is owned by this invocation, never by a request/model. Only
        # fresh approve/publish append a run; replay/rejection/rollback do not.
        def before_commit():
            if fresh_authority:
                try:
                    self._verify_commit_authority(conn, fresh_authority[0])
                except CandidateReviewError as error:
                    raise AgentError(error.code, error.status) from None
        try:
            with self.agent_store._transaction(write=write, before_commit=before_commit if fresh_authority is not None else None) as conn:
                try:
                    yield conn
                except CandidateReviewError as error:
                    raise AgentError(error.code, error.status) from None
        except AgentError as error:
            code = error.code if error.code.startswith("candidate_") else "candidate_unavailable"
            raise CandidateReviewError(code, error.status) from None

    def _verify_commit_authority(self, conn, run):
        """Final non-DB identity check under the runtime's commit/closing lock.

        SQLite already serializes private source/base writes. This separately
        checks the actual current trusted corpus and loaded registered code;
        refusal rolls back releases, pointer, receipts and necessary audits.
        It does not re-run/regenerate/re-sign the immutable regression report.
        """
        from .agents.regression import FixedRegression
        from .runtime import _verified_repair_corpus
        try:
            soup = baselines.session_soup(conn, run.manifest.context.observedPuzzleVersion)
            corpus = _verified_repair_corpus(self.runtime.repair_corpus,
                testing=self.runtime.settings.TESTING, soups=[soup])
            if corpus is None or FixedRegression(self.runtime, corpus=corpus).suite_manifest_digest != run.manifest.suiteManifestDigest:
                raise ValueError("Current suite authority differs from original report")
        except Exception:
            raise CandidateReviewError("candidate_proof_stale", 409) from None

    def detail(self, candidate_id):
        from pydantic import TypeAdapter
        from .audit_events import CanonicalId
        try:
            candidate_id = TypeAdapter(CanonicalId).validate_python(candidate_id, strict=True)
        except Exception:
            raise CandidateReviewError() from None
        with self._transaction() as conn:
            return self._detail(conn, candidate_id)

    def list_runs(self, *, limit=50, start=None, end=None, cursor=None, feedback_id=None):
        """One bounded minimal join, not a private-source or approval validator.

        Unix UTC seconds and inclusive bounds match existing admin navigation.
        Cursor fixes the original window/filter/page size across later reads.
        The cursor is not authorization; every HTTP call still authenticates.
        """
        from pydantic import TypeAdapter
        from .audit_events import CanonicalId
        def window(left, right):
            return (all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in (left, right))
                and 0 <= right - left <= 31 * 86400)
        def encode(fields):
            return base64.urlsafe_b64encode(baselines.canonical_json(fields).encode()).decode().rstrip("=")
        point = None
        try:
            if type(limit) is not int or not 1 <= limit <= 100:
                raise ValueError("Bounded limit required")
            if feedback_id is not None:
                feedback_id = TypeAdapter(CanonicalId).validate_python(feedback_id, strict=True)
            if any(v is not None and (type(v) not in (int, float) or not math.isfinite(v) or v < 0) for v in (start, end)):
                raise ValueError("Real timestamps required")
            if cursor is not None:
                if type(cursor) is not str or not 1 <= len(cursor) <= 512 or not re.fullmatch(r"[A-Za-z0-9_-]+", cursor):
                    raise ValueError("Bounded cursor required")
                fields = baselines.strict_json(base64.b64decode(cursor + "=" * (-len(cursor) % 4),
                    altchars=b"-_", validate=True).decode())
                if (type(fields) is not dict or set(fields) != {"schemaVersion", "scope", "limit", "feedbackId", "start", "end", "createdAt", "id"}
                    or type(fields["schemaVersion"]) is not int or fields["schemaVersion"] != 1
                    or fields["scope"] != "agent-runs-v1" or type(fields["limit"]) is not int or fields["limit"] != limit
                    or fields["feedbackId"] != feedback_id or not window(fields["start"], fields["end"])
                    or type(fields["createdAt"]) not in (int, float) or not math.isfinite(fields["createdAt"])
                    or not fields["start"] <= fields["createdAt"] <= fields["end"]
                    or (start is not None and start != fields["start"]) or (end is not None and end != fields["end"])
                    or encode(fields) != cursor):
                    raise ValueError("Cursor scope mismatch")
                point = fields["createdAt"], TypeAdapter(CanonicalId).validate_python(fields["id"], strict=True)
                start, end = fields["start"], fields["end"]
            end = self.agent_store._now() if end is None else end
            start = max(0, end - 7 * 86400) if start is None else start
            if not window(start, end):
                raise ValueError("Bounded time window required")
        except Exception:
            raise CandidateReviewError("candidate_query_invalid", 422) from None
        where, args = "r.created_at>=? AND r.created_at<=?", [start, end]
        if feedback_id is not None:
            where += " AND r.feedback_id=?"
            args.append(feedback_id)
        if point is not None:
            where += " AND (r.created_at<? OR (r.created_at=? AND r.id<?))"
            args.extend((point[0], point[0], point[1]))
        with self._transaction() as conn:
            rows = conn.execute("SELECT r.id,r.feedback_id,r.state,r.row_version,r.created_at,r.checkpoint_json,"
                "c.id AS candidate_id,c.status AS candidate_status FROM agent_runs r "
                "LEFT JOIN rule_candidates c ON c.run_id=r.id WHERE " + where
                + " ORDER BY r.created_at DESC,r.id DESC LIMIT ?", (*args, limit + 1)).fetchmany(limit + 1)
            try:
                values = []
                for row in rows[:limit]:
                    checkpoint = checked_model(AgentCheckpoint, row["checkpoint_json"], max_bytes=262144)
                    if baselines.strict_json(row["checkpoint_json"]) != checkpoint.model_dump(mode="json"):
                        raise ValueError("Incomplete stored checkpoint")
                    values.append(AgentRunSummary(id=row["id"], feedbackId=row["feedback_id"], state=row["state"],
                        rowVersion=row["row_version"], createdAt=row["created_at"], deadlineAt=checkpoint.deadlineAt,
                        modelAttemptsUsed=checkpoint.modelAttemptsUsed, toolAttemptsUsed=checkpoint.toolAttemptsUsed,
                        candidateId=row["candidate_id"], candidateStatus=row["candidate_status"]))
                next_cursor = None
                if len(rows) > limit:
                    last = values[-1]
                    next_cursor = encode(dict(schemaVersion=1, scope="agent-runs-v1", limit=limit, feedbackId=feedback_id,
                        start=float(start), end=float(end), createdAt=last.createdAt, id=last.id))
                    if len(next_cursor) > 512:
                        raise ValueError("Bounded cursor required")
                return AgentRunPage(runs=tuple(values), nextCursor=next_cursor)
            except Exception:
                raise CandidateReviewError("candidate_index_unavailable", 503) from None

    def _immutable(self, conn, candidate_id):
        row = conn.execute("SELECT * FROM rule_candidates WHERE id=?", (candidate_id,)).fetchone()
        if row is None:
            raise CandidateReviewError("candidate_not_found", 404)
        try:
            candidate = checked_model(CandidateRecord, row["candidate_json"])
            run = self.agent_store._raw_run(conn, row["run_id"])
            report = checked_model(RegressionReport, row["regression_json"])
            validate_candidate_report(candidate, report, run)
            if (candidate.id != row["id"] or candidate.runId != row["run_id"]
                or candidate.createdAt != row["created_at"] or candidate.candidateDigest != row["candidate_digest"]
                or candidate.draft.soupId != row["soup_id"] or candidate.draft.baseRuleVersion != row["base_rule_version"]):
                raise ValueError("Candidate row/body mismatch")
            source = conn.execute("SELECT * FROM agent_steps WHERE run_id=? AND operation_key=?",
                (run.id, candidate.regressionReportId)).fetchone()
            if source is None:
                raise ValueError("Regression source missing")
            step = self.agent_store._step(source)
            if (step.state != "completed" or step.action.action != "tool"
                or step.action.tool != "run_regression" or step.action.arguments.draft != candidate.draft
                or step.resultJson != row["regression_json"]):
                raise ValueError("Regression row/source mismatch")
            self.agent_store._report_binding(run, step, report)
            status = self.agent_store._status(conn, run)
            final = conn.execute("SELECT * FROM agent_steps WHERE run_id=? ORDER BY seq DESC LIMIT 1", (run.id,)).fetchone()
            finish = self.agent_store._step(final)
            outcome = checked_model(FinishRecord, finish.resultJson)
            if (status.candidateId != candidate.id or not isinstance(finish.action, FinishAction)
                or finish.action.candidateId != candidate.id or outcome.candidateId != candidate.id):
                raise ValueError("Candidate not bound to original finish")
        except Exception:
            raise CandidateReviewError("candidate_proof_invalid", 503) from None
        return row, candidate, report, run, status

    @staticmethod
    def _publication_shape(candidate):
        draft = candidate.draft
        return ChangeDraft(op=draft.operation, canonicalQuestionKey=draft.canonicalQuestionKey,
            question=draft.question, answer=draft.answer, factIds=draft.factIds, targetRuleDigest=draft.targetRuleDigest,
            puzzleVersion=draft.puzzleVersion, baseRuleVersion=draft.baseRuleVersion, confirmedContext=True)

    def _check_state_binding(self, state, candidate, run):
        context = run.manifest.context
        if (state.reviewedAt < candidate.createdAt or state.candidateId != candidate.id or state.candidateDigest != candidate.candidateDigest
            or state.candidateDraftDigest != draft_digest(candidate.draft)
            or state.publicationDraftDigest != baselines.digest(self._publication_shape(candidate).model_dump(mode="json"))
            or state.reportId != candidate.regressionReportId or state.reportDigest != candidate.reportDigest
            or state.suiteManifestDigest != run.manifest.suiteManifestDigest or state.contextDigest != run.manifest.contextDigest
            or state.sourceFeedbackVersion != context.sourceFeedbackVersion or state.targetRuleDigest != candidate.draft.targetRuleDigest):
            raise ValueError("Review differs from immutable source")
        if state.reviewReceipt is not None and (state.reviewReceipt.puzzleVersion != candidate.draft.puzzleVersion
            or state.reviewReceipt.baseRuleVersion != candidate.draft.baseRuleVersion):
            raise ValueError("Review receipt source mismatch")

    def _operation(self, conn, operation_key):
        row = conn.execute("SELECT value_json,row_version FROM runtime_meta WHERE key=?",
            ("candidate_operation:" + operation_key,)).fetchone()
        if row is None:
            return None
        try:
            receipt = checked_model(CandidateOperationReceipt, row["value_json"], max_bytes=65536)
            if (row["row_version"] != 0 or receipt.result.operationKey != operation_key
                or baselines.canonical_json(receipt.model_dump(mode="json")) != row["value_json"]):
                raise ValueError("Operation identity/canonical body mismatch")
            _, candidate, _, run, _ = self._immutable(conn, receipt.intent.candidateId)
            self._check_state_binding(receipt.state, candidate, run)
            if receipt.intent.action == "published":
                from .rule_publication import _prior_operation
                request = self._publication_request(candidate, receipt.intent.request)
                payload = baselines.digest(dict(action="publish", request=request.model_dump(mode="json"),
                    review=receipt.state.reviewReceipt.model_dump(mode="json")))
                published = _prior_operation(conn, operation_key, payload)
                if (published is None or published.ruleVersion != receipt.result.publishedRuleVersion
                    or published.pointerVersion != receipt.intent.request.expectedPointerVersion + 1):
                    raise ValueError("Publication operation not committed with actual rule operation")
                source = read_rule_snapshot(conn, candidate.draft.puzzleVersion, published.ruleVersion)
                rules = [rule for rule in source.exactRules if rule.canonicalQuestionKey == candidate.draft.canonicalQuestionKey]
                if (len(rules) != 1 or rules[0].candidateDigest != candidate.candidateDigest
                    or rules[0].reviewReceipt != receipt.state.reviewReceipt
                    or any(getattr(rules[0], name) != value for name, value in self._publication_shape(candidate).model_dump().items())):
                    raise ValueError("Publication history differs from actual approved rule")
            return receipt
        except Exception:
            raise CandidateReviewError("candidate_operation_corrupt", 503) from None

    def _review_state(self, conn, row, candidate, run):
        metadata = conn.execute("SELECT value_json,row_version FROM runtime_meta WHERE key=?",
            ("candidate_review:" + candidate.id,)).fetchone()
        try:
            if metadata is None:
                if row["status"] != "pending" or row["reviewed_at"] is not None or row["published_release_id"] is not None:
                    raise ValueError("Missing actual review")
                return None, 0, None
            state = checked_model(ReviewState, metadata["value_json"], max_bytes=32768)
            version = metadata["row_version"]
            if (type(version) is not int or not 1 <= version <= 9223372036854775807
                or state.status != row["status"] or state.reviewedAt != row["reviewed_at"]
                or state.publishedRuleVersion != row["published_release_id"]
                or baselines.canonical_json(state.model_dump(mode="json")) != metadata["value_json"]):
                raise ValueError("Review row/value mismatch")
            self._check_state_binding(state, candidate, run)
            last = self._operation(conn, state.lastOperationKey)
            if last is None or last.state != state or last.result.reviewVersion != version:
                raise ValueError("Missing actual latest review operation")
            if state.reviewReceipt is not None:
                approval = self._operation(conn, state.approvalOperationKey)
                if (approval is None or approval.intent.action != "approved" or approval.state.reviewReceipt != state.reviewReceipt
                    or approval.result.candidateId != candidate.id or approval.result.reviewVersion > version
                    or approval.state.reviewedAt > state.reviewedAt
                    or (state.status == "approved" and (approval.result.reviewVersion != version or approval.state != state))):
                    raise ValueError("Approved metadata alone is not authority")
            return state, version, metadata["value_json"]
        except Exception:
            raise CandidateReviewError("candidate_review_corrupt", 503) from None

    @staticmethod
    def _source_context(conn, context):
        """Admin-only public-message projection, never additional model input.

        The feedback's actual original user-message boundary fixes the history;
        later turns and other sessions cannot be relabelled as earlier context.
        A missing/corrupt/oversize source is not an empty reviewed conversation.
        No application initialization, model allocation, paths or new columns.
        """
        from .schemas import HostResult
        target = conn.execute("SELECT rowid AS source_seq,* FROM turns WHERE id=?", (context.turnId,)).fetchone()
        if target is None:
            raise ValueError("Original turn missing")
        session = conn.execute("SELECT * FROM sessions WHERE id=?", (target["session_id"],)).fetchone()
        if (session is None or session["soup_id"] != context.soupId or session["compat_state"] != "compatible"
            or (session["puzzle_version"], session["rule_version"]) != (context.observedPuzzleVersion, context.observedRuleVersion)):
            raise ValueError("Original context scope mismatch")

        def checked_pair(turn, messages):
            host = HostResult.model_validate_json(turn["result_json"])
            if (turn["state"] not in {"completed", "failed"} or len(messages) != 2
                or [m["role"] for m in messages] != ["user", "host"]
                or messages[0]["content"] != turn["question"] or messages[1]["content"] != host.reply
                or messages[0]["id"] >= messages[1]["id"]
                or any(m["turn_id"] != turn["id"] or m["session_id"] != session["id"]
                    or m["is_free_reminder"] != (turn["charged"] == 0) for m in messages)
                or turn["payload_hash"] != baselines.digest({"question": turn["question"]})
                or (turn["puzzle_version"], turn["rule_version"]) != (context.observedPuzzleVersion, context.observedRuleVersion)
                or (host.versions.puzzleVersion, host.versions.ruleVersion, host.versions.engineVersion) !=
                    (turn["puzzle_version"], turn["rule_version"], turn["engine_version"])):
                raise ValueError("Original message/result binding mismatch")
            return host

        pair = conn.execute("SELECT * FROM messages WHERE session_id=? AND turn_id=? ORDER BY id LIMIT 3",
            (session["id"], target["id"])).fetchmany(3)
        host = checked_pair(target, pair)
        messages = conn.execute("SELECT * FROM messages WHERE session_id=? AND id<? ORDER BY id LIMIT 101",
            (session["id"], pair[0]["id"])).fetchmany(101)
        prior = conn.execute("SELECT * FROM turns WHERE session_id=? AND rowid<? AND state IN ('completed','failed') "
            "AND result_json IS NOT NULL ORDER BY rowid LIMIT 51", (session["id"], target["source_seq"])).fetchmany(51)
        if len(messages) > 100 or len(prior) > 50 or len(messages) != 2 * len(prior):
            raise ValueError("Bounded complete preceding context required")
        groups = {}
        for message in messages:
            groups.setdefault(message["turn_id"], []).append(message)
        if set(groups) != {turn["id"] for turn in prior}:
            raise ValueError("Missing or foreign preceding context")
        for turn in prior:
            checked_pair(turn, groups[turn["id"]])
        body = dict(inputKind="stored_private_source", scope="admin_review_only", sessionId=session["id"],
            turnId=target["id"], soupId=context.soupId, puzzleVersion=context.observedPuzzleVersion,
            ruleVersion=context.observedRuleVersion, originalQuestion=target["question"], originalHostAnswer=host.reply,
            messages=tuple(dict(messageId=m["id"], turnId=m["turn_id"], role=m["role"], content=m["content"]) for m in messages))
        return CandidateSourceContext(**body, contextDigest=baselines.digest(body))

    def _detail(self, conn, candidate_id):
        from .task_context import _freeze
        from .agents.validation import validate_candidate
        from .agents.regression import FixedRegression
        from .runtime import _verified_repair_corpus
        row, candidate, report, run, status = self._immutable(conn, candidate_id)
        state, version, _ = self._review_state(conn, row, candidate, run)
        active = baselines.active_manifest(conn)
        pointer = conn.execute("SELECT row_version FROM runtime_meta WHERE key='active_baseline'").fetchone()
        base = dict(candidateId=candidate.id, runId=run.id, candidateStatus=row["status"], reviewVersion=version,
            agentStatus=status, activeRuleVersion=active["ruleVersion"], activePointerVersion=pointer[0],
            review=state, publishedRuleVersion=None if state is None else state.publishedRuleVersion)

        def result(availability, blockers=(), material=None, proof=None):
            projection = {**base, "review": None} if availability in {"stale", "unavailable"} else base
            value = CandidateReviewDetail(**projection, availability=availability, blockers=blockers,
                material=material, proofDigest=proof)
            if len(value.model_dump_json().encode("utf-8")) > 524288:
                return CandidateReviewDetail(**{**base, "review": None}, availability="unavailable", blockers=("candidate_detail_too_large",),
                    material=None, proofDigest=None)
            return value

        context = run.manifest.context
        try:
            current = _freeze(conn, context.feedbackId, context.sourceFeedbackVersion, context.allowedTools)
            # Current pointer is freshness, not permission to destroy a pinned
            # historical read. Every other source/privacy field must still match.
            if (current.model_copy(update={"baseRuleVersion": context.baseRuleVersion}) != context
                or run.manifest.trafficClass != ("test" if self.runtime.settings.TESTING else "real")):
                raise ValueError("Private source changed")
        except Exception:
            return result("stale", ("candidate_source_stale",))

        try:
            source_context = self._source_context(conn, context)
        except Exception:
            return result("unavailable", ("candidate_context_unavailable",))

        soup = baselines.session_soup(conn, context.observedPuzzleVersion)
        rules = read_rule_snapshot(conn, context.observedPuzzleVersion, context.baseRuleVersion)
        conflict = validate_candidate(candidate.draft, context=context, soup=soup, rule_snapshot=rules)
        if conflict.status not in {"reviewable_replace", "no_known_conflict"} or context.programDiagnostic is None:
            raise CandidateReviewError("candidate_proof_invalid", 503)
        old_target = None
        if candidate.draft.operation == "replace":
            if len(conflict.targets) != 1:
                raise CandidateReviewError("candidate_proof_invalid", 503)
            target = conflict.targets[0]
            if target.type == "confusion":
                old = soup.confusionPoints[int(target.sourcePath.removeprefix("confusionPoints[").removesuffix("]"))]
                question, answer = old.q, old.a
            else:
                matching = [rule for rule in rules.exactRules if baselines.digest(rule.model_dump(mode="json")) == target.targetRuleDigest]
                if len(matching) != 1:
                    raise CandidateReviewError("candidate_proof_invalid", 503)
                question, answer = matching[0].question, matching[0].answer
            old_target = CandidateOldTarget(**target.model_dump(mode="json"), question=question, answer=answer)
        material = CandidateReviewMaterial(sanitizedInput=context.sanitizedInput, programDiagnostic=context.programDiagnostic,
            draft=candidate.draft, factScope=context.factScope, highlightedFactIds=candidate.draft.factIds,
            oldTarget=old_target, report=report, sourceContext=source_context)
        if row["status"] in {"rejected", "published"}:
            return result("historical", ("candidate_terminal",), material)
        if self.runtime.repair_corpus is None:
            return result("unavailable", ("candidate_corpus_missing",))
        try:
            corpus = _verified_repair_corpus(self.runtime.repair_corpus, testing=self.runtime.settings.TESTING, soups=[soup])
        except Exception:
            return result("unavailable", ("candidate_corpus_invalid",))
        if active["ruleVersion"] != context.baseRuleVersion:
            return result("historical", ("candidate_base_changed",), material)
        try:
            regression = FixedRegression(self.runtime, corpus=corpus)
        except AgentError as error:
            if error.code == "agent_source_reload_required":
                return result("historical", ("candidate_suite_changed",), material)
            return result("unavailable", ("candidate_suite_unavailable",))
        except Exception:
            return result("unavailable", ("candidate_suite_unavailable",))
        if regression.suite_manifest_digest != run.manifest.suiteManifestDigest:
            return result("historical", ("candidate_suite_changed",), material)
        # Server-only publication *shape* for its separate digest domain, not a
        # human receipt or review confirmation. No approval metadata is written.
        draft = candidate.draft
        publication = self._publication_shape(candidate)
        proof = baselines.digest(dict(policy="candidate-review-v2", candidateDigest=candidate.candidateDigest,
            sourceContextDigest=source_context.contextDigest,
            candidateDraftDigest=draft_digest(draft), publicationDraftDigest=baselines.digest(publication.model_dump(mode="json")),
            reportId=report.reportId, reportDigest=candidate.reportDigest, suiteManifestDigest=report.suiteManifestDigest,
            contextDigest=run.manifest.contextDigest, sourceFeedbackVersion=context.sourceFeedbackVersion,
            targetRuleDigest=draft.targetRuleDigest, activeRuleVersion=active["ruleVersion"], activePointerVersion=pointer[0]))
        return result("ready", material=material, proof=proof)

    def approve(self, candidate_id, request):
        # draft -> stored regression report -> candidate -> explicit human
        # confirmations/reason. Approval records bound evidence, not publication
        # or a machine determination that the answer is semantically correct.
        return self._review(candidate_id, request, action="approved", model=CandidateApprove)

    def reject(self, candidate_id, request):
        return self._review(candidate_id, request, action="rejected", model=CandidateReject)

    def _publication_request(self, candidate, request):
        return PublicationRequest(operationKey=request.operationKey, expectedRuleVersion=request.expectedRuleVersion,
            expectedPointerVersion=request.expectedPointerVersion, changeDraft=self._publication_shape(candidate),
            regressionReportId=candidate.regressionReportId, candidateDigest=candidate.candidateDigest)

    @staticmethod
    def _require_unused_rule_key(conn, operation_key):
        if conn.execute("SELECT 1 FROM runtime_meta WHERE key=?", ("rule_operation:" + operation_key,)).fetchone() is not None:
            raise CandidateReviewError("candidate_operation_conflict", 409)

    def publish(self, candidate_id, request):
        # Recheck the approved candidate/report/proof and current authority in
        # one transaction; RulePublisher then CASes the active rule pointer.
        # A stale approval cannot authorize changed content or a changed corpus.
        from .audit_events import AuditEvent, CandidatePublicationDetails
        from .rule_publication import RulePublisher, RulePublicationError
        request = checked_candidate_request(CandidatePublish, request)
        try:
            intent = checked_model(CandidateReviewIntent,
                CandidateReviewIntent(candidateId=candidate_id, action="published", request=request))
        except Exception:
            raise CandidateReviewError() from None
        fresh_authority = []
        with self._transaction(write=True, fresh_authority=fresh_authority) as conn:
            prior = self._operation(conn, request.operationKey)
            if prior is not None:
                if prior.intent != intent:
                    raise CandidateReviewError("candidate_operation_conflict", 409)
                return prior.result
            self._require_unused_rule_key(conn, request.operationKey)
            row, candidate, _, run, _ = self._immutable(conn, candidate_id)
            old, version, old_json = self._review_state(conn, row, candidate, run)
            if (row["status"] != "approved" or version != request.expectedReviewVersion
                or version == 9223372036854775807):
                raise CandidateReviewError("candidate_review_conflict", 409)
            detail = self._detail(conn, candidate_id)
            if (detail.availability != "ready" or detail.proofDigest != request.expectedProofDigest
                or old.proofDigest != detail.proofDigest or detail.activeRuleVersion != request.expectedRuleVersion
                or detail.activePointerVersion != request.expectedPointerVersion):
                raise CandidateReviewError("candidate_proof_stale", 409)
            fresh_authority.append(run)
            now = self.agent_store._now()
            if now < old.reviewedAt:
                raise CandidateReviewError("candidate_unavailable", 503)
            publication = self._publication_request(candidate, request)
            def authorize(current_conn, submitted):
                # Exact server conversion and actual saved approval were checked
                # above under this same SQLite write lock, not caller authority.
                if current_conn is not conn or submitted != publication:
                    raise CandidateReviewError("candidate_proof_stale", 409)
                return old.reviewReceipt
            try:
                published = RulePublisher(authorizer=authorize).publish_in_transaction(conn, publication)
            except RulePublicationError as error:
                raise CandidateReviewError("candidate_" + error.code, error.status) from None
            state = checked_model(ReviewState, old.model_copy(update=dict(status="published", reviewedAt=now,
                lastOperationKey=request.operationKey, publishedRuleVersion=published.ruleVersion)))
            result = CandidateOperationResult(candidateId=candidate.id, operationKey=request.operationKey,
                action="published", candidateStatus="published", reviewVersion=version + 1, publishedRuleVersion=published.ruleVersion)
            operation = CandidateOperationReceipt(intent=intent, intentDigest=baselines.digest(intent.model_dump(mode="json")),
                state=state, result=result)
            changed = conn.execute("UPDATE runtime_meta SET value_json=?,row_version=row_version+1 WHERE key=? AND row_version=? AND value_json=?",
                (baselines.canonical_json(state.model_dump(mode="json")), "candidate_review:" + candidate.id, version, old_json))
            if changed.rowcount != 1:
                raise CandidateReviewError("candidate_review_conflict", 409)
            changed = conn.execute("UPDATE rule_candidates SET status='published',reviewed_at=?,published_release_id=? "
                "WHERE id=? AND status='approved' AND reviewed_at IS ? AND published_release_id IS NULL",
                (now, published.ruleVersion, candidate.id, row["reviewed_at"]))
            if changed.rowcount != 1:
                raise CandidateReviewError("candidate_review_conflict", 409)
            conn.execute("INSERT INTO runtime_meta(key,value_json,row_version) VALUES(?,?,0)",
                ("candidate_operation:" + request.operationKey, baselines.canonical_json(operation.model_dump(mode="json"))))
            audit_store.insert_business_event(conn, AuditEvent(eventId=str(uuid4()), eventType="candidate_published",
                requestId=request.operationKey, runId=run.id, createdAt=now, details=CandidatePublicationDetails(
                    candidateId=candidate.id, runId=run.id, operationKey=request.operationKey, approvalOperationKey=old.approvalOperationKey,
                    reviewVersion=version + 1, candidateDigest=candidate.candidateDigest, reportDigest=candidate.reportDigest,
                    proofDigest=state.proofDigest, fromRuleVersion=request.expectedRuleVersion, toRuleVersion=published.ruleVersion,
                    pointerVersion=published.pointerVersion, trafficClass="test" if self.runtime.settings.TESTING else "real")))
            return result

    def rollback(self, request):
        from .rule_publication import RulePublisher, RulePublicationError
        request = checked_candidate_request(CandidateRollback, request)
        with self._transaction(write=True) as conn:
            if self._operation(conn, request.operationKey) is not None:
                raise CandidateReviewError("candidate_operation_conflict", 409)
            try:
                # Rollback is an independently authenticated admin action, not
                # publication authority for any candidate or model capability.
                return RulePublisher(authorizer=lambda *_: None).rollback_in_transaction(conn, request)
            except RulePublicationError as error:
                raise CandidateReviewError("candidate_" + error.code, error.status) from None

    def _review(self, candidate_id, request, *, action, model):
        from .audit_events import AuditEvent, CandidateReviewDetails
        request = checked_candidate_request(model, request)
        try:
            intent = checked_model(CandidateReviewIntent,
                CandidateReviewIntent(candidateId=candidate_id, action=action, request=request))
        except Exception:
            raise CandidateReviewError() from None
        fresh_authority = []
        with self._transaction(write=True, fresh_authority=fresh_authority) as conn:
            old_operation = self._operation(conn, request.operationKey)
            if old_operation is not None:
                if old_operation.intent != intent:
                    raise CandidateReviewError("candidate_operation_conflict", 409)
                return old_operation.result  # Historical ack, never a fresh authorization.
            self._require_unused_rule_key(conn, request.operationKey)
            row, candidate, report, run, _ = self._immutable(conn, candidate_id)
            old, version, old_json = self._review_state(conn, row, candidate, run)
            if (version != request.expectedReviewVersion or version == 9223372036854775807
                or row["status"] not in ({"pending"} if action == "approved" else {"pending", "approved"})):
                raise CandidateReviewError("candidate_review_conflict", 409)
            detail = self._detail(conn, candidate_id)
            if action == "approved" and (detail.availability != "ready" or detail.proofDigest != request.expectedProofDigest):
                raise CandidateReviewError("candidate_proof_stale", 409)
            if action == "approved":
                fresh_authority.append(run)
            now = self.agent_store._now()
            if now < candidate.createdAt or (old is not None and now < old.reviewedAt):
                raise CandidateReviewError("candidate_unavailable", 503)
            publication = self._publication_shape(candidate)
            publication_digest = baselines.digest(publication.model_dump(mode="json"))
            human_receipt = (ReviewReceipt(draftDigest=publication_digest, candidateDigest=candidate.candidateDigest,
                regressionReportId=report.reportId, reportDigest=candidate.reportDigest,
                suiteManifestDigest=report.suiteManifestDigest, puzzleVersion=candidate.draft.puzzleVersion,
                baseRuleVersion=candidate.draft.baseRuleVersion, status="complete", answerSupported=True,
                contextIndependent=True, reviewNote=request.reviewNote) if action == "approved" else None if old is None else old.reviewReceipt)
            state = ReviewState(candidateId=candidate.id, status=action, candidateDigest=candidate.candidateDigest,
                candidateDraftDigest=draft_digest(candidate.draft), publicationDraftDigest=publication_digest,
                reportId=report.reportId, reportDigest=candidate.reportDigest, suiteManifestDigest=report.suiteManifestDigest,
                contextDigest=run.manifest.contextDigest, sourceFeedbackVersion=run.manifest.context.sourceFeedbackVersion,
                targetRuleDigest=candidate.draft.targetRuleDigest,
                proofDigest=detail.proofDigest if action == "approved" else None if old is None else old.proofDigest,
                reviewReceipt=human_receipt, approvalOperationKey=request.operationKey if action == "approved" else None if old is None else old.approvalOperationKey,
                reviewNote=request.reviewNote, reviewedAt=now, lastOperationKey=request.operationKey)
            result = CandidateOperationResult(candidateId=candidate.id, operationKey=request.operationKey,
                action=action, candidateStatus=action, reviewVersion=version + 1)
            operation = CandidateOperationReceipt(intent=intent, intentDigest=baselines.digest(intent.model_dump(mode="json")),
                state=state, result=result)
            state_json = baselines.canonical_json(state.model_dump(mode="json"))
            key = "candidate_review:" + candidate.id
            if old_json is None:
                changed = conn.execute("INSERT INTO runtime_meta(key,value_json,row_version) VALUES(?,?,1)", (key, state_json))
            else:
                changed = conn.execute("UPDATE runtime_meta SET value_json=?,row_version=row_version+1 WHERE key=? AND row_version=? AND value_json=?",
                    (state_json, key, version, old_json))
            if changed.rowcount != 1:
                raise CandidateReviewError("candidate_review_conflict", 409)
            changed = conn.execute("UPDATE rule_candidates SET status=?,reviewed_at=? WHERE id=? AND status=? AND reviewed_at IS ?",
                (action, now, candidate.id, row["status"], row["reviewed_at"]))
            if changed.rowcount != 1:
                raise CandidateReviewError("candidate_review_conflict", 409)
            conn.execute("INSERT INTO runtime_meta(key,value_json,row_version) VALUES(?,?,0)",
                ("candidate_operation:" + request.operationKey, baselines.canonical_json(operation.model_dump(mode="json"))))
            audit_store.insert_business_event(conn, AuditEvent(eventId=str(uuid4()), eventType="candidate_reviewed",
                requestId=request.operationKey, runId=run.id, createdAt=now, details=CandidateReviewDetails(
                    candidateId=candidate.id, runId=run.id, operationKey=request.operationKey, action=action,
                    reviewVersion=version + 1, candidateDigest=candidate.candidateDigest, reportDigest=candidate.reportDigest,
                    proofDigest=state.proofDigest, answerSupported=True if action == "approved" else None,
                    contextIndependent=True if action == "approved" else None, reviewNote=request.reviewNote,
                    trafficClass="test" if self.runtime.settings.TESTING else "real")))
            return result
