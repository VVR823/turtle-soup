import { expect, test, vi } from 'vitest';
import { getLastSession, saveLastSession, type ApiJsonResponse } from './api';
import { GameController } from './game-controller';
import { readPending, writePending } from './game-journal';

const target = { soupId: 'synthetic', level: 'xuermu' };
const requestId = '29ab9f58-d899-41dd-a2ab-8e7b3667c9f1';
const pointer = { ...target, sessionId: 'owned' };
const creation = { ...target, kind: 'create' as const, requestId };
const ask = { ...target, kind: 'ask' as const, requestId, sessionId: 'owned', question: '合成问题吗' };
const reveal = { ...target, kind: 'reveal' as const, sessionId: 'owned' };
const evaluation = { completion: 0, verifiedCoverage: 0, scoreVersion: 'coverage-v1', reconstructionScore: null,
  evaluation: 'Synthetic', keyPointsCovered: [], keyPointsMissing: ['A'], bottom: 'Synthetic truth', plotProgress: 100 };
const session = { ...pointer, soupTitle: 'Public', soupSurface: 'Public story', questionLimit: 3,
  questionsAsked: 1, remaining: 2, unlocks: null, status: 'playing', messages: [], evaluation: null };
const response = (body: unknown, status = 200): ApiJsonResponse =>
  ({ body, status, ok: status >= 200 && status < 300, headers: new Headers() });
function refusingJournal() {
  // Inject failure at the durable compare-and-clear boundary, without mutating controller internals.
  return { read: readPending, write: writePending, clear: vi.fn(() => false) };
}

test('creation journal clear conflict retains the verified pointer and original creation UUID', async () => {
  const journal = refusingJournal();
  const request = vi.fn(async () => response({ requestId, sessionId: 'owned', soupTitle: 'Public',
    soupSurface: 'Public story', questionLimit: 3, unlocks: null }));
  const game = new GameController(target, { request, journal, newId: () => requestId });
  await game.initialize();
  expect(game.getSnapshot()).toMatchObject({ phase: 'error', error: { category: 'conflict' } });
  expect(getLastSession()).toEqual(pointer);
  expect(readPending(target)).toEqual(creation);
  expect(request).toHaveBeenCalledTimes(1);
  game.dispose();
});

test('completed question with journal clear conflict retains its original request without repost', async () => {
  saveLastSession(pointer); writePending(ask);
  const journal = refusingJournal();
  const request = vi.fn(async (path: string) => response(path.includes('/turns/')
    ? { sessionId: 'owned', requestId, turnId: 'turn-owned', state: 'completed', kind: 'answer', reply: '是',
      remaining: 2, isFreeReminder: false, isWin: false, isReveal: false, isGiveup: false, limitReached: false }
    : session));
  const game = new GameController(target, { request, journal });
  await game.initialize();
  expect(game.getSnapshot()).toMatchObject({ phase: 'error', error: { category: 'conflict' } });
  expect(readPending(target)).toEqual(ask);
  expect(getLastSession()).toEqual(pointer);
  expect(request.mock.calls.map(([path]) => path)).toEqual([`/api/session/owned/turns/${requestId}`, '/api/session/owned']);
  game.dispose();
});

test('saved evaluation with journal clear conflict retains recovery state without another reveal', async () => {
  saveLastSession(pointer); writePending(reveal);
  const journal = refusingJournal();
  const request = vi.fn(async () => response({ ...session, status: 'given_up', evaluation }));
  const game = new GameController(target, { request, journal });
  await game.initialize();
  expect(game.getSnapshot()).toMatchObject({ phase: 'error', error: { category: 'conflict' } });
  expect(readPending(target)).toEqual(reveal);
  expect(getLastSession()).toEqual(pointer);
  expect(request.mock.calls).toEqual([['/api/session/owned', expect.any(Object)]]);
  game.dispose();
});

test('confirmed restart cannot discard a pending creation when durable clear is refused', async () => {
  writePending(creation);
  const journal = refusingJournal();
  const request = vi.fn(async () => response({}, 503));
  const game = new GameController(target, { request, journal });
  await game.initialize();
  expect(readPending(target)).toEqual(creation);
  await game.restart(true);
  expect(game.getSnapshot()).toMatchObject({ phase: 'error', pending: creation, error: { category: 'conflict' } });
  expect(readPending(target)).toEqual(creation);
  expect(getLastSession()).toBeNull();
  expect(request).toHaveBeenCalledTimes(1);
  game.dispose();
});

