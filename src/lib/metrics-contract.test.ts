import { expect, test } from 'vitest';
import { metricsPage, metricsExport } from '../../tests/frontend/metrics-fixtures';

function sourceUnknownPage() {
  const page = metricsPage();
  return { ...page, schemaVersion: 2, summary: { ...page.summary,
    postPublicationRegression: { state: 'unknown', failedRuns: null, observedRuns: null, reason: 'source_not_integrated' } } };
}
test('v2 metrics preserve null missing-source observations in page and complete export', async () => {
  const { readMetricsPage, readMetricsExport } = await import('./metrics-contract');
  const page = sourceUnknownPage();
  expect(readMetricsPage(page).summary).toMatchObject({ postPublicationRegression:
    { state: 'unknown', failedRuns: null, observedRuns: null, reason: 'source_not_integrated' } });
  const exported = { ...metricsExport(), schemaVersion: 2, summary: page.summary };
  expect(readMetricsExport(exported).summary).toMatchObject({ postPublicationRegression: page.summary.postPublicationRegression });
});
test('old private metrics schema refuses instead of pretending absent regression observations are known', async () => {
  const { readMetricsPage, readMetricsExport } = await import('./metrics-contract');
  expect(() => readMetricsPage({ ...sourceUnknownPage(), schemaVersion: 1 })).toThrow();
  expect(() => readMetricsExport({ ...metricsExport(), schemaVersion: 1 })).toThrow();
});
test.each([{ failedRuns: 0 }, { observedRuns: 0 }, { failedRuns: false }, { state: 'complete' },
  { reason: 'verified_real_source' }, { privateReport: 'PRIVATE_CANARY' }])('v2 missing source never grants unproven counts %#', async change => {
  const { readMetricsPage } = await import('./metrics-contract');
  const page = sourceUnknownPage(); Object.assign(page.summary.postPublicationRegression, change);
  expect(() => readMetricsPage(page)).toThrow();
});

test.each(['unknown', 'partial', 'complete'])('coverage rejects an array coercible to %s instead of granting completeness', async state => {
  const { readMetricsPage, MetricsContractError } = await import('./metrics-contract');
  const page = metricsPage();
  Object.assign(page.coverage, { state: [state] });
  expect(() => readMetricsPage(page)).toThrow(MetricsContractError);
});

test('closed metrics retain explicit unknown coverage and zero denominator null', async () => {
  const { readMetricsPage, readMetricsExport } = await import('./metrics-contract');
  expect(readMetricsPage(metricsPage()).summary.taskPublication.ratio).toBeNull();
  expect(readMetricsPage(metricsPage()).coverage.state).toBe('unknown');
  expect(readMetricsExport(metricsExport()).complete).toBe(true);
});
const malformed: Array<(d: ReturnType<typeof metricsPage>) => void> = [
  d => { d.schemaVersion = 1; }, d => { d.consistency = 'frozen_forever'; },
  d => { d.query.start = NaN; }, d => { d.query.end = Infinity; }, d => { d.query.end = d.query.start + 31 * 86400 + 1; },
  d => { d.query.limit = 101; }, d => { d.summary.counts.httpAttempts = -1; },
  d => { d.summary.counts.sessionsCreated = Number.MAX_SAFE_INTEGER + 1; },
  d => { Object.assign(d.summary.counts, { sessionsCreated: true }); },
  d => { d.summary.taskPublication.ratio = 0; }, d => { d.summary.taskStates.failed = 1; },
  d => { d.summary.candidateStates.pending = 1; }, d => { d.summary.taskPublication.denominator = 1; },
  d => { d.coverage.state = 'complete'; }, d => { d.coverage.historicalAttemptsBackfilled = true; },
  d => { d.groups[0].day = '1970-02-30'; }, d => { d.groups[0].day = '1970-01-02'; },
  d => { d.groups[0].ruleVersion = 'PRIVATE_FREE_TEXT'; }, d => { d.groups.push({ ...d.groups[0] }); },
  d => { d.groups[0].counts.sessionsCreated = 3; }, d => { d.query.soupId = 'another'; },
  d => { d.nextCursor = 'PRIVATE+INVALID'; }, d => { d.groups = []; d.nextCursor = 'encoded'; },
  d => { Object.assign(d, { rawQuestion: 'PRIVATE' }); },
  d => { Object.assign(d.coverage, { playerId: 'PRIVATE' }); },
];
test.each(malformed)('rejects malformed/private/unbound metrics page %#', async mutate => {
  const { readMetricsPage, MetricsContractError } = await import('./metrics-contract');
  const data = metricsPage(); mutate(data);
  expect(() => readMetricsPage(data)).toThrow(MetricsContractError);
});
test('complete export requires all group totals and no cursor/private fields', async () => {
  const { readMetricsExport } = await import('./metrics-contract');
  const data = metricsExport(); data.groups = [];
  expect(() => readMetricsExport(data)).toThrow();
  expect(() => readMetricsExport({ ...metricsExport(), complete: false })).toThrow();
  expect(() => readMetricsExport({ ...metricsExport(), nextCursor: 'encoded' })).toThrow();
  expect(() => readMetricsExport({ ...metricsExport(), generatedAt: NaN })).toThrow();
});
test('empty complete export and null public source dimensions stay explicit', async () => {
  const { readMetricsPage, readMetricsExport } = await import('./metrics-contract');
  const page = metricsPage(); page.groups[0].soupId = page.groups[0].puzzleVersion = page.groups[0].ruleVersion = null;
  page.summary.unscopedReal.sessionsCreated = 2;
  expect(readMetricsPage(page).groups[0].soupId).toBeNull();
  const exported = metricsExport(); exported.groups = []; exported.summary.counts.sessionsCreated = 0;
  expect(readMetricsExport(exported).groups).toEqual([]);
});
