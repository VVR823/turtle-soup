/** Private wire validation only. Digests bind server evidence; they never prove semantics. */
export class AgentReviewContractError extends Error {
  constructor() { super('任务数据暂时无法核验，请刷新；不会自动批准或发布'); this.name = 'AgentReviewContractError'; }
}
type Decoder<T> = (value: unknown) => T;
function invalid(): never { throw new AgentReviewContractError(); }
function object<S extends Record<string, Decoder<unknown>>>(value: unknown, shape: S): { [K in keyof S]: ReturnType<S[K]> } {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid();
  const data = value as Record<string, unknown>, keys = Object.keys(shape);
  if (Object.keys(data).length !== keys.length || Object.keys(data).some(key => !keys.includes(key))) return invalid();
  return Object.fromEntries(keys.map(key => [key, shape[key](data[key])])) as { [K in keyof S]: ReturnType<S[K]> };
}
function text(max: number, nonblank = true): Decoder<string> {
  return value => typeof value === 'string' && value.length > 0 && Array.from(value).length <= max
    && (!nonblank || !!value.trim()) ? value : invalid();
}
function nullable<T>(read: Decoder<T>): Decoder<T | null> { return value => value === null ? null : read(value); }
function integer(max = Number.MAX_SAFE_INTEGER): Decoder<number> {
  return value => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= max ? value : invalid();
}
const count = integer();
const seconds: Decoder<number> = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : invalid();
const bool: Decoder<boolean> = value => typeof value === 'boolean' ? value : invalid();
function choice<const T extends readonly (string | number | boolean)[]>(...values: T): Decoder<T[number]> {
  return value => values.includes(value as T[number]) ? value as T[number] : invalid();
}
function pattern(regex: RegExp, max: number): Decoder<string> { return value => { const result = text(max)(value); return regex.test(result) ? result : invalid(); }; }
const id = pattern(/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/, 36);
const digest = pattern(/^[0-9a-f]{64}$/, 64), p1 = pattern(/^p1:[0-9a-f]{64}$/, 67);
const r1 = pattern(/^r1:[0-9a-f]{64}$/, 67), f1 = pattern(/^f1:[0-9a-f]{64}$/, 67);
const schema = choice(1), answer = choice('是', '不是', '是也不是', '算是', '与此无关');
const state = choice('queued', 'running', 'awaiting_review', 'needs_human', 'failed', 'cancelled');
const candidateState = choice('pending', 'approved', 'rejected', 'published');
const action = choice('approved', 'rejected', 'published');
function array<T>(read: Decoder<T>, max: number, min = 0): Decoder<T[]> {
  return value => Array.isArray(value) && value.length >= min && value.length <= max ? value.map(read) : invalid();
}
function unique<T>(values: T[], key: (item: T) => unknown = item => item): T[] {
  if (new Set(values.map(key)).size !== values.length) return invalid(); return values;
}
const tool = choice('get_turn_trace', 'retrieve_truth', 'find_rule_conflicts', 'run_regression', 'save_candidate_rule');
const stopReason = choice('source_changed', 'permission_revoked', 'budget_exhausted', 'deadline', 'model_output_invalid',
  'tool_failed', 'model_unavailable', 'cancellation', 'shutting_down', 'missing_corpus', 'context_too_large');
const modelError = choice('model_timeout', 'model_busy', 'model_unavailable', 'model_output_invalid', 'model_policy_unknown',
  'model_auth', 'model_quota', 'model_transport_error', 'model_cancelled', 'model_cleanup_failed', 'context_too_large');
