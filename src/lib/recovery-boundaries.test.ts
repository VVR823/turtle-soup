import { beforeEach, expect, test, vi } from 'vitest';
import { apiJson, getLastSession, saveLastSession, type ApiJsonResponse } from './api';
import { GameController } from './game-controller';
import { GameStorageError, readPending, writePending } from './game-journal';

const target = { soupId: 'synthetic', level: 'xuermu' };
const requestId = '29ab9f58-d899-41dd-a2ab-8e7b3667c9f1';
const creation = { ...target, kind: 'create' as const, requestId };
const response = (body: unknown, status = 200): ApiJsonResponse => ({ body, status, ok: status >= 200 && status < 300, headers: new Headers() });
const session = () => ({ sessionId: 'owned', soupId: target.soupId, soupTitle: 'Public', soupSurface: 'Public story',
  questionLimit: 3, questionsAsked: 1, remaining: 2, unlocks: null, status: 'playing', messages: [], evaluation: null });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(finish => { resolve = finish; });
  return { promise, resolve };
}
beforeEach(() => localStorage.clear());

test('late canonical GET after a committed answer cannot clear recovery state on another page', async () => {
  saveLastSession({ ...target, sessionId: 'owned' });
  const reading = deferred<void>(), slow = deferred<ApiJsonResponse>();
  let reads = 0;
  const request = vi.fn(async (_path: string, init?: RequestInit) => {
    if (init?.method === 'POST') return response({ sessionId: 'owned', requestId, turnId: 'turn-owned',
      state: 'completed', kind: 'answer', reply: '是', remaining: 2, isFreeReminder: false,
      isWin: false, isReveal: false, isGiveup: false, limitReached: false });
    if (++reads === 1) return response(session());
    reading.resolve(undefined);
    return slow.promise;
  });
  const game = new GameController(target, { newId: () => requestId, request });
  await game.initialize();
  const pending = game.ask('合成问题吗');
  await reading.promise;
  const original = readPending(target);
  game.dispose();
  const before = game.getSnapshot();
  const other = { sessionId: 'other-owned', soupId: 'other', level: '' };
  saveLastSession(other);
  slow.resolve(response(session()));
  await pending;
  expect(game.getSnapshot()).toBe(before);
  expect(getLastSession()).toEqual(other);
  expect(readPending(target)).toEqual(original);
  expect(original).toMatchObject({ kind: 'ask', requestId, question: '合成问题吗' });
  expect(request).toHaveBeenCalledTimes(3);
});

test('valid JSON with malformed or cross-route operation is preserved and cannot be silently overwritten', () => {
  writePending(creation);
  const key = localStorage.key(0)!;
  for (const operation of [null, [], { ...creation, soupId: '' }, { ...creation, level: 0 },
    { ...creation, serverAuthority: true }, { ...creation, soupId: 'other' }]) {
    const raw = JSON.stringify({ version: 1, operation });
    localStorage.setItem(key, raw);
    expect(() => readPending(target)).toThrow(GameStorageError);
    expect(() => writePending(creation)).toThrow(GameStorageError);
    expect(localStorage.getItem(key)).toBe(raw);
  }
});

test('browser UUID generation throwing blocks creation before any request or saved intent', async () => {
  vi.stubGlobal('crypto', { randomUUID: () => { throw new DOMException('Synthetic unavailable crypto', 'SecurityError'); } });
  const request = vi.fn();
  const game = new GameController(target, { request });
  await game.initialize();
  expect(game.getSnapshot().error?.category).toBe('storage');
  expect(request).not.toHaveBeenCalled();
  expect(localStorage.length).toBe(0);
});

test('unstructured HTTP500 with invalid Retry-After preserves unknown submission metadata', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('Synthetic gateway failure', {
    status: 500, headers: { 'Retry-After': 'not-a-time' },
  })));
  await expect(apiJson('/api/chat', { method: 'POST', body: '{}' })).rejects.toMatchObject({
    status: 500, code: null, requestId: null, retryAfterSeconds: null, message: '请求失败（500），请保留原对局并重试',
  });
});
