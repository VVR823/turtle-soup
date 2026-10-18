import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiAuthError, type ApiJsonResponse, saveLastSession, getLastSession } from './api';
import { readPending, writePending } from './game-journal';
import { GameController } from './game-controller';

const target = { soupId: 'synthetic', level: 'xuermu' };
const evaluation = { completion: 0, verifiedCoverage: 0, scoreVersion: 'coverage-v1', reconstructionScore: null,
  evaluation: 'Synthetic', keyPointsCovered: [], keyPointsMissing: ['A'], bottom: 'Synthetic truth', plotProgress: 100 };
function response(body: unknown, status = 200): ApiJsonResponse { return { body, status, ok: status >= 200 && status < 300, headers: new Headers() }; }
function created(requestId: string, title = 'Public', sessionId = 'owned') {
  return { requestId, sessionId, soupTitle: title, soupSurface: 'Public story', questionLimit: 3, unlocks: null };
}
function session(status = 'playing') {
  return { sessionId: 'owned', soupId: 'synthetic', soupTitle: 'Public', soupSurface: 'Public story', questionLimit: 3,
    questionsAsked: 1, remaining: 2, unlocks: null, status, messages: [], evaluation: status === 'playing' ? null : evaluation };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(finish => { resolve = finish; });
  return { promise, resolve };
}
beforeEach(() => localStorage.clear());

describe('route-keyed recovery independent of the last visited game', () => {
  const requestId = '29ab9f58-d899-41dd-a2ab-8e7b3667c9f1';
  const operation = { ...target, kind: 'ask' as const, sessionId: 'owned', question: '合成问题吗', requestId };
  const foreign = { soupId: 'other', level: 'baozi', sessionId: 'other-owned' };
  const completed = { sessionId: 'owned', requestId, turnId: 'turn-owned', state: 'completed', kind: 'answer',
    reply: '是', remaining: 2, isFreeReminder: false, isWin: false, isReveal: false, isGiveup: false, limitReached: false };
  it('A lost committed answer survives creating B and returning to A, with GET-only recovery', async () => {
    saveLastSession({ ...target, sessionId: 'owned' });
    const first = new GameController(target, { newId: () => requestId, request: async (_path, init) => {
      if (init?.method === 'POST') throw new TypeError('Synthetic committed reply lost');
      return response(session());
    } });
    await first.initialize(); await first.ask(operation.question); first.dispose();
    const next = new GameController({ soupId: foreign.soupId, level: foreign.level }, { request: async (_path, init) => response(created(JSON.parse(String(init?.body)).requestId, 'B', foreign.sessionId)) });
    await next.initialize(); next.dispose(); expect(getLastSession()).toEqual(foreign);
    const request = vi.fn(async (path: string) => response(path.includes('/turns/') ? completed : session()));
    const returned = new GameController(target, { request }); await returned.initialize();
    expect(request.mock.calls.map(([path]) => path)).toEqual([`/api/session/owned/turns/${requestId}`, '/api/session/owned']);
    expect(returned.getSnapshot().phase).toBe('playing'); expect(readPending(target)).toBeNull();
    expect(getLastSession()).toEqual({ ...target, sessionId: 'owned' });
  });
  it('a valid route journal can recover when the global last pointer is absent', async () => {
    writePending(operation);
    const request = vi.fn(async (path: string) => response(path.includes('/turns/') ? completed : session()));
    const game = new GameController(target, { request }); await game.initialize();
    expect(game.getSnapshot().phase).toBe('playing'); expect(request).toHaveBeenCalledTimes(2);
    expect(getLastSession()?.sessionId).toBe('owned'); expect(readPending(target)).toBeNull();
  });
  it('returning to a lost reveal restores the exact frozen result without another POST', async () => {
    saveLastSession(foreign); writePending({ ...target, kind: 'reveal', sessionId: 'owned' });
    const request = vi.fn(async (path: string) => { expect(path).toBe('/api/session/owned'); return response(session('given_up')); });
    const game = new GameController(target, { request }); await game.initialize();
    expect(game.getSnapshot().phase).toBe('ended'); expect(game.getSnapshot().session?.evaluation).toEqual(evaluation);
    expect(getLastSession()?.sessionId).toBe('owned'); expect(request).toHaveBeenCalledTimes(1); expect(readPending(target)).toBeNull();
  });
  it('missing original turn reclaims only a validated session and reposts the identical UUID and body', async () => {
    saveLastSession(foreign); writePending(operation);
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (path.includes('/turns/')) return response({}, 404);
      if (init?.method === 'POST') {
        expect(getLastSession()?.sessionId).toBe('owned');
        expect(JSON.parse(String(init.body))).toEqual({ sessionId: 'owned', soupId: target.soupId, question: operation.question, requestId });
        return response(completed);
      }
      return response(session());
    });
    const game = new GameController(target, { request }); await game.initialize();
    expect(request.mock.calls.map(([path]) => path)).toEqual([`/api/session/owned/turns/${requestId}`, '/api/session/owned', '/api/chat', '/api/session/owned']);
    expect(game.getSnapshot().phase).toBe('playing'); expect(readPending(target)).toBeNull();
  });
  it('failed reclaim storage write keeps the foreign pointer and original journal', async () => {
    saveLastSession(foreign); writePending(operation);
    const original = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key, value) {
      if (key === 'last_session') throw new Error('Synthetic pointer unavailable');
      original.call(this, key, value);
    });
    const request = vi.fn(async (path: string) => response(path.includes('/turns/') ? completed : session()));
    const game = new GameController(target, { request }); await game.initialize();
    expect(game.getSnapshot().error?.category).toBe('storage'); expect(request).toHaveBeenCalledTimes(2);
    expect(getLastSession()).toEqual(foreign); expect(readPending(target)).toEqual(operation);
  });
  it.each(['turn', 'session'])('an intervening pointer change during %s GET still fences all writes', async delayed => {
    saveLastSession({ ...target, sessionId: 'owned' }); writePending(operation);
    const slow = deferred<ApiJsonResponse>();
    const request = vi.fn(async (path: string) => {
      if (path.includes('/turns/')) return delayed === 'turn' ? slow.promise : response(completed);
      return delayed === 'session' ? slow.promise : response(session());
    });
    const game = new GameController(target, { request }); const initializing = game.initialize();
    if (delayed === 'session') await Promise.resolve();
    saveLastSession(foreign); slow.resolve(response(delayed === 'turn' ? completed : session())); await initializing;
    expect(game.getSnapshot().error?.category).toBe('conflict'); expect(getLastSession()).toEqual(foreign);
    expect(readPending(target)).toEqual(operation); expect(game.getSnapshot().session).toBeNull();
  });
});

