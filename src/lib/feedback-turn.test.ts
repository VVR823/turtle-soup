import { expect, test } from 'vitest';
import type { SessionSnapshot } from './game-contract';

const id = 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa';
function session(): SessionSnapshot {
  return { sessionId: 'owned-session', soupId: 'synthetic', soupTitle: '合成题目', soupSurface: '', questionLimit: 3,
    questionsAsked: 1, remaining: 2, unlocks: null, status: 'playing', evaluation: null,
    messages: [{ role: 'user', content: '小明是凶手吗？', timestamp: 1, turnId: id },
      { role: 'host', content: '不是', timestamp: 2, turnId: id, isFreeReminder: false }] };
}
test('explicit answer feedback uses its unique public question pair, not the most recent session guess', async () => {
  const { feedbackTurn } = await import('./feedback-turn');
  expect(feedbackTurn(session(), 1)).toEqual({ soupId: 'synthetic', soupTitle: '合成题目',
    turnId: id, question: '小明是凶手吗？', hostAnswer: '不是' });
});
test.each(['missing', 'legacy-id', 'reminder', 'unknown-answer', 'ambiguous-user', 'unpaired', 'user-row'])(
  'no fabricated answer link for %s', async mode => {
    const { feedbackTurn } = await import('./feedback-turn');
    const data = session();
    if (mode === 'missing') delete data.messages[1].turnId;
    if (mode === 'legacy-id') data.messages[1].turnId = 'legacy-turn';
    if (mode === 'reminder') data.messages[1].isFreeReminder = true;
    if (mode === 'unknown-answer') data.messages[1].content = '系统暂不可用';
    if (mode === 'ambiguous-user') data.messages.unshift({ ...data.messages[0] });
    if (mode === 'unpaired') data.messages[0].turnId = 'bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb';
    expect(feedbackTurn(data, mode === 'ambiguous-user' ? 2 : mode === 'user-row' ? 0 : 1)).toBeNull();
  });
