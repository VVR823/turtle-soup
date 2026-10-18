import { expect, test } from 'vitest';
import { metricsPage } from '../../tests/frontend/metrics-fixtures';
import { MetricsContractError, readMetricsPage } from './metrics-contract';
import { decodeFeedbackPage, decodeFeedbackReview, FeedbackContractError } from './feedback-contract';

function completePage() {
  const page = metricsPage();
  Object.assign(page.coverage, {
    state: 'complete', auditStartedAt: 900, agentStartedAt: 950,
    windowStartsBeforeAudit: false, windowStartsBeforeAgent: false,
    processAudit: { complete: true, permanentGap: false, dropped: 0, fallbackCount: 0, memoryCount: 0, activeIO: 0 },
  });
  return page;
}

test('complete coverage requires explicit source start times and a drained audit process', () => {
  expect(readMetricsPage(completePage()).coverage).toEqual(completePage().coverage);
});

test.each(['permanentGap', 'dropped', 'fallbackCount', 'memoryCount', 'activeIO'] as const)(
  'a complete process audit cannot hide %s', field => {
    const page = completePage();
    Object.assign(page.coverage.processAudit!, { [field]: field === 'permanentGap' ? true : 1 });
    expect(() => readMetricsPage(page)).toThrow(MetricsContractError);
  },
);

test.each(['auditStartedAt', 'agentStartedAt', 'windowStartsBeforeAudit', 'windowStartsBeforeAgent'] as const)(
  'complete coverage cannot omit or predate %s', field => {
    const page = completePage();
    Object.assign(page.coverage, { [field]: field.endsWith('At') ? null : true });
    expect(() => readMetricsPage(page)).toThrow(MetricsContractError);
  },
);

test('a partial process reports its pending writes without granting completeness', () => {
  const page = completePage();
  page.coverage.state = 'partial';
  page.coverage.processAudit!.complete = false;
  page.coverage.processAudit!.activeIO = 2;
  expect(readMetricsPage(page).coverage.processAudit).toMatchObject({ complete: false, activeIO: 2 });
  page.coverage.state = 'complete';
  expect(() => readMetricsPage(page)).toThrow(MetricsContractError);
});

test('publication ratio preserves a nonzero task denominator', () => {
  const page = metricsPage();
  page.summary.counts.tasksCreated = 2;
  page.summary.taskStates.awaiting_review = 2;
  page.summary.taskPublication = { numerator: 1, denominator: 2, ratio: 0.5 };
  expect(readMetricsPage(page).summary.taskPublication.ratio).toBe(0.5);
  page.summary.taskPublication.ratio = 1;
  expect(() => readMetricsPage(page)).toThrow(MetricsContractError);
});

test.each([null, [], 'private', false])('non-object aggregate responses are rejected: %j', value => {
  expect(() => readMetricsPage(value)).toThrow(MetricsContractError);
});

test.each([null, [], 'unknown'])('non-object regression observations are rejected: %j', value => {
  const page = metricsPage();
  Object.assign(page.summary, { postPublicationRegression: value });
  expect(() => readMetricsPage(page)).toThrow(MetricsContractError);
});

test.each([null, {}, Array.from({ length: 101 }, () => metricsPage().groups[0])])(
  'group results must be a bounded array %#', groups => {
    const page = metricsPage();
    Object.assign(page, { groups });
    expect(() => readMetricsPage(page)).toThrow(MetricsContractError);
  },
);

test.each([null, '', ' ', 'x'.repeat(201)])('invalid soup filter is refused: %j', soupId => {
  const page = metricsPage();
  // Null is a valid unfiltered query; all other values here are invalid.
  page.query.soupId = soupId;
  if (soupId === null) expect(readMetricsPage(page).query.soupId).toBeNull();
  else expect(() => readMetricsPage(page)).toThrow(MetricsContractError);
});

test('zero page limit cannot masquerade as an empty page', () => {
  const page = metricsPage();
  page.query.limit = 0;
  expect(() => readMetricsPage(page)).toThrow(MetricsContractError);
});

const rowId = 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa';
const feedback = () => ({
  id: rowId, ts: '2026-10-09T00:00:00Z', soupId: 'synthetic', soupTitle: null,
  question: '合成问题', hostAnswer: '是', expectedAnswer: '否', reason: null,
  status: 'pending', reviewedAt: null, mergedAt: null, mergedAnswer: null,
  rowVersion: 0, safeForModel: false, sourceState: 'unverified', turnId: null,
});
const feedbackPage = () => ({ totalInRange: 1, nextCursor: null, feedbacks: [feedback()] });

test.each(['', 1, 'x'.repeat(501)])('historical claims preserve whitespace but reject empty, wrong type and overflow: %j', question => {
  const page = feedbackPage();
  Object.assign(page.feedbacks[0], { question });
  expect(() => decodeFeedbackPage(page)).toThrow(FeedbackContractError);
});

test.each(['not-a-date', '1969-12-31T23:59:59Z', '2026-10-09T00:00:00'])(
  'feedback timestamp requires a finite nonnegative instant with timezone: %s', ts => {
    const page = feedbackPage();
    page.feedbacks[0].ts = ts;
    expect(() => decodeFeedbackPage(page)).toThrow(FeedbackContractError);
  },
);

test('timezone-bearing feedback timestamps preserve their original representation', () => {
  const page = feedbackPage();
  page.feedbacks[0].ts = '2026-10-09T08:00:00+08:00';
  expect(decodeFeedbackPage(page).feedbacks[0].ts).toBe(page.feedbacks[0].ts);
});

test('duplicate feedback identities are refused even when the declared total is large enough', () => {
  const page = feedbackPage();
  page.totalInRange = 2;
  page.feedbacks.push(feedback());
  expect(() => decodeFeedbackPage(page)).toThrow(FeedbackContractError);
});

test('feedback count cannot be smaller than the actual page', () => {
  const page = feedbackPage();
  page.totalInRange = 0;
  expect(() => decodeFeedbackPage(page)).toThrow(FeedbackContractError);
});

test('feedback cursor rejects punctuation outside the closed URL-safe alphabet', () => {
  const page = feedbackPage();
  Object.assign(page, { nextCursor: 'cursor+private=' });
  expect(() => decodeFeedbackPage(page)).toThrow(FeedbackContractError);
});

test.each([false, 1, 'true', null])('review success must be the literal boolean true: %j', ok => {
  const updated = { ...feedback(), status: 'approved', reviewedAt: '2026-10-09T00:01:00Z', rowVersion: 1 };
  expect(() => decodeFeedbackReview({ ok, feedback: updated }, rowId, 0, 'approved')).toThrow(FeedbackContractError);
});