describe('terminal transition and explicit restart', () => {
  it.each(['given_up', 'solved', 'solved-without-evaluation'])('missing turn reconciles a verified %s session without a question POST or charge claim', async mode => {
    saveLastSession({ ...target, sessionId: 'owned' });
    const requestId = '29ab9f58-d899-41dd-a2ab-8e7b3667c9f1';
    writePending({ ...target, kind: 'ask', sessionId: 'owned', question: '合成问题吗', requestId });
    let reads = 0;
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (path.includes('/turns/')) return response({ code: 'turn_not_found' }, 404);
      if (path === '/api/evaluate') {
        expect(mode).toBe('solved-without-evaluation');
        expect(JSON.parse(String(init?.body))).toEqual({ sessionId: 'owned' });
        expect(readPending(target)).toMatchObject({ kind: 'reveal', sessionId: 'owned' });
        return response(evaluation);
      }
      return response(mode === 'solved-without-evaluation' && reads++ === 0 ? { ...session('solved'), evaluation: null }
        : session(mode === 'given_up' ? 'given_up' : 'solved'));
    });
    const game = new GameController(target, { request }); await game.initialize();
    expect(game.getSnapshot().phase).toBe('ended'); expect(game.getSnapshot().session?.evaluation).toEqual(evaluation);
    expect(game.getSnapshot().session?.status).toBe(mode === 'given_up' ? 'given_up' : 'solved');
    expect(request.mock.calls.filter(([path]) => path === '/api/chat')).toHaveLength(0);
    expect(request.mock.calls.filter(([path]) => path === '/api/evaluate')).toHaveLength(mode === 'solved-without-evaluation' ? 1 : 0);
    expect(game.getSnapshot().error?.message || '').not.toContain('没有扣次数');
    expect(readPending(target)).toBeNull(); expect(getLastSession()?.sessionId).toBe('owned');
  });
  it.each(['ask', 'reveal'] as const)('disposed controller cannot persist a new %s intent before reactivation', async action => {
    saveLastSession({ ...target, sessionId: 'owned' }); const request = vi.fn(async () => response(session()));
    const game = new GameController(target, { request }); await game.initialize(); game.dispose();
    if (action === 'ask') await game.ask('合成问题吗'); else await game.reveal();
    expect(readPending(target)).toBeNull(); expect(request).toHaveBeenCalledTimes(1);
  });
  it('late restoration after disposal cannot publish a session or write result markers', async () => {
    saveLastSession({ ...target, sessionId: 'owned' }); const slow = deferred<ApiJsonResponse>();
    const game = new GameController(target, { request: async () => slow.promise }); const first = game.initialize();
    game.dispose(); const before = game.getSnapshot(); slow.resolve(response(session('given_up'))); await first;
    expect(game.getSnapshot()).toBe(before); expect(localStorage.getItem('played_soups')).toBeNull();
  });
  it.each(['solved', 'zero'])('confirmed %s question completes through the same exclusive reveal path', async mode => {
    saveLastSession({ ...target, sessionId: 'owned' }); let reads = 0;
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (path === '/api/evaluate') return response(evaluation);
      if (init?.method === 'POST') {
        const requestId = JSON.parse(String(init.body)).requestId;
        return response({ sessionId: 'owned', requestId, turnId: 'turn-owned', state: 'completed', kind: mode === 'solved' ? 'win' : 'answer',
          reply: '合成回答', remaining: mode === 'zero' ? 0 : 1, isFreeReminder: false, isWin: mode === 'solved',
          isReveal: mode === 'solved', isGiveup: false, limitReached: false });
      }
      const step = reads++;
      return response(step === 0 ? session() : step === 1
        ? { ...session(), status: mode === 'solved' ? 'solved' : 'playing', evaluation: null,
          questionsAsked: mode === 'zero' ? 3 : 2, remaining: mode === 'zero' ? 0 : 1 }
        : { ...session(mode === 'solved' ? 'solved' : 'given_up'), questionsAsked: mode === 'zero' ? 3 : 2, remaining: mode === 'zero' ? 0 : 1 });
    });
    const game = new GameController(target, { request }); await game.initialize(); await game.ask('合成问题吗');
    expect(game.getSnapshot().phase).toBe('ended'); expect(game.getSnapshot().session?.evaluation).toEqual(evaluation);
    expect(request.mock.calls.filter(args => args[0] === '/api/evaluate')).toHaveLength(1);
    expect(readPending(target)).toBeNull();
  });
  it('refresh of exhausted playing session completes rather than enabling an impossible next question', async () => {
    saveLastSession({ ...target, sessionId: 'owned' }); let reads = 0;
    const request = vi.fn(async (path: string) => path === '/api/evaluate' ? response(evaluation)
      : response({ ...session(reads++ === 0 ? 'playing' : 'given_up'), questionsAsked: 3, remaining: 0 }));
    const game = new GameController(target, { request }); await game.initialize();
    expect(game.getSnapshot().phase).toBe('ended'); expect(readPending(target)).toBeNull();
  });
  it('restart is explicit, mints one new UUID and retains the previous pointer until the new creation succeeds', async () => {
    const old = { ...target, sessionId: 'owned' }; saveLastSession(old); const slow = deferred<ApiJsonResponse>(); let id = '';
    const request = vi.fn(async (_path: string, init?: RequestInit) => {
      if (init?.method === 'POST') { id = JSON.parse(String(init.body)).requestId; expect(getLastSession()).toEqual(old); return slow.promise; }
      return response(session('given_up'));
    });
    const game = new GameController(target, { request }); await game.initialize(); const first = game.restart(); await game.restart();
    expect(readPending(target)).toMatchObject({ kind: 'create', requestId: id });
    slow.resolve(response(created(id, 'Restarted', 'new-owned'))); await first;
    expect(getLastSession()?.sessionId).toBe('new-owned'); expect(game.getSnapshot().phase).toBe('playing');
    expect(request.mock.calls.filter(args => args[1]?.method === 'POST')).toHaveLength(1);
  });
  it('unknown pending operation cannot be abandoned by an ordinary restart, only an explicitly confirmed action', async () => {
    saveLastSession({ ...target, sessionId: 'owned' }); const askId = '29ab9f58-d899-41dd-a2ab-8e7b3667c9f1';
    writePending({ ...target, kind: 'ask', sessionId: 'owned', question: '合成问题吗', requestId: askId });
    const request = vi.fn(async (_path: string, init?: RequestInit) => init?.method === 'POST'
      ? response(created(JSON.parse(String(init.body)).requestId, 'Restarted', 'new-owned')) : response({}, 503));
    const game = new GameController(target, { request }); await game.initialize(); await game.restart();
    expect(readPending(target)).toMatchObject({ requestId: askId }); expect(request.mock.calls.filter(args => args[1]?.method === 'POST')).toHaveLength(0);
    await game.restart(true);
    expect(getLastSession()?.sessionId).toBe('new-owned'); expect(readPending(target)).toBeNull();
  });
  it('another tab changing the pointer prevents restart from replacing the foreign game', async () => {
    saveLastSession({ ...target, sessionId: 'owned' }); const request = vi.fn(async () => response(session()));
    const game = new GameController(target, { request }); await game.initialize();
    const foreign = { sessionId: 'foreign', soupId: 'other', level: '' }; saveLastSession(foreign); await game.restart();
    expect(getLastSession()).toEqual(foreign); expect(request).toHaveBeenCalledTimes(1);
    expect(game.getSnapshot().error?.category).toBe('conflict');
  });
  it('404 unknown turn with missing original session never re-posts or clears the question', async () => {
    saveLastSession({ ...target, sessionId: 'owned' }); const requestId = '29ab9f58-d899-41dd-a2ab-8e7b3667c9f1';
    writePending({ ...target, kind: 'ask', sessionId: 'owned', question: '合成问题吗', requestId });
    const request = vi.fn(async () => response({}, 404)); const game = new GameController(target, { request }); await game.initialize();
    expect(request).toHaveBeenCalledTimes(2); expect(readPending(target)).toMatchObject({ requestId });
    expect(game.getSnapshot().error?.category).toBe('missing');
  });
  it('invalid reveal DTO preserves the intent and never invents an ended result', async () => {
    saveLastSession({ ...target, sessionId: 'owned' });
    const request = vi.fn(async (path: string) => path === '/api/evaluate' ? response({ ...evaluation, completion: 100 }) : response(session()));
    const game = new GameController(target, { request }); await game.initialize(); await game.reveal();
    expect(game.getSnapshot().error?.category).toBe('protocol'); expect(readPending(target)?.kind).toBe('reveal');
    expect(game.getSnapshot().session?.evaluation).toBeNull();
  });
});

