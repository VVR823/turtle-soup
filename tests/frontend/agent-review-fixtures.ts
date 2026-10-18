// Complete declared-synthetic wire shapes, NOT genuine model/human quality evidence.
export const runId = 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa';
export const candidateId = 'bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb';
export const reportId = 'cccccccc-cccc-4ccc-cccc-cccccccccccc';
export const operationKey = 'dddddddd-dddd-4ddd-dddd-dddddddddddd';
export const proof = '1'.repeat(64), factId = 'f1:' + '2'.repeat(64);
export const puzzle = 'p1:' + '3'.repeat(64), rule = 'r1:' + '4'.repeat(64);
export const nextRule = 'r1:' + '5'.repeat(64);
export function agentStatus() {
  return { id: runId, state: 'awaiting_review', rowVersion: 9, modelAttemptsUsed: 3, toolAttemptsUsed: 2,
    deadlineAt: 180, reason: null, candidateId,
    steps: [{ seq: 0, action: 'tool', state: 'completed', tool: 'run_regression' },
      { seq: 1, action: 'finish', state: 'completed', tool: null }] };
}
export function candidateDetail() {
  return { schemaVersion: 1, candidateId, runId, candidateStatus: 'pending', reviewVersion: 0,
    agentStatus: agentStatus(), activeRuleVersion: rule, activePointerVersion: 0, proofDigest: proof,
    availability: 'ready', blockers: [], review: null, publishedRuleVersion: null,
    material: { inputKind: 'user_claim', draftKind: 'model_summary',
      sourceContext: { inputKind: 'stored_private_source', scope: 'admin_review_only', sessionId: reportId,
        turnId: runId, soupId: 'synthetic', puzzleVersion: puzzle, ruleVersion: rule,
        originalQuestion: '原本他指的是小明吗？', originalHostAnswer: '不是', contextDigest: 'e'.repeat(64),
        messages: [{ messageId: 1, turnId: operationKey, role: 'user', content: '刚才说的是小明吗？' },
          { messageId: 2, turnId: operationKey, role: 'host', content: '是' }] },
      sanitizedInput: { question: '他知道吗？', hostAnswer: '不是', expectedClaim: '是', reason: null },
      programDiagnostic: { kind: 'answer', source: 'deterministic', answer: '不是', chargeable: true,
        errorCode: null, engineVersion: 'host-v3', normalizationVersion: 'exact-v1', resultDigest: '6'.repeat(64) },
      draft: { schemaVersion: 1, type: 'exact_qa', operation: 'replace', targetRuleDigest: '7'.repeat(64),
        soupId: 'synthetic', puzzleVersion: puzzle, baseRuleVersion: rule, question: '他知道吗？',
        normalizationVersion: 'exact-v1', answer: '是', factIds: [factId], evidenceSummary: '模型建议，不是真人确认。' },
      factScope: [{ id: factId, soupId: 'synthetic', puzzleVersion: puzzle, sourcePath: 'truth', category: 'truth',
        payload: '{"text":"可能知道，但仅限事后","confidence":"low"}' }],
      highlightedFactIds: [factId], oldTarget: { targetRuleDigest: '7'.repeat(64), type: 'confusion',
        sourcePath: 'confusionPoints[0]', question: '他知道吗？', answer: '不是' },
      report: { schemaVersion: 1, reportId, runId, draftDigest: '8'.repeat(64), contextDigest: '9'.repeat(64),
        suiteManifestDigest: 'a'.repeat(64), puzzleVersion: puzzle, baseRuleVersion: rule,
        evidenceKind: 'synthetic_fixture', status: 'complete', inputCaseCount: 1, attemptedCaseCount: 1,
        passedCaseCount: 1, elapsedSeconds: 0.1, truncated: false, cleanupConfirmed: true,
        caseResults: [{ caseId: reportId, suite: 'dev_regression', passed: true, code: 'passed' }] } } };
}
export function reviewState() {
  return { schemaVersion: 1, candidateId, status: 'approved', candidateDigest: 'b'.repeat(64),
    candidateDraftDigest: '8'.repeat(64), publicationDraftDigest: 'c'.repeat(64), reportId,
    reportDigest: 'd'.repeat(64), suiteManifestDigest: 'a'.repeat(64), contextDigest: '9'.repeat(64),
    sourceFeedbackVersion: 2, targetRuleDigest: '7'.repeat(64), proofDigest: proof, approvalOperationKey: operationKey,
    reviewNote: '人工核对', reviewedAt: 200, lastOperationKey: operationKey, publishedRuleVersion: null,
    reviewReceipt: { draftDigest: 'c'.repeat(64), candidateDigest: 'b'.repeat(64), regressionReportId: reportId,
      reportDigest: 'd'.repeat(64), suiteManifestDigest: 'a'.repeat(64), puzzleVersion: puzzle, baseRuleVersion: rule,
      status: 'complete', answerSupported: true, contextIndependent: true, reviewNote: '人工核对' } };
}
