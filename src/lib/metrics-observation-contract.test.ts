import { expect, test } from 'vitest';
import { readMetricsPage, readMetricsExport } from './metrics-contract';
import { observedMetricsPage, metricsExport, observationCounts } from '../../tests/frontend/metrics-fixtures';

test('v3 preserves full test observation denominator separately from real business counters', () => {
  const page = readMetricsPage(observedMetricsPage());
  expect(page.schemaVersion).toBe(3);
  expect(page.summary.postPublicationRegression).toMatchObject({ state: 'observed', observedRuns: 0,
    failedRuns: 0, excluded: { test: observationCounts() } });
  expect(page.summary.counts.sessionsCreated).toBe(2);
  const exported = readMetricsExport({ ...metricsExport(), schemaVersion: 3, summary: observedMetricsPage().summary });
  expect(exported.summary.postPublicationRegression).toEqual(page.summary.postPublicationRegression);
});

test.each([{ observedRuns: 3 }, { pendingExpiredRuns: 2 }, { plannedCases: 3 }, { attemptedCases: 2 },
  { passedCases: true }, { errorCases: -1 }, { accuracy: 1 }, { privateReport: 'PRIVATE' },
  { observedRuns: Number.MAX_SAFE_INTEGER + 1 }, { pendingRuns: 4, passedRuns: 0, failedRuns: 0, incompleteRuns: 0 }])(
  'v3 refuses contradictory, incomplete or private observation totals %#', mutation => {
    const page = observedMetricsPage(); Object.assign(page.summary.postPublicationRegression.excluded.test, mutation);
    expect(() => readMetricsPage(page)).toThrow();
  });

test('v3 missing counters cannot become invented zeros', () => {
  const page = observedMetricsPage();
  const { errorCases: omitted, ...partial } = page.summary.postPublicationRegression.excluded.test;
  expect(omitted).toBe(0);
  Object.assign(page.summary.postPublicationRegression.excluded, { test: partial });
  expect(() => readMetricsPage(page)).toThrow();
});

test.each([{ passedRuns: 1, notAttemptedCases: 1 },
  { failedRuns: 1, attemptedCases: 1, passedCases: 1 },
  { incompleteRuns: 1, attemptedCases: 1, counterexampleCases: 1 }])(
  'v3 run status requires supporting case evidence %#', mutation => {
    const page = observedMetricsPage();
    const zero = Object.fromEntries(Object.keys(observationCounts()).map(key => [key, 0]));
    Object.assign(page.summary.postPublicationRegression.excluded,
      { test: { ...zero, observedRuns: 1, plannedCases: 1, ...mutation } });
    expect(() => readMetricsPage(page)).toThrow();
  });

test('v3 incomplete may retain all passed cases after cleanup or deadline failure', () => {
  const page = observedMetricsPage();
  const zero = Object.fromEntries(Object.keys(observationCounts()).map(key => [key, 0]));
  Object.assign(page.summary.postPublicationRegression.excluded,
    { test: { ...zero, observedRuns: 1, incompleteRuns: 1, plannedCases: 1, attemptedCases: 1, passedCases: 1 } });
  expect(readMetricsPage(page).summary.postPublicationRegression).toMatchObject(
    { excluded: { test: { incompleteRuns: 1, passedCases: 1 } } });
});

test.each([{ historicalBackfill: 0 }, { historicalBackfill: true }, { sourceCoverageStart: true },
  { state: 'partial' }, { sourceCoverageStart: 1001 }, { windowStartsBeforeCoverage: [false] }])(
  'v3 coverage must be exact and bound to the returned window %#', mutation => {
    const page = observedMetricsPage(); Object.assign(page.summary.postPublicationRegression, mutation);
    expect(() => readMetricsPage(page)).toThrow();
  });

test('partial v3 observation coverage and complete export use the same window binding', () => {
  const page = observedMetricsPage(); page.query.start = 999;
  Object.assign(page.summary.postPublicationRegression, { state: 'partial', windowStartsBeforeCoverage: true });
  expect(readMetricsPage(page).summary.postPublicationRegression.state).toBe('partial');
  const exported = { ...metricsExport(), schemaVersion: 3, window: { start: 999, end: 1100 }, summary: page.summary };
  expect(readMetricsExport(exported).summary.postPublicationRegression.state).toBe('partial');
  expect(() => readMetricsExport({ ...exported, window: { start: 1000, end: 1100 } })).toThrow();
});

test.each(['schema_5_required', 'source_unavailable'])('v3 discloses %s as null, not zero', reason => {
  const page = observedMetricsPage();
  Object.assign(page.summary, { postPublicationRegression: { state: 'unknown', failedRuns: null, observedRuns: null, reason } });
  expect(readMetricsPage(page).summary.postPublicationRegression).toEqual({ state: 'unknown', failedRuns: null, observedRuns: null, reason });
});

test('v2 compatibility refuses any v3 known observation object', () => {
  expect(() => readMetricsPage({ ...observedMetricsPage(), schemaVersion: 2 })).toThrow();
});
