/** Declared synthetic aggregate responses, never a real user/performance claim. */
export const metricsCounts = () => ({ sessionsCreated: 0, successfulChargedTurns: 0, httpAttempts: 0,
  feedbackSubmitted: 0, tasksCreated: 0, candidatesCreated: 0, reviewApproved: 0, reviewRejected: 0,
  candidatePublicationEvents: 0 });
export const metricsPage = () => ({ schemaVersion: 2, consistency: 'fixed_window_live_snapshot',
  query: { start: 1000, end: 1100, soupId: null as string | null, puzzleVersion: null as string | null,
    ruleVersion: null as string | null, limit: 50, cursor: null as string | null },
  summary: { counts: { ...metricsCounts(), sessionsCreated: 2 },
    excluded: { test: metricsCounts(), synthetic: metricsCounts(), legacy: metricsCounts(), unknown: metricsCounts() },
    unscopedReal: metricsCounts(), taskStates: { queued: 0, running: 0, awaiting_review: 0, needs_human: 0, failed: 0, cancelled: 0 },
    candidateStates: { pending: 0, approved: 0, rejected: 0, published: 0 },
    taskPublication: { numerator: 0, denominator: 0, ratio: null as number | null },
    postPublicationRegression: { state: 'unknown', failedRuns: null, observedRuns: null, reason: 'source_not_integrated' } },
  coverage: { auditStartedAt: null as number | null, agentStartedAt: null as number | null,
    historicalAttemptsBackfilled: false, historicalRunsBackfilled: false, windowStartsBeforeAudit: null as boolean | null,
    windowStartsBeforeAgent: null as boolean | null, processAudit: null as null | { complete: boolean; permanentGap: boolean;
      dropped: number; fallbackCount: number; memoryCount: number; activeIO: number }, state: 'unknown' },
  groups: [{ day: '1970-01-01', soupId: 'synthetic' as string | null, puzzleVersion: 'p1:' + 'a'.repeat(64) as string | null,
    ruleVersion: 'r1:' + 'b'.repeat(64) as string | null, counts: { ...metricsCounts(), sessionsCreated: 2 } }],
  nextCursor: null as string | null });
export const metricsExport = () => {
  const page = metricsPage();
  return { schemaVersion: 2, window: { start: page.query.start, end: page.query.end },
    filters: { soupId: page.query.soupId, puzzleVersion: page.query.puzzleVersion, ruleVersion: page.query.ruleVersion },
    summary: page.summary, coverage: page.coverage, groups: page.groups, complete: true, generatedAt: 1200 };
};

export const observationCounts = () => ({ observedRuns: 4, passedRuns: 1, failedRuns: 1, incompleteRuns: 1,
  pendingRuns: 1, pendingExpiredRuns: 1, plannedCases: 4, attemptedCases: 3, passedCases: 1,
  counterexampleCases: 1, errorCases: 0, unsupportedCases: 1, notAttemptedCases: 1 });
export const zeroObservationCounts = () => ({ observedRuns: 0, passedRuns: 0, failedRuns: 0, incompleteRuns: 0,
  pendingRuns: 0, pendingExpiredRuns: 0, plannedCases: 0, attemptedCases: 0, passedCases: 0,
  counterexampleCases: 0, errorCases: 0, unsupportedCases: 0, notAttemptedCases: 0 });
export const observedMetricsPage = () => {
  const page = metricsPage();
  return { ...page, schemaVersion: 3, summary: { ...page.summary,
    postPublicationRegression: { ...zeroObservationCounts(), state: 'observed', sourceCoverageStart: 1000,
      historicalBackfill: false, windowStartsBeforeCoverage: false,
      excluded: { test: observationCounts(), synthetic: zeroObservationCounts(), unknown: zeroObservationCounts() } } } };
};
