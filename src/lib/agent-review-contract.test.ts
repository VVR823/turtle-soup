import { expect, test } from 'vitest';
import { agentStatus, candidateDetail, candidateId, runId, reportId, operationKey, reviewState, nextRule } from '../../tests/frontend/agent-review-fixtures';

// Breaks caught: permissive/unbound private responses granting fresh controls,
// rounded versions, silently omitted facts/cases, or treating prior publication as current.
test('preserves full claims, model label, source qualifiers, real denominator and original finish', async () => {
  const { decodeCandidateDetail } = await import('./agent-review-contract');
  const data = decodeCandidateDetail(candidateDetail(), candidateId);
  expect(data.material?.factScope[0].payload).toBe('{"text":"可能知道，但仅限事后","confidence":"low"}');
  expect(data.material?.sanitizedInput.expectedClaim).toBe('是');
  expect(data.material?.draftKind).toBe('model_summary');
  expect(data.material?.report.caseResults).toEqual([{ caseId: reportId, suite: 'dev_regression', passed: true, code: 'passed' }]);
  expect(data.agentStatus.state).toBe('awaiting_review');
});
const malformed: Array<(d: ReturnType<typeof candidateDetail>) => void> = [
  d => { d.reviewVersion = Number.MAX_SAFE_INTEGER + 1; },
  d => { d.activePointerVersion = 0.5; },
  d => { d.agentStatus.modelAttemptsUsed = 11; },
  d => { d.runId = reportId; },
  d => { d.material.report.runId = reportId; },
  d => { d.material.report.passedCaseCount = 0; },
  d => { d.material.report.caseResults[0].passed = false; },
  d => { d.material.report.truncated = true; },
  d => { d.material.report.cleanupConfirmed = false; },
  d => { d.material.report.elapsedSeconds = Infinity; },
  d => { d.material.report.caseResults.push(d.material.report.caseResults[0]); },
  d => { d.material.draft.factIds = ['f1:' + 'e'.repeat(64)]; },
  d => { d.material.factScope[0].soupId = 'foreign'; },
  d => { d.material.factScope[0].payload = '界'.repeat(200000); },
  d => { Object.assign(d, { authorizer: 'invented' }); },
];
test.each(malformed)('refuses malformed/unbound candidate response %#', async change => {
  const { decodeCandidateDetail, AgentReviewContractError } = await import('./agent-review-contract');
  const data = candidateDetail(); change(data);
  expect(() => decodeCandidateDetail(data, candidateId)).toThrow(AgentReviewContractError);
});
test('a foreign selected ID cannot reveal a plausible candidate response', async () => {
  const { decodeCandidateDetail } = await import('./agent-review-contract');
  expect(() => decodeCandidateDetail(candidateDetail(), reportId)).toThrow();
});
test('published historical workflow keeps original agent outcome and no fresh authority', async () => {
  const { decodeCandidateDetail } = await import('./agent-review-contract');
  const data = { ...candidateDetail(), availability: 'historical', proofDigest: null, blockers: ['candidate_terminal'],
    candidateStatus: 'published', reviewVersion: 2, publishedRuleVersion: nextRule,
    review: { ...reviewState(), status: 'published', publishedRuleVersion: nextRule } };
  const item = decodeCandidateDetail(data, candidateId);
  expect(item.proofDigest).toBeNull(); expect(item.candidateStatus).toBe('published');
  expect(item.agentStatus.state).toBe('awaiting_review');
  expect(item.review?.publicationDraftDigest).not.toBe(item.material?.report.draftDigest);
});
test('minimal unavailable detail is not an empty ready candidate', async () => {
  const { decodeCandidateDetail } = await import('./agent-review-contract');
  const data = { ...candidateDetail(), availability: 'unavailable', material: null, proofDigest: null,
    blockers: ['candidate_corpus_missing'] };
  expect(decodeCandidateDetail(data, candidateId).availability).toBe('unavailable');
  expect(() => decodeCandidateDetail({ ...data, blockers: [] }, candidateId)).toThrow();
});

test.each(['stale', 'unavailable'])('%s detail cannot retain a prior review receipt', async availability => {
  const { decodeCandidateDetail, AgentReviewContractError } = await import('./agent-review-contract');
  const data = { ...candidateDetail(), availability, candidateStatus: 'approved', reviewVersion: 1,
    review: reviewState(), material: null, proofDigest: null, blockers: ['candidate_source_stale'] };
  expect(() => decodeCandidateDetail(data, candidateId)).toThrow(AgentReviewContractError);
  // Stale minimal projection, without the saved private review, stays readable.
  expect(decodeCandidateDetail({ ...data, review: null }, candidateId).availability).toBe(availability);
});