describe('owned reveal recovery', () => {
  it('a browser marker write failure keeps the saved result visible with a storage warning', async () => {
    saveLastSession({ ...target, sessionId: 'owned' });
    const original = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key, value) {
      if (key === 'played_soups') throw new Error('Synthetic marker storage failure');
      original.call(this, key, value);
    });
    const game = new GameController(target, { request: async () => response(session('given_up')) }); await game.initialize();
    expect(game.getSnapshot().phase).toBe('ended'); expect(game.getSnapshot().session?.evaluation).toEqual(evaluation);
    expect(game.getSnapshot().error?.category).toBe('storage'); expect(getLastSession()?.sessionId).toBe('owned');
  });
  it('reveal requires a verified session and excludes a concurrent question or duplicate reveal', async () => {
    saveLastSession({ ...target, sessionId: 'owned' });
    const slow = deferred<ApiJsonResponse>(); let reads = 0;
    const request = vi.fn(async (path: string) => path === '/api/evaluate' ? slow.promise
      : response(reads++ === 0 ? session() : session('given_up')));
    const game = new GameController(target, { request });
    await game.reveal(); expect(request).not.toHaveBeenCalled();
    await game.initialize(); const first = game.reveal();
    expect(readPending(target)).toMatchObject({ kind: 'reveal', sessionId: 'owned' });
    await game.reveal(); await game.ask('合成问题吗');
    expect(request.mock.calls.map(args => args[0])).toEqual(['/api/session/owned', '/api/evaluate']);
    slow.resolve(response(evaluation)); await first;
    expect(game.getSnapshot().phase).toBe('ended');
    expect(game.getSnapshot().session?.evaluation).toEqual(evaluation);
    expect(getLastSession()?.sessionId).toBe('owned'); expect(readPending(target)).toBeNull();
  });
  it('lost reveal response retains the journal and restores the saved result by GET without a second POST', async () => {
    saveLastSession({ ...target, sessionId: 'owned' }); let reads = 0;
    const request = vi.fn(async (path: string) => {
      if (path === '/api/evaluate') throw new TypeError('Synthetic lost reveal after commit');
      return response(reads++ === 0 ? session() : session('given_up'));
    });
    const game = new GameController(target, { request }); await game.initialize(); await game.reveal();
    expect(readPending(target)?.kind).toBe('reveal'); expect(game.getSnapshot().phase).toBe('error');
    await game.synchronize();
    expect(game.getSnapshot().phase).toBe('ended'); expect(readPending(target)).toBeNull();
    expect(request.mock.calls.filter(args => args[0] === '/api/evaluate')).toHaveLength(1);
  });
  it('a solved session without a score evaluates once after persisting recovery, and cannot reopen as playing', async () => {
    saveLastSession({ ...target, sessionId: 'owned' }); let reads = 0;
    const request = vi.fn(async (path: string) => {
      if (path === '/api/evaluate') {
        expect(readPending(target)?.kind).toBe('reveal'); return response(evaluation);
      }
      return response(reads++ === 0 ? { ...session('solved'), evaluation: null } : session('solved'));
    });
    const game = new GameController(target, { request }); await game.initialize();
    expect(game.getSnapshot().phase).toBe('ended'); expect(game.getSnapshot().session?.evaluation).toEqual(evaluation);
    expect(request.mock.calls.filter(args => args[0] === '/api/evaluate')).toHaveLength(1);
    expect(readPending(target)).toBeNull();
  });
  it('refresh of pending reveal validates the original session before repeating a session-idempotent evaluate', async () => {
    saveLastSession({ ...target, sessionId: 'owned' }); writePending({ ...target, kind: 'reveal', sessionId: 'owned' });
    let reads = 0;
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (path === '/api/evaluate') { expect(JSON.parse(String(init?.body))).toEqual({ sessionId: 'owned' }); return response(evaluation); }
      return response(reads++ === 0 ? session() : session('given_up'));
    });
    const game = new GameController(target, { request }); await game.initialize();
    expect(request.mock.calls.map(args => args[0])).toEqual(['/api/session/owned', '/api/evaluate', '/api/session/owned']);
    expect(game.getSnapshot().phase).toBe('ended'); expect(readPending(target)).toBeNull();
  });
  it('late reveal after disposal cannot clear its journal or replace a newer game', async () => {
    saveLastSession({ ...target, sessionId: 'owned' }); const slow = deferred<ApiJsonResponse>();
    const request = vi.fn(async (path: string) => path === '/api/evaluate' ? slow.promise : response(session()));
    const game = new GameController(target, { request }); await game.initialize(); const pending = game.reveal();
    game.dispose(); const before = game.getSnapshot(); const other = { sessionId: 'next', soupId: 'other', level: '' }; saveLastSession(other);
    slow.resolve(response(evaluation)); await pending;
    expect(game.getSnapshot()).toBe(before); expect(getLastSession()).toEqual(other); expect(readPending(target)?.kind).toBe('reveal');
  });
});