test('late reveal rejection after disposal cannot overwrite another route or its saved pointer', async () => {
  saveLastSession(pointer);
  let reject!: (error: Error) => void;
  const slow = new Promise<ApiJsonResponse>((_, fail) => { reject = fail; });
  const request = vi.fn(async (_path: string, init?: RequestInit) => init?.method === 'POST' ? slow : response(session));
  const game = new GameController(target, { request });
  await game.initialize();
  const revealing = game.reveal();
  expect(readPending(target)).toEqual(reveal);
  game.dispose();
  const snapshot = game.getSnapshot();
  const other = { soupId: 'other', level: '', sessionId: 'other-owned' };
  saveLastSession(other);
  reject(new Error('Synthetic late reveal failure'));
  await revealing;
  expect(game.getSnapshot()).toBe(snapshot);
  expect(readPending(target)).toEqual(reveal);
  expect(getLastSession()).toEqual(other);
  expect(request).toHaveBeenCalledTimes(2);
});

test('late completed question after disposal cannot read or overwrite the next route', async () => {
  saveLastSession(pointer);
  let resolve!: (value: ApiJsonResponse) => void;
  const slow = new Promise<ApiJsonResponse>(done => { resolve = done; });
  const request = vi.fn(async (_path: string, init?: RequestInit) => init?.method === 'POST' ? slow : response(session));
  const game = new GameController(target, { request, newId: () => requestId });
  await game.initialize();
  const asking = game.ask(ask.question);
  expect(readPending(target)).toEqual(ask);
  game.dispose();
  const snapshot = game.getSnapshot();
  const other = { soupId: 'other', level: '', sessionId: 'other-owned' };
  saveLastSession(other);
  resolve(response({ sessionId: 'owned', requestId, turnId: 'turn-owned', state: 'completed', kind: 'answer', reply: '是',
    remaining: 2, isFreeReminder: false, isWin: false, isReveal: false, isGiveup: false, limitReached: false }));
  await asking;
  expect(game.getSnapshot()).toBe(snapshot);
  expect(getLastSession()).toEqual(other);
  expect(readPending(target)).toEqual(ask);
  expect(request).toHaveBeenCalledTimes(2);
});

test('a recovery sleep resolving after disposal cannot start another poll or clear its pending UUID', async () => {
  saveLastSession(pointer); writePending(ask);
  let wake!: () => void;
  const sleeping = new Promise<void>(done => { wake = done; });
  const sleep = vi.fn(() => sleeping);
  const request = vi.fn(async (path: string) => path.includes('/turns/')
    ? response({ sessionId: 'owned', requestId, turnId: 'turn-owned', state: 'reserved', code: 'turn_in_progress', detail: '处理中' }, 202)
    : response(session));
  const game = new GameController(target, { request, sleep });
  const recovering = game.initialize();
  await vi.waitFor(() => expect(sleep).toHaveBeenCalledTimes(1));
  game.dispose();
  const snapshot = game.getSnapshot();
  wake(); await recovering;
  expect(game.getSnapshot()).toBe(snapshot);
  expect(request).toHaveBeenCalledTimes(2);
  expect(readPending(target)).toEqual(ask);
  expect(getLastSession()).toEqual(pointer);
});

test('rule suspension discovered after a completed turn retains its UUID until canonical resume', async () => {
  saveLastSession(pointer); writePending(ask);
  let suspended = true;
  const request = vi.fn(async (path: string) => response(path.includes('/turns/')
    ? { sessionId: 'owned', requestId, turnId: 'turn-owned', state: 'completed', kind: 'answer', reply: '是',
      remaining: 2, isFreeReminder: false, isWin: false, isReveal: false, isGiveup: false, limitReached: false }
    : { ...session, ruleSuspended: suspended }));
  const game = new GameController(target, { request });
  await game.initialize();
  expect(game.getSnapshot()).toMatchObject({ phase: 'playing', pending: ask, error: { category: 'conflict' } });
  expect(readPending(target)).toEqual(ask);
  expect(getLastSession()).toEqual(pointer);
  suspended = false;
  await game.synchronize();
  expect(game.getSnapshot()).toMatchObject({ phase: 'playing', pending: null, error: null });
  expect(readPending(target)).toBeNull();
  expect(request.mock.calls.map(([path]) => path)).toEqual([
    `/api/session/owned/turns/${requestId}`, '/api/session/owned',
    `/api/session/owned/turns/${requestId}`, '/api/session/owned',
  ]);
  game.dispose();
});

test('missing question in an ended session cannot clear recovery state when durable clear conflicts', async () => {
  saveLastSession(pointer); writePending(ask);
  const journal = refusingJournal();
  const request = vi.fn(async (path: string) => path.includes('/turns/')
    ? response({}, 404) : response({ ...session, status: 'given_up', evaluation }));
  const game = new GameController(target, { request, journal });
  await game.initialize();
  expect(game.getSnapshot()).toMatchObject({ phase: 'error', error: { category: 'conflict' } });
  expect(readPending(target)).toEqual(ask);
  expect(getLastSession()).toEqual(pointer);
  expect(request).toHaveBeenCalledTimes(2);
  game.dispose();
});
