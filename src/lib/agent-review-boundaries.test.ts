import { expect, test } from 'vitest';
import { agentStatus, candidateDetail, candidateId, runId, reportId } from '../../tests/frontend/agent-review-fixtures';
import { AgentReviewContractError, decodeAgentRunPage, decodeAgentStatus, decodeCandidateDetail } from './agent-review-contract';

test.each([
  { kind: 'system_error', source: 'llm', answer: null, chargeable: false, errorCode: 'model_timeout' },
  { kind: 'system_error', source: 'flow', answer: null, chargeable: false, errorCode: 'model_busy' },
  { kind: 'reminder', source: 'deterministic', answer: null, chargeable: false, errorCode: null },
  { kind: 'reminder', source: 'flow', answer: null, chargeable: false, errorCode: null },
  { kind: 'win', source: 'deterministic', answer: null, chargeable: true, errorCode: null },
])('private material preserves a coherent $kind/$source diagnostic without inventing an answer', diagnostic => {
  const detail = candidateDetail();
  Object.assign(detail.material.programDiagnostic, diagnostic);
  expect(decodeCandidateDetail(detail, candidateId).material?.programDiagnostic).toMatchObject(diagnostic);
});

test.each([
  { kind: 'answer', source: 'flow' },
  { kind: 'answer', answer: null },
  { kind: 'answer', chargeable: false },
  { kind: 'answer', errorCode: 'model_timeout' },
  { kind: 'system_error', answer: null, chargeable: false, errorCode: null },
  { kind: 'system_error', answer: '是', chargeable: false, errorCode: 'model_timeout' },
  { kind: 'system_error', answer: null, chargeable: true, errorCode: 'model_timeout' },
  { kind: 'system_error', source: 'deterministic', answer: null, chargeable: false, errorCode: 'model_timeout' },
  { kind: 'reminder', answer: '是', chargeable: false },
  { kind: 'reminder', answer: null, chargeable: true },
  { kind: 'reminder', answer: null, chargeable: false, errorCode: 'model_busy' },
  { kind: 'reminder', source: 'llm', answer: null, chargeable: false },
  { kind: 'win', answer: '是' },
  { kind: 'win', answer: null, errorCode: 'model_busy' },
  { kind: 'win', source: 'llm', answer: null },
])('incoherent diagnostic refuses the entire candidate material %#', diagnostic => {
  const detail = candidateDetail();
  Object.assign(detail.material.programDiagnostic, diagnostic);
  expect(() => decodeCandidateDetail(detail, candidateId)).toThrow(AgentReviewContractError);
});

test.each([null, [], 'candidate', false])('candidate detail must be an object: %j', value => {
  expect(() => decodeCandidateDetail(value, candidateId)).toThrow(AgentReviewContractError);
});

test.each(['', ' ', 'x'.repeat(501)])('candidate questions reject blank or oversized strings: %j', question => {
  const detail = candidateDetail();
  detail.material.draft.question = question;
  expect(() => decodeCandidateDetail(detail, candidateId)).toThrow(AgentReviewContractError);
});

test.each(['truncated', 'cleanupConfirmed'] as const)('regression %s cannot be coerced from text', field => {
  const detail = candidateDetail();
  Object.assign(detail.material.report, { [field]: 'false' });
  expect(() => decodeCandidateDetail(detail, candidateId)).toThrow(AgentReviewContractError);
});

test.each([false, 1, 'x'.repeat(2001)])('review reason rejects wrong types or overflow: %j', reason => {
  const detail = candidateDetail();
  Object.assign(detail.material.sanitizedInput, { reason });
  expect(() => decodeCandidateDetail(detail, candidateId)).toThrow(AgentReviewContractError);
});

test('a review-ready status cannot omit its candidate identity', () => {
  expect(() => decodeAgentStatus({ ...agentStatus(), candidateId: null }, runId)).toThrow(AgentReviewContractError);
});

test('adding a rule has no replacement digest or old target', () => {
  const detail = candidateDetail();
  const added = { ...detail, material: { ...detail.material,
    draft: { ...detail.material.draft, operation: 'add', targetRuleDigest: null }, oldTarget: null } };
  expect(decodeCandidateDetail(added, candidateId).material?.draft.operation).toBe('add');
  expect(() => decodeCandidateDetail({ ...added, material: { ...added.material,
    draft: { ...added.material.draft, targetRuleDigest: '7'.repeat(64) } } }, candidateId)).toThrow(AgentReviewContractError);
});

function queuedRun() {
  return { id: runId, feedbackId: reportId, state: 'queued', rowVersion: 0,
    createdAt: 100, deadlineAt: null, modelAttemptsUsed: 0, toolAttemptsUsed: 0,
    candidateId: null, candidateStatus: null };
}

test('a genuinely queued run has no active deadline, consumed attempts or candidate', () => {
  expect(decodeAgentRunPage({ schemaVersion: 1, runs: [queuedRun()], nextCursor: null }).runs[0]).toEqual(queuedRun());
});

test.each([{ deadlineAt: 200 }, { modelAttemptsUsed: 1 }, { toolAttemptsUsed: 1 },
  { candidateId, candidateStatus: 'pending' }])('queued run cannot hide already consumed execution state %j', change => {
  expect(() => decodeAgentRunPage({ schemaVersion: 1, runs: [{ ...queuedRun(), ...change }], nextCursor: null }))
    .toThrow(AgentReviewContractError);
});

test('a terminal non-review run cannot grant an approved candidate state', () => {
  expect(() => decodeAgentRunPage({ schemaVersion: 1, runs: [{ ...queuedRun(),
    state: 'failed', candidateId, candidateStatus: 'approved' }], nextCursor: null })).toThrow(AgentReviewContractError);
});
