import { expect, test } from 'vitest';

const id = 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa';
export function feedback(changes: Record<string, unknown> = {}) {
  return { id, ts: '2026-10-09T00:00:00Z', soupId: 'synthetic', soupTitle: 'Test', question: '谁是凶手？',
    hostAnswer: '是', expectedAnswer: '不知道', reason: null, status: 'pending', reviewedAt: null,
    mergedAt: null, mergedAnswer: null, rowVersion: 3, safeForModel: false, sourceState: 'unverified',
    turnId: null, ...changes };
}

test.each(['soupId', 'question', 'hostAnswer', 'expectedAnswer'])(
  'a historical blank %s stays inspectable without poisoning a mixed private page', async field => {
    const { decodeFeedbackPage } = await import('./feedback-contract');
    const old = feedback({ id: 'bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb', [field]: ' \t ' });
    const page = decodeFeedbackPage({ totalInRange: 2, nextCursor: null, feedbacks: [feedback(), old] });
    expect(page.feedbacks).toHaveLength(2);
    expect(page.feedbacks[1][field as 'soupId' | 'question' | 'hostAnswer' | 'expectedAnswer']).toBe(' \t ');
    expect(page.feedbacks.every(row => !row.safeForModel && row.status === 'pending')).toBe(true);
  },
);

test.each([{ reason: '' }, { reason: '  ' }, { soupTitle: '' }, { soupTitle: '汤'.repeat(500) }])(
  'backend-valid optional strings %j do not poison the whole admin page', async change => {
    const { decodeFeedbackPage } = await import('./feedback-contract');
    const actual = decodeFeedbackPage({ totalInRange: 1, nextCursor: null, feedbacks: [feedback(change)] }).feedbacks[0];
    for (const [key, value] of Object.entries(change)) expect(actual[key as keyof typeof actual]).toBe(value);
  },
);

test.each([{ reason: 1 }, { reason: 'x'.repeat(2001) }, { soupTitle: [] }, { soupTitle: '汤'.repeat(501) }])(
  'optional strings still reject malformed bounds %j', async change => {
    const { decodeFeedbackPage } = await import('./feedback-contract');
    expect(decodeFeedbackPage({ totalInRange: 1, nextCursor: null, feedbacks: [feedback()] }).feedbacks).toHaveLength(1);
    expect(() => decodeFeedbackPage({ totalInRange: 1, nextCursor: null, feedbacks: [feedback(change)] })).toThrow();
  },
);

test('page is a bounded time-window count with a cursor, not an unbounded total', async () => {
  const { decodeFeedbackPage } = await import('./feedback-contract');
  const page = decodeFeedbackPage({ totalInRange: 51, nextCursor: 'owned_cursor', feedbacks: [feedback()] });
  expect(page.totalInRange).toBe(51); expect(page.nextCursor).toBe('owned_cursor');
  expect(page.feedbacks[0].expectedAnswer).toBe('不知道');
  expect(() => decodeFeedbackPage({ total: 51, feedbacks: [feedback()] })).toThrow();
});

test.each([true, -1, 1.2, Number.MAX_SAFE_INTEGER + 1, '3'])('rowVersion %s cannot authorize a browser review', async version => {
  const { decodeFeedbackPage } = await import('./feedback-contract');
  expect(decodeFeedbackPage({ totalInRange: 1, nextCursor: null, feedbacks: [feedback()] }).feedbacks[0].rowVersion).toBe(3);
  expect(() => decodeFeedbackPage({ totalInRange: 1, nextCursor: null, feedbacks: [feedback({ rowVersion: version })] })).toThrow();
});

test.each([{ safeForModel: 'true' }, { sourceState: 'trusted' }, { status: 'published' },
  { mergedAt: '2026-10-09T00:00:00Z' }, { id: 'foreign' }])('malformed private review row %j is refused', async change => {
  const { decodeFeedbackPage } = await import('./feedback-contract');
  expect(decodeFeedbackPage({ totalInRange: 1, nextCursor: null, feedbacks: [feedback()] }).feedbacks[0].safeForModel).toBe(false);
  expect(() => decodeFeedbackPage({ totalInRange: 1, nextCursor: null, feedbacks: [feedback(change)] })).toThrow();
});

test('oversized page or cursor is not silently truncated into a complete page', async () => {
  const { decodeFeedbackPage } = await import('./feedback-contract');
  expect(decodeFeedbackPage({ totalInRange: 1, nextCursor: null, feedbacks: [feedback()] }).feedbacks).toHaveLength(1);
  expect(() => decodeFeedbackPage({ totalInRange: 101, nextCursor: null, feedbacks: Array(101).fill(feedback()) })).toThrow();
  expect(() => decodeFeedbackPage({ totalInRange: 1, nextCursor: 'x'.repeat(513), feedbacks: [feedback()] })).toThrow();
});

test('review response must be actual same row and exactly next version, not client optimistic status', async () => {
  const { decodeFeedbackReview } = await import('./feedback-contract');
  const updated = feedback({ rowVersion: 4, status: 'approved', reviewedAt: '2026-10-09T00:01:00Z' });
  expect(decodeFeedbackReview({ ok: true, feedback: updated }, id, 3, 'approved').rowVersion).toBe(4);
  expect(() => decodeFeedbackReview({ ok: true }, id, 3, 'approved')).toThrow();
  expect(() => decodeFeedbackReview({ ok: true, feedback: updated }, 'bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb', 3, 'approved')).toThrow();
  expect(() => decodeFeedbackReview({ ok: true, feedback: updated }, id, 4, 'approved')).toThrow();
  expect(() => decodeFeedbackReview({ ok: true, feedback: updated }, id, 3, 'rejected')).toThrow();
});
