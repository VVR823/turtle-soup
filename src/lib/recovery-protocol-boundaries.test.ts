import { beforeEach, expect, test, vi } from 'vitest';
import { getLastSession, saveLastSession, type ApiJsonResponse } from './api';
import { GameController } from './game-controller';
import { GameStorageError, readPending, writePending } from './game-journal';

const target = { soupId: 'synthetic', level: 'xuermu' };
const requestId = '29ab9f58-d899-41dd-a2ab-8e7b3667c9f1';
const creation = { ...target, kind: 'create' as const, requestId };
const ask = { ...target, kind: 'ask' as const, requestId, sessionId: 'owned', question: '合成问题吗' };
const reveal = { ...target, kind: 'reveal' as const, sessionId: 'owned' };
const response = (body: unknown, status = 200): ApiJsonResponse => ({ body, status, ok: status >= 200 && status < 300, headers: new Headers() });
const session = { sessionId: 'owned', soupId: 'synthetic', soupTitle: 'Public', soupSurface: 'Public story',
  questionLimit: 3, questionsAsked: 1, remaining: 2, unlocks: null, status: 'playing', messages: [], evaluation: null };
const evaluation = { completion: 0, verifiedCoverage: 0, scoreVersion: 'coverage-v1', reconstructionScore: null,
  evaluation: 'Synthetic', keyPointsCovered: [], keyPointsMissing: ['A'], bottom: 'Synthetic truth', plotProgress: 100 };
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(finish => { resolve = finish; });
  return { promise, resolve };
}
beforeEach(() => localStorage.clear());

// Missing target validation would treat a damaged route as an empty new game.
test.each([{ soupId: '', level: '' }, { soupId: 'x'.repeat(201), level: '' },
  { soupId: 'synthetic', level: 'x'.repeat(51) }])('invalid caller target preserves the valid pending game: %j', invalid => {
  writePending(creation);
  const raw = localStorage.getItem(localStorage.key(0)!);
  expect(() => readPending(invalid)).toThrow(GameStorageError);
  expect(readPending(target)).toEqual(creation);
  expect(localStorage.length).toBe(1);
  expect(localStorage.getItem(localStorage.key(0)!)).toBe(raw);
});

// Returning null without a browser would falsely authorize a new operation.
test('missing window refuses journal reads and writes instead of inventing empty storage', () => {
  writePending(creation);
  const stored = localStorage, key = stored.key(0)!, raw = stored.getItem(key);
  vi.stubGlobal('window', undefined);
  try {
    expect(() => readPending(target)).toThrow(GameStorageError);
    expect(() => writePending(creation)).toThrow(GameStorageError);
    expect(stored.getItem(key)).toBe(raw);
    expect(stored.length).toBe(1);
  } finally { vi.unstubAllGlobals(); }
});

// Removing the post-GET ownership check would publish an obsolete session.
test('pointer change during saved-session GET preserves the other page and rejects stale restoration', async () => {
  saveLastSession({ ...target, sessionId: 'owned' });
  const slow = deferred<ApiJsonResponse>(), request = vi.fn<(path: string, init?: RequestInit) => Promise<ApiJsonResponse>>(() => slow.promise);
  const game = new GameController(target, { request });
  const restoring = game.initialize();
  const other = { soupId: 'other', level: '', sessionId: 'other-owned' };
  saveLastSession(other);
  slow.resolve(response(session));
  await restoring;
  expect(game.getSnapshot()).toMatchObject({ phase: 'error', session: null, error: { category: 'conflict' } });
  expect(getLastSession()).toEqual(other);
  expect(readPending(target)).toBeNull();
  expect(request.mock.calls.map(args => args[0])).toEqual(['/api/session/owned']);
  game.dispose();
});

// Removing the in-flight gate would send the same creation twice on sync.
test('synchronizing during initialization sends no second creation and keeps its durable UUID', async () => {
  const slow = deferred<ApiJsonResponse>(), request = vi.fn<(path: string, init?: RequestInit) => Promise<ApiJsonResponse>>(() => slow.promise);
  const game = new GameController(target, { request, newId: () => requestId });
  const initializing = game.initialize();
  expect(readPending(target)).toEqual(creation);
  await game.synchronize();
  expect(request).toHaveBeenCalledTimes(1);
  expect(JSON.parse(String(request.mock.calls[0][1]?.body))).toEqual({ ...target, requestId });
  slow.resolve(response({ requestId, sessionId: 'owned', soupTitle: 'Public', soupSurface: 'Public story', questionLimit: 3, unlocks: null }));
  await initializing;
  expect(game.getSnapshot().phase).toBe('playing');
  expect(readPending(target)).toBeNull();
  expect(getLastSession()).toEqual({ ...target, sessionId: 'owned' });
  expect(request).toHaveBeenCalledTimes(1);
  game.dispose();
});

// Accepting a DTO with the wrong HTTP status could clear an unconfirmed ask.
test.each([
  { name: 'reserved with HTTP200', status: 200, body: { sessionId: 'owned', requestId, turnId: 'turn-owned', state: 'reserved', code: 'turn_in_progress', detail: '处理中' } },
  { name: 'completed answer with HTTP503', status: 503, body: { sessionId: 'owned', requestId, turnId: 'turn-owned', state: 'completed', kind: 'answer', reply: '是', remaining: 2,
    isFreeReminder: false, isWin: false, isReveal: false, isGiveup: false, limitReached: false } },
])('recovery rejects $name without removing the original question', async ({ body, status }) => {
  writePending(ask);
  const request = vi.fn<(path: string, init?: RequestInit) => Promise<ApiJsonResponse>>(async () => response(body, status));
  const game = new GameController(target, { request });
  await game.initialize();
  expect(game.getSnapshot()).toMatchObject({ phase: 'error', session: null, pending: ask, error: { category: 'protocol' } });
  expect(readPending(target)).toEqual(ask);
  expect(getLastSession()).toBeNull();
  expect(request.mock.calls.map(args => args[0])).toEqual([`/api/session/owned/turns/${requestId}`]);
  game.dispose();
});

// Trusting only evaluate's DTO would show a score never saved to the session.
test('successful reveal response cannot end a canonical session that is still playing', async () => {
  writePending(reveal);
  const request = vi.fn(async (path: string) => response(path === '/api/evaluate' ? evaluation : session));
  const game = new GameController(target, { request });
  await game.initialize();
  expect(game.getSnapshot()).toMatchObject({ phase: 'error', session: { status: 'playing', evaluation: null }, pending: reveal, error: { category: 'protocol' } });
  expect(readPending(target)).toEqual(reveal);
  expect(localStorage.getItem('played_soups')).toBeNull();
  expect(request.mock.calls.map(args => args[0])).toEqual(['/api/session/owned', '/api/evaluate', '/api/session/owned']);
  game.dispose();
});

// Dropping reveal's non-OK check would pretend an HTTP503 response completed it.
test('HTTP503 during reveal preserves its journal for later synchronization', async () => {
  writePending(reveal);
  const request = vi.fn(async (path: string) => path === '/api/evaluate' ? response({ detail: 'Synthetic busy' }, 503) : response(session));
  const game = new GameController(target, { request });
  await game.initialize();
  expect(game.getSnapshot()).toMatchObject({ phase: 'error', pending: reveal, error: { category: 'service' } });
  expect(game.getSnapshot().session?.evaluation).toBeNull();
  expect(readPending(target)).toEqual(reveal);
  expect(localStorage.getItem('played_soups')).toBeNull();
  expect(request.mock.calls.map(args => args[0])).toEqual(['/api/session/owned', '/api/evaluate']);
  game.dispose();
});
