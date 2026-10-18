import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { getLastSession, saveLastSession, type ApiJsonResponse } from './api';
import { GameController } from './game-controller';
import { readPending, writePending } from './game-journal';

const target = { soupId: 'synthetic', level: 'xuermu' };
const requestId = '29ab9f58-d899-41dd-a2ab-8e7b3667c9f1';
const pending = { ...target, kind: 'ask' as const, sessionId: 'owned', question: '合成问题吗', requestId };
const reserved = { sessionId: 'owned', requestId, turnId: 'turn-owned', state: 'reserved', code: 'turn_in_progress', detail: '处理中' };
const session = { sessionId: 'owned', soupId: 'synthetic', soupTitle: 'Public', soupSurface: 'Public story',
  questionLimit: 3, questionsAsked: 1, remaining: 2, unlocks: null, status: 'playing', messages: [], evaluation: null };
const response = (body: unknown, status = 200): ApiJsonResponse => ({ body, status, ok: status >= 200 && status < 300, headers: new Headers() });
type Request = (path: string, init?: RequestInit) => Promise<ApiJsonResponse>;
const controllers: GameController[] = [];
function own(request: Request) {
  const game = new GameController(target, { request, newId: () => requestId });
  controllers.push(game);
  return game;
}
function pollingRequest() {
  return vi.fn<Request>(async path => path.includes('/turns/') ? response(reserved, 202) : response(session));
}
function seedAsk() {
  saveLastSession({ ...target, sessionId: 'owned' });
  writePending(pending);
}
beforeEach(() => { localStorage.clear(); vi.useFakeTimers(); });
afterEach(() => {
  for (const game of controllers.splice(0)) game.dispose();
  vi.useRealTimers();
});

// A missing/default-zero delay or unbounded loop would add extra GETs here.
test('default polling waits two full seconds for at most three same-UUID GETs', async () => {
  seedAsk();
  const request = pollingRequest(), game = own(request);
  const recovering = game.initialize();
  await vi.advanceTimersByTimeAsync(0);
  expect(game.getSnapshot().phase).toBe('syncing');
  expect(request).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(999);
  expect(request).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(1);
  expect(request).toHaveBeenCalledTimes(4);
  await vi.advanceTimersByTimeAsync(999);
  expect(request).toHaveBeenCalledTimes(4);
  await vi.advanceTimersByTimeAsync(1);
  await recovering;
  expect(request.mock.calls.map(args => args[0])).toEqual(Array.from({ length: 3 }, () => [
    `/api/session/owned/turns/${requestId}`, '/api/session/owned',
  ]).flat());
  expect(request.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true);
  expect(readPending(target)).toEqual(pending);
  expect(game.getSnapshot()).toMatchObject({ phase: 'syncing', pending, error: { category: 'service' } });
  expect(vi.getTimerCount()).toBe(0);
});

// Not clearing a timer on abort would leave work queued after navigation.
test('disposing during the default wait removes its timer and preserves unknown submission', async () => {
  seedAsk();
  const request = pollingRequest(), game = own(request);
  const recovering = game.initialize();
  await vi.advanceTimersByTimeAsync(0);
  expect(vi.getTimerCount()).toBe(1);
  const before = game.getSnapshot();
  game.dispose();
  expect(vi.getTimerCount()).toBe(0); // Must be cleared now, not merely expire after time advances.
  await recovering;
  await vi.advanceTimersByTimeAsync(5000);
  expect(vi.getTimerCount()).toBe(0);
  expect(request).toHaveBeenCalledTimes(2);
  expect(game.getSnapshot()).toBe(before);
  expect(readPending(target)).toEqual(pending);
});

// An already-aborted wait must reject, not install a new timer or hang.
test('leaving from a syncing subscriber refuses the already-aborted default wait', async () => {
  seedAsk();
  const request = pollingRequest(), game = own(request);
  let published: ReturnType<GameController['getSnapshot']> | undefined;
  game.subscribe(() => {
    if (game.getSnapshot().phase === 'syncing') { published = game.getSnapshot(); game.dispose(); }
  });
  await game.initialize();
  expect(published).toMatchObject({ phase: 'syncing', pending });
  expect(game.getSnapshot()).toBe(published);
  // jsdom queues zero-delay storage notifications; do not confuse them with a 1000ms poll.
  await vi.advanceTimersByTimeAsync(0);
  expect(vi.getTimerCount()).toBe(0);
  expect(request).toHaveBeenCalledTimes(2);
  expect(readPending(target)).toEqual(pending);
});

// Removing the post-wait generation fence would issue another GET after leave.
test('navigation after the timer fires but before its continuation prevents another poll', async () => {
  seedAsk();
  const request = pollingRequest(), game = own(request);
  const recovering = game.initialize();
  await vi.advanceTimersByTimeAsync(0);
  const before = game.getSnapshot();
  vi.advanceTimersByTime(1000); // Resolve timer synchronously, before awaiting its continuation.
  game.dispose();
  await recovering;
  expect(game.getSnapshot()).toBe(before);
  expect(request).toHaveBeenCalledTimes(2);
  expect(readPending(target)).toEqual(pending);
  expect(vi.getTimerCount()).toBe(0);
});

// Removing the post-GET generation fence would begin reconciliation on a new page.
test('late turn GET after disposal cannot touch the foreign pointer or original journal', async () => {
  seedAsk();
  let resolve!: (value: ApiJsonResponse) => void;
  const slow = new Promise<ApiJsonResponse>(finish => { resolve = finish; });
  const request = vi.fn<Request>(() => slow), game = own(request);
  const recovering = game.initialize(), before = game.getSnapshot();
  game.dispose();
  const other = { soupId: 'other', level: '', sessionId: 'other-owned' };
  saveLastSession(other);
  resolve(response(reserved, 202));
  await recovering;
  expect(game.getSnapshot()).toBe(before);
  expect(getLastSession()).toEqual(other);
  expect(readPending(target)).toEqual(pending);
  expect(request.mock.calls.map(args => args[0])).toEqual([`/api/session/owned/turns/${requestId}`]);
  await vi.advanceTimersByTimeAsync(0); // Deliver only the synthetic storage notifications.
  expect(vi.getTimerCount()).toBe(0);
});

// Treating unknown rejection as a completed failure could erase the create UUID.
test.each([null, 'Synthetic private transport detail'])('non-Error rejection %j keeps the original creation and a safe network error', async rejected => {
  const request = vi.fn<Request>(async () => { throw rejected; }), game = own(request);
  await game.initialize();
  expect(game.getSnapshot()).toMatchObject({ phase: 'error', error: {
    category: 'network', message: '网络暂时不可用，请同步原对局', retryAfterSeconds: null,
  } });
  expect(readPending(target)).toEqual({ ...target, kind: 'create', requestId });
  expect(getLastSession()).toBeNull();
  expect(request).toHaveBeenCalledTimes(1);
  expect(JSON.parse(String(request.mock.calls[0][1]?.body))).toEqual({ ...target, requestId });
});
