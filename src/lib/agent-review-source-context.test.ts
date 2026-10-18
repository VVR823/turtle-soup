import { expect, test } from 'vitest';
import { decodeCandidateDetail } from './agent-review-contract';
import { candidateDetail, candidateId, runId, reportId, operationKey, puzzle, rule } from '../../tests/frontend/agent-review-fixtures';

const sourceContext = () => ({ inputKind: 'stored_private_source', scope: 'admin_review_only', sessionId: reportId,
  turnId: runId, soupId: 'synthetic', puzzleVersion: puzzle, ruleVersion: rule,
  originalQuestion: '原本他指的是小明吗？', originalHostAnswer: '不是', contextDigest: 'e'.repeat(64),
  messages: [{ messageId: 1, turnId: operationKey, role: 'user', content: '刚才说的是小明吗？' },
    { messageId: 2, turnId: operationKey, role: 'host', content: '是' }] });
const detail = () => ({ ...candidateDetail(), material: { ...candidateDetail().material, sourceContext: sourceContext() } });

test('complete actual-source projection stays separate from the sanitized model claim', () => {
  const result = decodeCandidateDetail(detail(), candidateId);
  expect(result.material).toMatchObject({ sanitizedInput: { question: '他知道吗？' },
    sourceContext: { scope: 'admin_review_only', originalQuestion: '原本他指的是小明吗？',
      messages: [{ content: '刚才说的是小明吗？' }, { content: '是' }] } });
});
test.each(['self-turn', 'duplicate-id', 'foreign-puzzle', 'too-many', 'too-large', 'wrong-scope'])('malformed original context %s grants no detail', change => {
  const data = detail();
  if (change === 'self-turn') data.material.sourceContext.messages[0].turnId = runId;
  if (change === 'duplicate-id') data.material.sourceContext.messages[1].messageId = 1;
  if (change === 'foreign-puzzle') data.material.sourceContext.puzzleVersion = 'p1:' + 'f'.repeat(64);
  if (change === 'too-many') data.material.sourceContext.messages = Array.from({ length: 102 }, (_, n) => ({
    messageId: n + 1, turnId: operationKey, role: n % 2 ? 'host' : 'user', content: '是' }));
  if (change === 'too-large') data.material.sourceContext.originalHostAnswer = '界'.repeat(50000);
  if (change === 'wrong-scope') data.material.sourceContext.scope = 'model_input';
  expect(() => decodeCandidateDetail(data, candidateId)).toThrow();
});