describe('owned initialization and generation fences', () => {
  it('persists the create UUID before transport and clears only after saving a verified pointer', async () => {
    const request = vi.fn(async (_path: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      expect(readPending(target)).toMatchObject({ kind: 'create', requestId: body.requestId });
      return response(created(body.requestId));
    });
    const game = new GameController(target, { request });
    expect(game.getSnapshot().phase).toBe('initializing');
    expect(game.getSnapshot()).toBe(game.getSnapshot());
    await game.initialize();
    expect(game.getSnapshot().phase).toBe('playing');
    expect(getLastSession()).toEqual({ ...target, sessionId: 'owned' });
    expect(readPending(target)).toBeNull();
    expect(request).toHaveBeenCalledTimes(1);
  });
  it('same-controller StrictMode setup cleanup setup reuses UUID and retires old callbacks', async () => {
    const old = deferred<ApiJsonResponse>(), current = deferred<ApiJsonResponse>();
    const request = vi.fn().mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    const game = new GameController(target, { request });
    const first = game.initialize();
    const id = readPending(target)!.kind === 'create' && (readPending(target) as { requestId: string }).requestId;
    game.dispose();
    const second = game.initialize();
    const bodies = request.mock.calls.map(([, init]) => JSON.parse(init.body));
    expect(bodies.map(body => body.requestId)).toEqual([id, id]);
    current.resolve(response(created(String(id), 'Current title')));
    await second;
    old.resolve(response(created(String(id), 'Obsolete title')));
    await first;
    expect(game.getSnapshot().session?.soupTitle).toBe('Current title');
    expect(getLastSession()?.sessionId).toBe('owned');
  });
  it('late creation after navigation cannot replace another target pointer', async () => {
    const slow = deferred<ApiJsonResponse>();
    let firstId = '';
    const old = new GameController(target, { request: vi.fn((_path, init) => {
      firstId = JSON.parse(String(init?.body)).requestId;
      return slow.promise;
    }) });
    const pending = old.initialize();
    old.dispose();
    const nextTarget = { soupId: 'other', level: 'baozi' };
    const next = new GameController(nextTarget, { request: vi.fn(async (_path, init) => response(created(JSON.parse(String(init?.body)).requestId, 'New soup', 'next-session'))) });
    await next.initialize();
    slow.resolve(response(created(firstId, 'Old soup')));
    await pending;
    expect(getLastSession()).toEqual({ ...nextTarget, sessionId: 'next-session' });
    expect(readPending(target)?.kind).toBe('create'); // still recoverable, not falsely cancelled remotely
  });
  it('another controller changing saved pointer stops an old creation from overwriting it', async () => {
    const slow = deferred<ApiJsonResponse>();
    let id = '';
    const game = new GameController(target, { request: vi.fn((_path, init) => {
      id = JSON.parse(String(init?.body)).requestId; return slow.promise;
    }) });
    const pending = game.initialize();
    const foreign = { sessionId: 'another-tab', soupId: 'other', level: '' };
    saveLastSession(foreign);
    slow.resolve(response(created(id)));
    await pending;
    expect(game.getSnapshot().error?.category).toBe('conflict');
    expect(getLastSession()).toEqual(foreign);
    expect(readPending(target)?.kind).toBe('create');
  });
  it.each([404, 410, 409, 429, 503])('resume HTTP%s retains pointer and never automatically creates a game', async status => {
    const saved = { ...target, sessionId: 'owned' }; saveLastSession(saved);
    const request = vi.fn(async (path: string) => {
      expect(path).toBe('/api/session/owned');
      return response({ code: 'synthetic', detail: 'Synthetic' }, status);
    });
    const game = new GameController(target, { request });
    await game.initialize();
    expect(game.getSnapshot().phase).toBe('error');
    expect(getLastSession()).toEqual(saved);
    expect(request.mock.calls.every(call => call[0] === '/api/session/owned')).toBe(true);
    expect(readPending(target)).toBeNull();
  });
  it.each([new ApiAuthError(), new TypeError('Synthetic network failure')])('resume auth/network failure does not change saved identity', async error => {
    const saved = { ...target, sessionId: 'owned' }; saveLastSession(saved);
    const request = vi.fn().mockRejectedValue(error);
    const game = new GameController(target, { request });
    await game.initialize();
    expect(game.getSnapshot().error?.category).toBe(error instanceof ApiAuthError ? 'auth' : 'network');
    expect(getLastSession()).toEqual(saved);
    expect(request).toHaveBeenCalledTimes(1);
  });
  it.each(['solved', 'given_up'])('restores ended %s with exact frozen score and keeps pointer', async status => {
    saveLastSession({ ...target, sessionId: 'owned' });
    const request = vi.fn(async () => response(session(status)));
    const game = new GameController(target, { request });
    await game.initialize();
    expect(game.getSnapshot().phase).toBe('ended');
    expect(game.getSnapshot().session?.evaluation).toEqual(evaluation);
    expect(getLastSession()?.sessionId).toBe('owned');
    expect(request).toHaveBeenCalledTimes(1);
  });
  it('corrupted pointer or invalid restored DTO cannot create and overwrite an old game', async () => {
    localStorage.setItem('last_session', '{broken');
    const request = vi.fn(async () => response({}));
    const game = new GameController(target, { request });
    await game.initialize();
    expect(game.getSnapshot().error?.category).toBe('storage');
    expect(request).not.toHaveBeenCalled();
    expect(localStorage.getItem('last_session')).toBe('{broken');
    saveLastSession({ ...target, sessionId: 'owned' });
    await game.initialize();
    expect(game.getSnapshot().error?.category).toBe('protocol');
    expect(getLastSession()?.sessionId).toBe('owned');
    expect(request).toHaveBeenCalledTimes(1);
  });
  it('storage write failure blocks a POST before it leaves the browser', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Synthetic storage blocked'); });
    const request = vi.fn();
    const game = new GameController(target, { request });
    await game.initialize();
    expect(game.getSnapshot().error?.category).toBe('storage');
    expect(request).not.toHaveBeenCalled();
  });
  it('lost creation retries the persisted UUID without clearing pending on temporary failure', async () => {
    const request = vi.fn(async (_path: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      return request.mock.calls.length === 1 ? response({}, 503) : response(created(body.requestId));
    });
    const game = new GameController(target, { request });
    await game.initialize();
    const before = readPending(target);
    expect(before?.kind).toBe('create');
    expect(game.getSnapshot().error?.category).toBe('service');
    await game.synchronize();
    expect(request.mock.calls.map(([, init]) => JSON.parse(String(init?.body)).requestId)).toEqual([
      (before as { requestId: string }).requestId, (before as { requestId: string }).requestId,
    ]);
    expect(game.getSnapshot().phase).toBe('playing');
  });
  it('does not notify an unsubscribed observer or publish after disposal', async () => {
    const slow = deferred<ApiJsonResponse>();
    const request = vi.fn().mockReturnValue(slow.promise);
    const game = new GameController(target, { request });
    const listener = vi.fn(); const unsubscribe = game.subscribe(listener);
    const pending = game.initialize();
    const body = JSON.parse(request.mock.calls[0][1].body);
    unsubscribe(); game.dispose(); const calls = listener.mock.calls.length;
    slow.resolve(response(created(body.requestId)));
    await pending;
    expect(listener).toHaveBeenCalledTimes(calls);
    expect(getLastSession()).toBeNull();
  });
});