function readStatus(value: unknown) {
  const result = object(value, { id, state, rowVersion: count, modelAttemptsUsed: integer(10), toolAttemptsUsed: integer(8),
    deadlineAt: nullable(seconds), reason: nullable(stopReason), candidateId: nullable(id),
    steps: array(value => object(value, { seq: count, action: choice('tool', 'finish', 'model_decision', 'server_stop'),
      state: choice('planned', 'completed', 'failed'), tool: nullable(tool) }), 32) });
  unique(result.steps, step => step.seq);
  if (result.state === 'awaiting_review' && result.candidateId === null) return invalid();
  return result;
}
export function decodeAgentStatus(value: unknown, expectedId: string) {
  const result = readStatus(value); if (result.id !== id(expectedId)) return invalid(); return result;
}
function readRun(value: unknown) {
  const result = object(value, { id, feedbackId: id, state, rowVersion: count, createdAt: seconds, deadlineAt: nullable(seconds),
    modelAttemptsUsed: integer(10), toolAttemptsUsed: integer(8), candidateId: nullable(id), candidateStatus: nullable(candidateState) });
  if ((result.candidateId === null) !== (result.candidateStatus === null)
    || (result.state === 'awaiting_review' && result.candidateId === null)
    || (result.candidateStatus !== null && result.candidateStatus !== 'pending' && result.state !== 'awaiting_review')
    || (result.state === 'queued' && (result.deadlineAt !== null || result.modelAttemptsUsed || result.toolAttemptsUsed || result.candidateId !== null))
    || (['running', 'awaiting_review'].includes(result.state) && result.deadlineAt === null)
    || (result.deadlineAt !== null && result.deadlineAt < result.createdAt)) return invalid();
  return result;
}
export function decodeAgentRunPage(value: unknown) {
  const result = object(value, { schemaVersion: schema, runs: array(readRun, 100), nextCursor: nullable(pattern(/^[A-Za-z0-9_-]+$/, 512)) });
  unique(result.runs, run => run.id); return result;
}
function readDraft(value: unknown) {
  const result = object(value, { schemaVersion: schema, type: choice('exact_qa'), operation: choice('add', 'replace'),
    targetRuleDigest: nullable(digest), soupId: text(200), puzzleVersion: p1, baseRuleVersion: r1,
    question: text(500), normalizationVersion: choice('exact-v1'), answer, factIds: array(f1, 32, 1), evidenceSummary: text(1000) });
  unique(result.factIds);
  if ((result.operation === 'replace') !== (result.targetRuleDigest !== null)) return invalid(); return result;
}
function readReport(value: unknown) {
  const result = object(value, { schemaVersion: schema, reportId: id, runId: id, draftDigest: digest, contextDigest: digest,
    suiteManifestDigest: digest, puzzleVersion: p1, baseRuleVersion: r1,
    evidenceKind: choice('synthetic_fixture', 'deterministic_regression'), status: choice('complete', 'incomplete', 'failed'),
    inputCaseCount: integer(128), attemptedCaseCount: integer(128), passedCaseCount: integer(128), elapsedSeconds: seconds,
    truncated: bool, cleanupConfirmed: bool, caseResults: array(value => object(value, { caseId: id,
      suite: choice('dev_regression', 'fixed_safety'), passed: bool,
      code: choice('passed', 'counterexample', 'needs_corpus', 'deadline', 'truncated', 'probe_failed') }), 128) });
  unique(result.caseResults, row => row.caseId);
  if (result.attemptedCaseCount !== result.caseResults.length || result.passedCaseCount !== result.caseResults.filter(row => row.passed).length
    || result.attemptedCaseCount > result.inputCaseCount || result.caseResults.some(row => row.passed !== (row.code === 'passed'))
    || (result.status === 'complete' && (!result.inputCaseCount || result.passedCaseCount !== result.inputCaseCount
      || result.truncated || !result.cleanupConfirmed || result.elapsedSeconds > 5))
    || (result.status === 'failed' && result.caseResults.every(row => row.passed))) return invalid();
  return result;
}
function readDiagnostic(value: unknown) {
  const result = object(value, { kind: choice('answer', 'reminder', 'system_error', 'win'),
    source: choice('deterministic', 'llm', 'flow', 'legacy'), answer: nullable(answer), chargeable: bool, errorCode: nullable(modelError),
    engineVersion: text(100), normalizationVersion: text(100), resultDigest: digest });
  const valid = result.kind === 'answer' ? result.answer !== null && result.chargeable && result.errorCode === null && result.source !== 'flow'
    : result.kind === 'system_error' ? result.answer === null && !result.chargeable && result.errorCode !== null && ['llm', 'flow'].includes(result.source)
    : result.kind === 'reminder' ? result.answer === null && !result.chargeable && result.errorCode === null && ['deterministic', 'flow'].includes(result.source)
    : result.answer === null && result.errorCode === null && result.source === 'deterministic';
  if (!valid) return invalid(); return result;
}
function readSourceContext(value: unknown) {
  try { if (new TextEncoder().encode(JSON.stringify(value)).byteLength > 131072) return invalid(); } catch { return invalid(); }
  const result = object(value, { inputKind: choice('stored_private_source'), scope: choice('admin_review_only'),
    sessionId: id, turnId: id, soupId: text(200), puzzleVersion: p1, ruleVersion: r1,
    originalQuestion: text(500), originalHostAnswer: text(2000, false), contextDigest: digest,
    messages: array(value => object(value, { messageId: count, turnId: id, role: choice('user', 'host'), content: text(2000, false) }), 100) });
  unique(result.messages, message => message.messageId);
  if (result.messages.length % 2 || new Set(result.messages.map(message => message.turnId)).size !== result.messages.length / 2
    || result.messages.some((message, index) => message.messageId < 1 || message.turnId === result.turnId
      || (index > 0 && message.messageId <= result.messages[index - 1].messageId)
      || message.role !== (index % 2 ? 'host' : 'user')
      || (index % 2 && message.turnId !== result.messages[index - 1].turnId))) return invalid();
  return result;
}
function readMaterial(value: unknown) {
  const result = object(value, { inputKind: choice('user_claim'), draftKind: choice('model_summary'),
    sourceContext: readSourceContext,
    sanitizedInput: value => object(value, { question: text(500), hostAnswer: text(100), expectedClaim: text(100),
      reason: nullable((value: unknown) => typeof value === 'string' && Array.from(value).length <= 2000 ? value : invalid()) }),
    programDiagnostic: readDiagnostic, draft: readDraft,
    factScope: array(value => object(value, { id: f1, soupId: text(200), puzzleVersion: p1, sourcePath: text(200),
      category: choice('truth', 'checkpoint', 'confusion', 'symbol', 'metadata'), payload: text(32768, false) }), 256, 1),
    highlightedFactIds: array(f1, 256, 1), oldTarget: nullable(value => object(value, { targetRuleDigest: digest,
      type: choice('exact_qa', 'confusion'), sourcePath: text(200), question: text(500), answer })), report: readReport });
  const facts = new Set(unique(result.factScope, fact => fact.id).map(fact => fact.id)); unique(result.highlightedFactIds);
  if (result.sourceContext.soupId !== result.draft.soupId || result.sourceContext.puzzleVersion !== result.draft.puzzleVersion
    || result.factScope.some(fact => fact.soupId !== result.draft.soupId || fact.puzzleVersion !== result.draft.puzzleVersion)
    || [...result.highlightedFactIds, ...result.draft.factIds].some(fact => !facts.has(fact))
    || result.report.puzzleVersion !== result.draft.puzzleVersion || result.report.baseRuleVersion !== result.draft.baseRuleVersion
    || (result.draft.operation === 'replace') !== (result.oldTarget !== null)
    || (result.oldTarget !== null && result.oldTarget.targetRuleDigest !== result.draft.targetRuleDigest)) return invalid();
  return result;
}
function readReceipt(value: unknown) {
  return object(value, { draftDigest: digest, candidateDigest: digest, regressionReportId: id, reportDigest: digest,
    suiteManifestDigest: digest, puzzleVersion: p1, baseRuleVersion: r1, status: choice('complete'),
    answerSupported: choice(true), contextIndependent: choice(true), reviewNote: text(1000) });
}
function readReview(value: unknown) {
  const result = object(value, { schemaVersion: schema, candidateId: id, status: action, candidateDigest: digest,
    candidateDraftDigest: digest, publicationDraftDigest: digest, reportId: id, reportDigest: digest, suiteManifestDigest: digest,
    contextDigest: digest, sourceFeedbackVersion: count, targetRuleDigest: nullable(digest), proofDigest: nullable(digest),
    reviewReceipt: nullable(readReceipt), approvalOperationKey: nullable(id), reviewNote: text(1000), reviewedAt: seconds,
    lastOperationKey: id, publishedRuleVersion: nullable(r1) });
  const receipt = result.reviewReceipt;
  if ((receipt === null) !== (result.approvalOperationKey === null)
    || (result.status !== 'rejected' && (receipt === null || result.proofDigest === null))
    || (result.status === 'published') !== (result.publishedRuleVersion !== null)
    || (receipt !== null && (receipt.draftDigest !== result.publicationDraftDigest || receipt.candidateDigest !== result.candidateDigest
      || receipt.regressionReportId !== result.reportId || receipt.reportDigest !== result.reportDigest
      || receipt.suiteManifestDigest !== result.suiteManifestDigest))) return invalid();
  return result;
}
export function decodeCandidateDetail(value: unknown, expectedId: string) {
  // Full material is all-or-nothing; never trim qualifiers or failing cases to fit.
  try { if (new TextEncoder().encode(JSON.stringify(value)).byteLength > 524288) return invalid(); } catch { return invalid(); }
  const result = object(value, { schemaVersion: schema, candidateId: id, runId: id, candidateStatus: candidateState,
    reviewVersion: count, agentStatus: readStatus, activeRuleVersion: r1, activePointerVersion: count, proofDigest: nullable(digest),
    availability: choice('ready', 'historical', 'stale', 'unavailable'),
    blockers: array(choice('candidate_source_stale', 'candidate_base_changed', 'candidate_suite_changed', 'candidate_suite_unavailable',
      'candidate_corpus_missing', 'candidate_corpus_invalid', 'candidate_detail_too_large', 'candidate_terminal', 'candidate_context_unavailable'), 6),
    material: nullable(readMaterial), review: nullable(readReview), publishedRuleVersion: nullable(r1) });
  const { material, review } = result;
  if (result.candidateId !== id(expectedId) || result.agentStatus.id !== result.runId || result.agentStatus.candidateId !== result.candidateId
    || result.agentStatus.state !== 'awaiting_review' || (result.availability === 'ready') !== (result.proofDigest !== null)
    || ['ready', 'historical'].includes(result.availability) !== (material !== null)
    || (result.availability === 'ready') !== (result.blockers.length === 0)
    || (result.availability === 'ready' && !['pending', 'approved'].includes(result.candidateStatus))
    || (['stale', 'unavailable'].includes(result.availability) && review !== null)
    || (result.availability === 'ready' && material?.report.status !== 'complete')
    || (result.candidateStatus === 'pending' && (result.reviewVersion !== 0 || review !== null))
    || (material !== null && result.candidateStatus !== 'pending' && review === null)
    || (material !== null && material.report.runId !== result.runId)
    || (review !== null && (review.candidateId !== result.candidateId || review.status !== result.candidateStatus
      || review.publishedRuleVersion !== result.publishedRuleVersion || result.reviewVersion === 0
      || (material !== null && (review.reportId !== material.report.reportId || review.candidateDraftDigest !== material.report.draftDigest
        || review.contextDigest !== material.report.contextDigest || review.suiteManifestDigest !== material.report.suiteManifestDigest
        || review.targetRuleDigest !== material.draft.targetRuleDigest
        || (review.reviewReceipt !== null && (review.reviewReceipt.puzzleVersion !== material.draft.puzzleVersion
          || review.reviewReceipt.baseRuleVersion !== material.draft.baseRuleVersion))))))) return invalid();
  return result;
}
export type AgentRunPage = ReturnType<typeof decodeAgentRunPage>;
export type AgentStatus = ReturnType<typeof decodeAgentStatus>;
export type CandidateDetail = ReturnType<typeof decodeCandidateDetail>;
export type CandidateIntent = { candidateId: string; operationKey: string; action: 'approved' | 'rejected' | 'published'; previousVersion: number };
export function decodeCandidateOperation(value: unknown, expected: CandidateIntent) {
  const result = object(value, { schemaVersion: schema, candidateId: id, operationKey: id, action, reviewVersion: count,
    candidateStatus: action, publishedRuleVersion: nullable(r1) });
  if (result.candidateId !== id(expected.candidateId) || result.operationKey !== id(expected.operationKey) || result.action !== expected.action
    || result.candidateStatus !== result.action || result.reviewVersion !== count(expected.previousVersion) + 1
    || (result.action === 'published') !== (result.publishedRuleVersion !== null)) return invalid();
  return result;
}
export function decodeAgentStart(value: unknown) { return object(value, { runId: id }); }
export function decodeRulePublication(value: unknown, expected: { operationKey: string; targetRuleVersion: string; previousPointerVersion: number }) {
  const result = object(value, { operationKey: id, ruleVersion: r1, pointerVersion: count, markerVersion: nullable(count) });
  if (result.operationKey !== id(expected.operationKey) || result.ruleVersion !== r1(expected.targetRuleVersion)
    || result.pointerVersion !== count(expected.previousPointerVersion) + 1) return invalid();
  return result;
}