test.each(['failed', 'incomplete'])('ready cannot expose a coherent %s regression report as actionable', async status => {
  const { decodeCandidateDetail, AgentReviewContractError } = await import('./agent-review-contract');
  const data = candidateDetail();
  const report = { ...data.material.report, status, passedCaseCount: 0,
    caseResults: [{ caseId: reportId, suite: 'dev_regression', passed: false,
      code: status === 'failed' ? 'counterexample' : 'deadline' }] };
  expect(() => decodeCandidateDetail({ ...data, material: { ...data.material, report } }, candidateId))
    .toThrow(AgentReviewContractError);
});
test('receipt is bound to actual review metadata, without conflating the two draft digests', async () => {
  const { decodeCandidateDetail } = await import('./agent-review-contract');
  const data = { ...candidateDetail(), candidateStatus: 'approved', reviewVersion: 1, review: reviewState() };
  expect(decodeCandidateDetail(data, candidateId).review?.approvalOperationKey).toBe(operationKey);
  data.review.reviewReceipt.draftDigest = data.review.candidateDraftDigest;
  expect(() => decodeCandidateDetail(data, candidateId)).toThrow();
});
test('full workflow without saved review cannot enable ready approval/publication or fake pending versions', async () => {
  const { decodeCandidateDetail } = await import('./agent-review-contract');
  expect(() => decodeCandidateDetail({ ...candidateDetail(), candidateStatus: 'approved', reviewVersion: 1 }, candidateId)).toThrow();
  expect(() => decodeCandidateDetail({ ...candidateDetail(), reviewVersion: 1 }, candidateId)).toThrow();
  expect(() => decodeCandidateDetail({ ...candidateDetail(), candidateStatus: 'published', reviewVersion: 2,
    review: { ...reviewState(), status: 'published', publishedRuleVersion: nextRule }, publishedRuleVersion: nextRule }, candidateId)).toThrow();
});
test('run index preserves bounded summaries, but rejects duplicate or incoherent candidates', async () => {
  const { decodeAgentRunPage } = await import('./agent-review-contract');
  const row = { id: runId, feedbackId: reportId, state: 'awaiting_review', rowVersion: 9,
    createdAt: 0, deadlineAt: 180, modelAttemptsUsed: 3, toolAttemptsUsed: 2, candidateId, candidateStatus: 'pending' };
  const page = { schemaVersion: 1, runs: [row], nextCursor: null };
  expect(decodeAgentRunPage(page).runs[0].feedbackId).toBe(reportId);
  expect(() => decodeAgentRunPage({ ...page, runs: [row, row] })).toThrow();
  expect(() => decodeAgentRunPage({ ...page, runs: [{ ...row, candidateId: null }] })).toThrow();
  expect(() => decodeAgentRunPage({ ...page, runs: [{ ...row, rowVersion: true }] })).toThrow();
  expect(() => decodeAgentRunPage({ ...page, schemaVersion: true })).toThrow();
});
test('status response is bound to the selected task and cannot exceed conserved budgets', async () => {
  const { decodeAgentStatus } = await import('./agent-review-contract');
  expect(decodeAgentStatus(agentStatus(), runId).steps[1].action).toBe('finish');
  expect(() => decodeAgentStatus(agentStatus(), reportId)).toThrow();
  expect(() => decodeAgentStatus({ ...agentStatus(), toolAttemptsUsed: 9 }, runId)).toThrow();
});
test('minimal operation acknowledgement binds exact nonce, candidate, action and previous version', async () => {
  const { decodeCandidateOperation } = await import('./agent-review-contract');
  const intent = { candidateId, operationKey, action: 'published' as const, previousVersion: 1 };
  const result = { schemaVersion: 1, candidateId, operationKey, action: 'published', reviewVersion: 2,
    candidateStatus: 'published', publishedRuleVersion: nextRule };
  expect(decodeCandidateOperation(result, intent).publishedRuleVersion).toBe(nextRule);
  for (const changes of [{ operationKey: runId }, { reviewVersion: 3 }, { candidateId: runId },
    { candidateStatus: 'approved' }, { publishedRuleVersion: null }, { schemaVersion: true }]) {
    expect(() => decodeCandidateOperation({ ...result, ...changes }, intent)).toThrow();
  }
});
test('start and rollback acknowledgements remain minimal and bound to loaded target and prior pointer', async () => {
  const { decodeAgentStart, decodeRulePublication } = await import('./agent-review-contract');
  expect(decodeAgentStart({ runId }).runId).toBe(runId);
  expect(() => decodeAgentStart({ runId, tools: [] })).toThrow();
  const expected = { operationKey, targetRuleVersion: nextRule, previousPointerVersion: 2 };
  expect(decodeRulePublication({ operationKey, ruleVersion: nextRule, pointerVersion: 3, markerVersion: null }, expected).pointerVersion).toBe(3);
  expect(() => decodeRulePublication({ operationKey, ruleVersion: nextRule, pointerVersion: 4, markerVersion: null }, expected)).toThrow();
});
