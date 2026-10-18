import { expect, test } from 'vitest';
import { getLastSession, saveLastSession, type ApiJsonResponse } from './api';
import { decodeSession } from './game-contract';
import { GameController } from './game-controller';
import { readPending, writePending } from './game-journal';

const target = { soupId: 'synthetic', level: 'xuermu' };
const requestId = 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa';
const evaluation = { completion: 50, verifiedCoverage: 50, scoreVersion: 'coverage-v1', reconstructionScore: null,
  plotProgress: 80, evaluation: 'Saved', keyPointsCovered: [], keyPointsMissing: [], bottom: 'Saved truth' };
function session(change: Record<string, unknown> = {}) {
  return { ...target, sessionId: 'owned', soupTitle: 'T', soupSurface: 'S', questionLimit: 3, questionsAsked: 1,
    remaining: 2, unlocks: null, status: 'playing', evaluation: null, messages: [{ role: 'user', content: 'Old question?', timestamp: 1 },
      { role: 'host', content: '是', timestamp: 2 }], ...change };
}
const response = (body: unknown, status = 200): ApiJsonResponse => ({ body, status, ok: status >= 200 && status < 300, headers: new Headers() });

test('old snapshots default false but actual boolean suspension is retained', () => {
  expect(decodeSession(session(), 'owned', 'synthetic').ruleSuspended).toBe(false);
  expect(decodeSession(session({ ruleSuspended: true }), 'owned', 'synthetic').ruleSuspended).toBe(true);
});
test.each([null, 'true', 1])('provided nonboolean suspension %s is not ignored', flag => {
  expect(() => decodeSession(session({ ruleSuspended: flag }), 'owned', 'synthetic')).toThrow();
});

test('a stopped playing game keeps history/pointer and sends no new ask or reveal', async () => {
  saveLastSession({ ...target, sessionId: 'owned' }); const calls: Array<{ path: string; method?: string }> = [];
  const game = new GameController(target, { request: async (path, init) => {
    calls.push({ path, method: init?.method }); return response(session({ ruleSuspended: true }));
  } });
  await game.initialize(); await game.ask('New question?'); await game.reveal();
  expect(calls.filter(call => call.method === 'POST')).toHaveLength(0);
  expect(game.getSnapshot().session?.messages).toHaveLength(2);
  expect(game.getSnapshot().session?.ruleSuspended).toBe(true);
  expect(readPending(target)).toBeNull(); expect(getLastSession()?.sessionId).toBe('owned');
});

test.each([{ questionsAsked: 3, remaining: 0 }, { status: 'solved' }])('stopped %j does not auto-reveal', async changed => {
  saveLastSession({ ...target, sessionId: 'owned' }); const methods: Array<string | undefined> = [];
  const game = new GameController(target, { request: async (_path, init) => { methods.push(init?.method); return response(session({ ruleSuspended: true, ...changed })); } });
  await game.initialize(); expect(methods.filter(method => method === 'POST')).toHaveLength(0);
  expect(readPending(target)).toBeNull(); expect(game.getSnapshot().session?.ruleSuspended).toBe(true);
});

test('missing pending ask is not reposted while paused and its original UUID survives', async () => {
  const operation = { ...target, kind: 'ask' as const, sessionId: 'owned', question: 'Original question?', requestId };
  saveLastSession({ ...target, sessionId: 'owned' }); writePending(operation); const methods: Array<string | undefined> = [];
  const game = new GameController(target, { request: async (path, init) => {
    methods.push(init?.method); return path.includes('/turns/') ? response({}, 404) : response(session({ ruleSuspended: true }));
  } });
  await game.initialize(); expect(methods.filter(method => method === 'POST')).toHaveLength(0);
  expect(readPending(target)).toEqual(operation); expect(game.getSnapshot().pending).toEqual(operation);
  expect(game.getSnapshot().session?.ruleSuspended).toBe(true); expect(game.getSnapshot().session?.messages).toHaveLength(2);
});

test('pending reveal remains durable until explicit unsuspend and manual synchronize', async () => {
  const operation = { ...target, kind: 'reveal' as const, sessionId: 'owned' };
  saveLastSession({ ...target, sessionId: 'owned' }); writePending(operation); let paused = true, ended = false;
  const methods: Array<string | undefined> = [];
  const game = new GameController(target, { request: async (_path, init) => {
    methods.push(init?.method); if (init?.method === 'POST') { ended = true; return response(evaluation); }
    return response(session({ ruleSuspended: paused, ...(ended ? { status: 'given_up', evaluation } : {}) }));
  } });
  await game.initialize(); expect(methods.filter(method => method === 'POST')).toHaveLength(0);
  expect(readPending(target)).toEqual(operation); paused = false; await game.synchronize();
  expect(game.getSnapshot().phase).toBe('ended'); expect(game.getSnapshot().session?.evaluation?.bottom).toBe('Saved truth');
  expect(readPending(target)).toBeNull(); expect(methods.filter(method => method === 'POST')).toHaveLength(1);
});

test('saved ended evaluation is still displayed on a stopped version', async () => {
  saveLastSession({ ...target, sessionId: 'owned' });
  const game = new GameController(target, { request: async () => response(session({ ruleSuspended: true, status: 'given_up', evaluation })) });
  await game.initialize(); expect(game.getSnapshot().phase).toBe('ended');
  expect(game.getSnapshot().session?.evaluation?.bottom).toBe('Saved truth');
});


test('a reserved pending request on a stopped version stops polling and shows original history', async () => {
  const operation = { ...target, kind: 'ask' as const, sessionId: 'owned', question: 'Original?', requestId };
  saveLastSession({ ...target, sessionId: 'owned' }); writePending(operation); let queries = 0;
  const game = new GameController(target, { sleep: async () => {}, request: async path => {
    if (path.includes('/turns/')) { queries++; return response({ sessionId: 'owned', requestId, turnId: 'turn',
      state: 'reserved', code: 'turn_in_progress', detail: 'Reserved' }, 202); }
    return response(session({ ruleSuspended: true }));
  } });
  await game.initialize(); expect(queries).toBe(1);
  expect(game.getSnapshot().session?.messages).toHaveLength(2); expect(readPending(target)).toEqual(operation);
  expect(game.getSnapshot().session?.ruleSuspended).toBe(true);
});
