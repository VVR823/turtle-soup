import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import GamePage from './page';

vi.mock('next/navigation', () => {
  const router = { push: vi.fn() };
  return { useRouter: () => router, useParams: () => ({ id: 'synthetic' }),
    useSearchParams: () => new URLSearchParams('level=xuermu') };
});

const originalScroll = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView');
beforeEach(() => {
  vi.stubGlobal('alert', vi.fn());
  Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: () => {} });
});
afterEach(() => {
  if (originalScroll) Object.defineProperty(Element.prototype, 'scrollIntoView', originalScroll);
  else Reflect.deleteProperty(Element.prototype, 'scrollIntoView');
});

const facts = { completion: 50, verifiedCoverage: 50, scoreVersion: 'coverage-v1',
  reconstructionScore: null, plotProgress: 80, unknownTopics: ['天气'],
  evaluation: '已确认事实覆盖 50%，这不是还原评分。', keyPointsCovered: ['医生身份'],
  keyPointsMissing: ['另一个事实'], bottom: 'Synthetic revealed truth', unlockSoupId: 'synthetic-egg' };

function transport(evaluation: Record<string, unknown>, win = false) {
  let ended = false, solved = false, asked = 0;
  vi.stubGlobal('fetch', async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    const body = init?.body ? JSON.parse(String(init.body)) : {};
    if (url.endsWith('/api/chat') && !body.question) {
      return new Response(JSON.stringify({ requestId: body.requestId, sessionId: 'owned-session', soupTitle: 'Synthetic title',
        soupSurface: 'Public surface', questionLimit: 3, unlocks: 'synthetic-egg' }));
    }
    if (url.endsWith('/api/chat') && body.sessionId === 'owned-session') {
      asked = 1; solved = win;
      return new Response(JSON.stringify({ sessionId: 'owned-session', requestId: body.requestId, turnId: 'turn-owned', state: 'completed',
        reply: 'Synthetic win', isWin: win, isReveal: win, isGiveup: false, limitReached: false, isFreeReminder: false,
        kind: win ? 'win' : 'answer', remaining: 2 }));
    }
    if (url.endsWith('/api/evaluate') && body.sessionId === 'owned-session') {
      ended = true;
      return new Response(JSON.stringify(evaluation));
    }
    if (url.endsWith('/api/session/owned-session')) return new Response(JSON.stringify({ sessionId: 'owned-session', soupId: 'synthetic',
      soupTitle: 'Synthetic title', soupSurface: 'Public surface', questionLimit: 3, questionsAsked: asked, remaining: 3 - asked,
      unlocks: 'synthetic-egg', messages: [], status: solved ? 'solved' : ended ? 'given_up' : 'playing', evaluation: ended ? evaluation : null }));
    throw new Error(`Unexpected unit-test request ${url}`);
  });
}

async function openResult() {
  await screen.findByText('Public surface');
  fireEvent.click(screen.getByRole('button', { name: /揭晓答案/ }));
  await screen.findByText('Synthetic revealed truth');
}

test('real game result view separates coverage, narrative, null reconstruction and unlock', async () => {
  transport(facts);
  render(<GamePage />);
  await openResult();
  expect(screen.getByText('已确认事实覆盖')).toBeDefined();
  expect(screen.getByText('还原程度：尚未独立评估')).toBeDefined();
  expect(screen.getByText('剧情进度（非还原评分）：80%')).toBeDefined();
  expect(screen.getByText('隐藏彩蛋已解锁！')).toBeDefined();
  expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('50');
  expect(screen.queryByText('AI 根据本局问答自动评估的还原完成度')).toBeNull();
});

test('old reveal keeps its score but labels it historical', async () => {
  transport({ completion: 83, evaluation: 'Old stored result', keyPointsCovered: [],
    keyPointsMissing: [], bottom: 'Synthetic revealed truth' });
  render(<GamePage />);
  await openResult();
  expect(screen.getByText('历史分数（旧口径）')).toBeDefined();
  expect(screen.getByText('历史记录采用旧计分方式，不代表已确认事实')).toBeDefined();
  expect(screen.queryByText('记录中被明确问清的事实，不代表已还原故事')).toBeNull();
  expect(screen.queryByText('已确认事实覆盖')).toBeNull();
  expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('83');
});

test('actual game win still celebrates with zero fact bar and separate plot100', async () => {
  transport({ ...facts, completion: 0, verifiedCoverage: 0, plotProgress: 100,
    keyPointsCovered: [], keyPointsMissing: ['医生身份', '另一个事实'],
    evaluation: '剧情已通关；事实覆盖 0%，尚未独立评估还原。' }, true);
  render(<GamePage />);
  await screen.findByText('Public surface');
  fireEvent.change(screen.getByRole('textbox', { name: '向主持人提问' }), { target: { value: 'Synthetic win condition?' } });
  fireEvent.click(screen.getByRole('button', { name: '发送' }));
  await screen.findByText('通关！');
  expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('0');
  expect(screen.getByText('剧情进度（非还原评分）：100%')).toBeDefined();
});

test('malformed new score never opens a guessed result view', async () => {
  transport({ ...facts, completion: 100 });
  render(<GamePage />);
  await screen.findByText('Public surface');
  fireEvent.click(screen.getByRole('button', { name: /揭晓答案/ }));
  await waitFor(() => expect(screen.queryByText('Synthetic revealed truth')).toBeNull());
  await waitFor(() => expect(screen.getByRole('textbox', { name: '向主持人提问' })).toBeDefined());
  expect(screen.queryByRole('progressbar')).toBeNull();
});
