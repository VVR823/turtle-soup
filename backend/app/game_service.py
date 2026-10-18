"""Request orchestration; owned model work happens between short transactions."""
import re

from . import ai_host, db, trace_logger
from .schemas import ChatRequest, EvaluationResult, HostResult, HostVersions
from .request_lifecycle import cancellation_signal


def ask(req: ChatRequest) -> db.TurnReplay:
    owner = db.reserve_turn(req.sessionId, str(req.requestId), req.question, soup_id=req.soupId)
    if isinstance(owner, db.TurnReplay):
        return owner
    session = db.get_session(owner.sessionId)
    soup = db.get_session_soup(session)
    versions = HostVersions(puzzleVersion=owner.puzzleVersion, ruleVersion=owner.ruleVersion,
                            engineVersion=owner.engineVersion)
    if re.match(r"^(我猜出答案了|我猜到了|我知道了|我放弃了|告诉我答案|看汤底|揭晓真相|跳过|不玩了)", req.question):
        host = HostResult(kind="reminder", source="flow", chargeable=False, versions=versions,
                          reply="请点击左侧「🏁 揭晓答案」按钮，AI 会根据本局问答自动评估完成度并公布汤底。")
    else:
        try:
            history = db.get_private_host_history(owner.sessionId)
            from .rule_contract import read_rule_snapshot
            conn = db._connect()
            try:
                conn.execute("BEGIN")
                snapshot = read_rule_snapshot(conn, owner.puzzleVersion, owner.ruleVersion)
            finally:
                conn.rollback()
                conn.close()
            options = {"rule_snapshot": snapshot} if snapshot.exactRules else {}
            host = ai_host.handle_host_response(soup, history, req.question, versions=versions, **options)
        except Exception:
            # No provider details or guessed factual answer; the failure itself
            # is persisted as this request's terminal result and never charged.
            host = HostResult(kind="system_error", source="flow", chargeable=False,
                              versions=versions, errorCode="model_unavailable", reply="主持人暂时不可用，请稍后重新提问。")
    cancellation = cancellation_signal()
    if cancellation is not None and cancellation.is_set():
        host = HostResult(kind="system_error", source="flow", chargeable=False, versions=versions,
                          errorCode="model_cancelled", reply="这次提问已中止，没有扣次数；请重新提问。")
    response = db.finish_turn(owner, host, cancelled=cancellation)
    if response.safeResponse.get("code") == "model_cancelled":
        host = HostResult(kind="system_error", source="flow", chargeable=False, versions=versions,
                          errorCode="model_cancelled", reply=response.safeResponse["reply"])
    trace_logger.record(owner.sessionId, soup.id, req.question, host)
    return response


def evaluate_snapshot(soup, turns, *, versions, excluded_legacy_count=0):
    # No model call or display-text parsing under the protected game snapshot.
    result = ai_host.evaluate_completion(soup, "", turns=turns, versions=versions,
                                         excluded_legacy_count=excluded_legacy_count)
    return EvaluationResult(
        completion=result["completion"], evaluation=result["evaluation"],
        keyPointsCovered=result["keyPointsCovered"], keyPointsMissing=result["keyPointsMissing"],
        bottom=soup.bottom, unlockSoupId=soup.unlocks if result.get("unlockThresholdReached") else None,
        verifiedCoverage=result["verifiedCoverage"], reconstructionScore=None,
        scoreVersion=result["scoreVersion"], plotProgress=result["plotProgress"], unknownTopics=result["unknownTopics"],
    ).model_dump(mode="json")