describe('committed question recovery', () => {
  function answer(requestId: string, changed = {}) {
    return { sessionId: 'owned', requestId, turnId: 'turn-owned', state: 'completed', kind: 'answer', reply: '是', remaining: 1,
      isFreeReminder: false, isWin: false, isReveal: false, isGiveup: false, limitReached: false, ...changed };
  }
  const afterAnswer = { ...session(), questionsAsked: 2, remaining: 1,
    messages: [{ role: 'user', content: '合成问题吗', timestamp: 1, turnId: 'turn-owned', isFreeReminder: false },
      { role: 'host', content: '是', timestamp: 2, turnId: 'turn-owned', isFreeReminder: false }] };

  it('blocks an empty-session question before initialization', async () => {
    const request = vi.fn(); const game = new GameController(target, { request });
    await game.ask('合成问题吗');
    expect(request).not.toHaveBeenCalled();
    expect(readPending(target)).toBeNull();
  });
  it('same-tick double click posts once and replaces optimistic guesses with authoritative history', async () => {
    saveLastSession({ ...target, sessionId: 'owned' });
    const slow = deferred<ApiJsonResponse>(); let id = ''; let reads = 0;
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        id = JSON.parse(String(init.body)).requestId;
        expect(readPending(target)).toMatchObject({ kind: 'ask', question: '合成问题吗', requestId: id });
        return slow.promise;
      }
      expect(path).toBe('/api/session/owned');
      return response(reads++ === 0 ? session() : afterAnswer);
    });
    const game = new GameController(target, { request }); await game.initialize();
    const first = game.ask('合成问题吗'), duplicate = game.ask('合成问题吗');
    expect(request.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
    slow.resolve(response(answer(id))); await first; await duplicate;
    expect(game.getSnapshot().session?.messages).toHaveLength(2);
    expect(game.getSnapshot().session?.remaining).toBe(1);
    expect(readPending(target)).toBeNull();
  });
  it('lost committed response keeps the original UUID and queries it on manual sync without reposting', async () => {
    saveLastSession({ ...target, sessionId: 'owned' }); let id = ''; let reads = 0;
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === 'POST') { id = JSON.parse(String(init.body)).requestId; throw new TypeError('Synthetic response lost after commit'); }
      if (path.includes('/turns/')) { expect(path).toBe(`/api/session/owned/turns/${id}`); return response(answer(id)); }
      return response(reads++ === 0 ? session() : afterAnswer);
    });
    const game = new GameController(target, { request }); await game.initialize(); await game.ask('合成问题吗');
    expect(readPending(target)).toMatchObject({ requestId: id });
    expect(game.getSnapshot().error?.message).not.toContain('不会扣次数');
    await game.synchronize();
    expect(game.getSnapshot().phase).toBe('playing');
    expect(game.getSnapshot().session?.remaining).toBe(1);
    expect(request.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
    expect(readPending(target)).toBeNull();
  });
  it('404 turn recovery validates the original session before retrying identical payload and UUID', async () => {
    saveLastSession({ ...target, sessionId: 'owned' }); const posts: unknown[] = []; let reads = 0;
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (path.includes('/turns/')) return response({}, 404);
      if (init?.method === 'POST') {
        const body = JSON.parse(String(init.body)); posts.push(body);
        if (posts.length === 1) throw new TypeError('Synthetic request lost before commit');
        return response(answer(body.requestId));
      }
      return response(reads++ < 2 ? session() : afterAnswer);
    });
    const game = new GameController(target, { request }); await game.initialize(); await game.ask('合成问题吗'); await game.synchronize();
    expect(posts).toHaveLength(2); expect(posts[0]).toEqual(posts[1]);
    expect(game.getSnapshot().session?.remaining).toBe(1);
    expect(readPending(target)).toBeNull();
  });
  it('a validated failed turn may say uncharged, whereas unknown transport failure cannot', async () => {
    saveLastSession({ ...target, sessionId: 'owned' });
    const request = vi.fn(async (_path: string, init?: RequestInit) => init?.method === 'POST'
      ? response(answer(JSON.parse(String(init.body)).requestId, { state: 'failed', kind: 'system_error', reply: '合成失败',
        remaining: 2, code: 'model_busy', detail: '合成失败', isFreeReminder: true }), 503) : response(session()));
    const game = new GameController(target, { request }); await game.initialize(); await game.ask('合成问题吗');
    expect(game.getSnapshot().phase).toBe('playing');
    expect(game.getSnapshot().session?.remaining).toBe(2);
    expect(game.getSnapshot().error?.message).toContain('没有扣次数');
    expect(readPending(target)).toBeNull();
  });
  it('an incorrect response identity cannot clear the pending question or change counts', async () => {
    saveLastSession({ ...target, sessionId: 'owned' });
    const request = vi.fn(async (_path: string, init?: RequestInit) => init?.method === 'POST'
      ? response(answer('29ab9f58-d899-41dd-a2ab-8e7b3667c9f1', { sessionId: 'foreign' })) : response(session()));
    const game = new GameController(target, { request }); await game.initialize(); await game.ask('合成问题吗');
    expect(game.getSnapshot().error?.category).toBe('protocol');
    expect(game.getSnapshot().session?.remaining).toBe(2);
    expect(readPending(target)?.kind).toBe('ask');
  });
  it('reserved recovery makes at most three queries spaced by one second', async () => {
    saveLastSession({ ...target, sessionId: 'owned' }); let id = ''; let queries = 0;
    const sleep = vi.fn(async (milliseconds: number) => { expect(milliseconds).toBe(1000); });
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === 'POST') { id = JSON.parse(String(init.body)).requestId; throw new TypeError('Synthetic lost response'); }
      if (path.includes('/turns/')) { queries++; return response({ sessionId: 'owned', requestId: id, turnId: 'turn-owned', state: 'reserved', code: 'turn_in_progress', detail: '处理中' }, 202); }
      return response(session());
    });
    const game = new GameController(target, { request, sleep }); await game.initialize(); await game.ask('合成问题吗'); await game.synchronize();
    expect(queries).toBe(3);
    expect(sleep.mock.calls.map(args => args[0])).toEqual([1000, 1000]);
    expect(game.getSnapshot().phase).toBe('syncing');
    expect(readPending(target)).toMatchObject({ requestId: id });
  });
  it('a reserved reply can resolve in the same bounded poll without sending another POST', async () => {
    saveLastSession({ ...target, sessionId: 'owned' }); let id = ''; let queries = 0; let reads = 0;
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === 'POST') { id = JSON.parse(String(init.body)).requestId; throw new TypeError('Synthetic lost response'); }
      if (path.includes('/turns/')) return ++queries === 1
        ? response({ sessionId: 'owned', requestId: id, turnId: 'turn-owned', state: 'reserved', code: 'turn_in_progress', detail: '处理中' }, 202)
        : response(answer(id));
      return response(reads++ === 0 ? session() : afterAnswer);
    });
    const game = new GameController(target, { request, sleep: async () => {} }); await game.initialize(); await game.ask('合成问题吗'); await game.synchronize();
    expect(queries).toBe(2); expect(readPending(target)).toBeNull();
    expect(game.getSnapshot().session?.remaining).toBe(1);
    expect(request.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
  });
  it('429 stops polling and respects Retry-After before a manual sync', async () => {
    saveLastSession({ ...target, sessionId: 'owned' }); let now = 0; let id = ''; let queries = 0; let reads = 0;
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === 'POST') { id = JSON.parse(String(init.body)).requestId; throw new TypeError('Synthetic lost response'); }
      if (path.includes('/turns/')) {
        if (++queries === 1) return { ...response({}, 429), headers: new Headers({ 'Retry-After': '2' }) };
        return response(answer(id));
      }
      return response(reads++ === 0 ? session() : afterAnswer);
    });
    const game = new GameController(target, { request, now: () => now, sleep: async () => {} });
    await game.initialize(); await game.ask('合成问题吗'); await game.synchronize();
    expect(queries).toBe(1); expect(game.getSnapshot().error?.category).toBe('rate');
    now = 1999; await game.synchronize(); expect(queries).toBe(1);
    now = 2000; await game.synchronize(); expect(queries).toBe(2);
    expect(game.getSnapshot().phase).toBe('playing'); expect(readPending(target)).toBeNull();
  });
  it('a late committed answer after disposal cannot update UI, saved pointer or pending', async () => {
    saveLastSession({ ...target, sessionId: 'owned' }); const slow = deferred<ApiJsonResponse>(); let id = '';
    const request = vi.fn(async (_path: string, init?: RequestInit) => {
      if (init?.method === 'POST') { id = JSON.parse(String(init.body)).requestId; return slow.promise; }
      return response(session());
    });
    const game = new GameController(target, { request }); await game.initialize(); const pending = game.ask('合成问题吗');
    game.dispose(); const before = game.getSnapshot();
    const other = { sessionId: 'next-session', soupId: 'other', level: '' }; saveLastSession(other);
    slow.resolve(response(answer(id))); await pending;
    expect(game.getSnapshot()).toBe(before); expect(getLastSession()).toEqual(other);
    expect(readPending(target)).toMatchObject({ requestId: id });
  });
});
