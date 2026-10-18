/** One route owner. Generation checks fence state AND persistent game pointers. */
import { ApiAuthError, ApiHttpError, ApiProtocolError, apiResponseJson, httpError, saveLastSession, addPlayedSoup, addUnlockedSoup,
  type ApiJsonResponse, type LastSession } from './api';
import { decodeCreation, decodeEvaluation, decodeSession, decodeTurn, GameContractError, type SessionSnapshot } from './game-contract';
import { clearPending, GameStorageError, newRequestId, readPending, readSavedSession, sameOperation, writePending,
  type GameTarget, type PendingOperation } from './game-journal';

export interface GameIssue {
  category: 'auth' | 'missing' | 'incompatible' | 'rate' | 'service' | 'network' | 'protocol' | 'storage' | 'conflict';
  message: string; retryAfterSeconds: number | null;
}
export interface GameState {
  phase: 'initializing' | 'playing' | 'asking' | 'syncing' | 'revealing' | 'ended' | 'error';
  session: SessionSnapshot | null; pending: PendingOperation | null; error: GameIssue | null;
}
interface ControllerDeps {
  request?: (path: string, init?: RequestInit) => Promise<ApiJsonResponse>;
  journal?: { read: typeof readPending; write: typeof writePending; clear: typeof clearPending };
  lastSession?: { read: typeof readSavedSession; save: typeof saveLastSession };
  newId?: () => string;
  now?: () => number;
  sleep?: (milliseconds: number, signal?: AbortSignal) => Promise<void>;
}
class OwnershipConflict extends Error {
  constructor() { super('保存的游戏已被另一个页面更新，请保留当前请求并重新同步'); }
}
function sameSavedSession(a: LastSession | null, b: LastSession | null): boolean {
  return a === null || b === null ? a === b : a.sessionId === b.sessionId && a.soupId === b.soupId && a.level === b.level;
}
function pause(milliseconds: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new DOMException('Operation aborted', 'AbortError')); return; }
    const abort = () => { clearTimeout(timer); reject(new DOMException('Operation aborted', 'AbortError')); };
    const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve(); }, milliseconds);
    signal?.addEventListener('abort', abort, { once: true });
  });
}
function classify(error: unknown): GameIssue {
  let category: GameIssue['category'] = 'network';
  if (error instanceof GameStorageError) category = 'storage';
  else if (error instanceof OwnershipConflict) category = 'conflict';
  else if (error instanceof GameContractError || error instanceof ApiProtocolError) category = 'protocol';
  else if (error instanceof ApiAuthError) category = 'auth';
  else if (error instanceof ApiHttpError) category = ({ 404: 'missing', 410: 'incompatible', 409: 'conflict',
    429: 'rate' } as Record<number, GameIssue['category']>)[error.status] || 'service';
  return { category, message: error instanceof Error ? error.message : '网络暂时不可用，请同步原对局',
    retryAfterSeconds: error instanceof ApiHttpError ? error.retryAfterSeconds : null };
}

export class GameController {
  private readonly target: GameTarget;
  private readonly request: NonNullable<ControllerDeps['request']>;
  private readonly journal: NonNullable<ControllerDeps['journal']>;
  private readonly lastSession: NonNullable<ControllerDeps['lastSession']>;
  private readonly newId: () => string;
  private readonly now: () => number;
  private readonly sleep: NonNullable<ControllerDeps['sleep']>;
  private retryAt = 0;
  private state: GameState = { phase: 'initializing', session: null, pending: null, error: null };
  private readonly listeners = new Set<() => void>();
  private generation = 0;
  private abort: AbortController | null = null;
  private inFlight = false;
  private ownedPointer: LastSession | null = null;

  constructor(target: GameTarget, deps: ControllerDeps = {}) {
    this.target = Object.freeze({ ...target });
    this.request = deps.request || apiResponseJson;
    this.journal = deps.journal || { read: readPending, write: writePending, clear: clearPending };
    this.lastSession = deps.lastSession || { read: readSavedSession, save: saveLastSession };
    this.newId = deps.newId || newRequestId;
    this.now = deps.now || (() => Date.now());
    this.sleep = deps.sleep || pause;
  }
  getSnapshot = (): GameState => this.state;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  private publish(change: Partial<GameState>): void {
    this.state = { ...this.state, ...change };
    for (const listener of this.listeners) listener();
  }
  private current(generation: number): boolean { return this.generation === generation && !this.abort?.signal.aborted; }
  dispose(): void { this.generation++; this.abort?.abort(); this.inFlight = false; }
  private fail(error: unknown): void {
    if (error instanceof ApiHttpError && error.status === 429) this.retryAt = this.now() + Math.max(1000, (error.retryAfterSeconds ?? 1) * 1000);
    this.publish({ phase: 'error', error: classify(error) });
  }

  async initialize(): Promise<void> {
    if (this.retryAt > this.now()) return;
    const generation = ++this.generation;
    this.abort?.abort(); this.abort = new AbortController(); this.inFlight = true;
    this.publish({ phase: 'initializing', error: null });
    try {
      const pending = this.journal.read(this.target), saved = this.lastSession.read();
      this.ownedPointer = saved;
      this.publish({ pending });
      if (pending?.kind === 'ask' || pending?.kind === 'reveal') {
        // A route journal remains readable when another route was last visited.
        // Writes still require the captured pointer and journal to be unchanged.
        if (pending.kind === 'ask') await this.recoverAsk(pending, generation);
        else await this.recoverReveal(pending, generation);
        return;
      }
      if (!pending && saved && saved.soupId === this.target.soupId && saved.level === this.target.level) {
        const response = await this.request(`/api/session/${encodeURIComponent(saved.sessionId)}`, { signal: this.abort.signal });
        if (!this.current(generation)) return;
        if (!response.ok) throw httpError(response);
        const session = decodeSession(response.body, saved.sessionId, this.target.soupId);
        if (!sameSavedSession(this.lastSession.read(), saved)) throw new OwnershipConflict();
        await this.acceptSession(session, generation);
        return;
      }
      const operation = pending || { ...this.target, kind: 'create' as const, requestId: this.newId() };
      this.journal.write(operation); // durable before HTTP; failed writes cannot send
      this.publish({ pending: operation });
      const response = await this.request('/api/chat', { method: 'POST', signal: this.abort.signal,
        body: JSON.stringify({ ...this.target, requestId: operation.requestId }) });
      if (!this.current(generation)) return;
      if (!response.ok) throw httpError(response);
      const created = decodeCreation(response.body, operation.requestId);
      if (!sameSavedSession(this.lastSession.read(), saved)
          || !this.journal.read(this.target) || JSON.stringify(this.journal.read(this.target)) !== JSON.stringify(operation)) throw new OwnershipConflict();
      const pointer: LastSession = { ...this.target, sessionId: created.sessionId };
      try { this.lastSession.save(pointer); } catch { throw new GameStorageError('新局已返回，但无法保存恢复指针；原请求编号仍保留'); }
      this.ownedPointer = pointer;
      if (!this.journal.clear(operation)) throw new OwnershipConflict();
      const session: SessionSnapshot = { sessionId: created.sessionId, soupId: this.target.soupId,
        soupTitle: created.soupTitle, soupSurface: created.soupSurface, questionLimit: created.questionLimit,
        questionsAsked: 0, remaining: created.questionLimit, unlocks: created.unlocks, messages: [], status: 'playing', evaluation: null };
      await this.acceptSession(session, generation);
    } catch (error) {
      if (this.current(generation)) this.fail(error);
    } finally { if (this.current(generation)) this.inFlight = false; }
  }
  async synchronize(): Promise<void> {
    if (this.inFlight) return;
    await this.initialize();
  }

  private async acceptSession(session: SessionSnapshot, generation: number, error: GameIssue | null = null): Promise<void> {
    if (!this.current(generation)) return;
    if (this.holdSuspended(session, generation)) return;
    if ((session.status === 'solved' && !session.evaluation) || (session.status === 'playing' && session.remaining === 0)) {
      const operation = { ...this.target, kind: 'reveal' as const, sessionId: session.sessionId };
      this.journal.write(operation);
      this.publish({ phase: 'revealing', session, pending: operation, error: null });
      await this.postReveal(operation, generation);
    } else this.publish({ phase: session.status === 'playing' ? 'playing' : 'ended', session, pending: null,
      error: session.evaluation ? this.recordResult(session) : error });
  }

  private holdSuspended(session: SessionSnapshot, generation: number, pending: PendingOperation | null = null): boolean {
    // A saved ended result is still readable. Only operations requiring a new
    // decision pause; don't delete its durable request or silently create/rebase.
    if (!session.ruleSuspended || (session.status !== 'playing' && session.evaluation)) return false;
    if (this.current(generation)) this.publish({ phase: 'playing', session, pending,
      error: { category: 'conflict', message: '本局规则暂停，历史和原请求编号已保留；管理员解除后请同步原对局', retryAfterSeconds: null } });
    return true;
  }

  private recordResult(session: SessionSnapshot): GameIssue | null {
    try {
      addPlayedSoup(this.target.soupId);
      if (session.evaluation?.unlockSoupId) addUnlockedSoup(session.evaluation.unlockSoupId);
      return null;
    } catch { return classify(new GameStorageError('结果已保存，但浏览器未能保存玩过/解锁标记；原对局仍可同步')); }
  }

  async restart(confirmAbandon = false): Promise<void> {
    if (this.inFlight || this.retryAt > this.now() || this.generation === 0 || this.abort?.signal.aborted) return;
    const generation = this.generation;
    this.inFlight = true;
    try {
      if (!sameSavedSession(this.lastSession.read(), this.ownedPointer)) throw new OwnershipConflict();
      const pending = this.journal.read(this.target);
      if (pending && (!confirmAbandon || !this.state.pending || !sameOperation(pending, this.state.pending))) throw new OwnershipConflict();
      if (pending && !this.journal.clear(pending)) throw new OwnershipConflict();
      const operation = { ...this.target, kind: 'create' as const, requestId: this.newId() };
      this.journal.write(operation); // old pointer survives until verified new creation
      this.publish({ phase: 'initializing', session: null, pending: operation, error: null });
      await this.initialize();
    } catch (error) { if (this.current(generation)) this.fail(error); }
    finally { if (this.current(generation)) this.inFlight = false; }
  }

  private assertAskOwner(operation: Extract<PendingOperation, { kind: 'ask' | 'reveal' }>, generation: number): void {
    const stored = this.journal.read(this.target);
    if (!this.current(generation) || !stored || !sameOperation(stored, operation)
        || !sameSavedSession(this.lastSession.read(), this.ownedPointer)) throw new OwnershipConflict();
  }
  private reclaimVerifiedSession(operation: Extract<PendingOperation, { kind: 'ask' | 'reveal' }>, generation: number): void {
    // Only call after canonical GET validates the original session/soup.
    this.assertAskOwner(operation, generation);
    const pointer = { ...this.target, sessionId: operation.sessionId };
    if (sameSavedSession(this.ownedPointer, pointer)) return;
    try { this.lastSession.save(pointer); }
    catch { throw new GameStorageError('原对局已核验，但无法保存恢复指针；原请求编号仍保留'); }
    this.ownedPointer = pointer;
  }
  private async readSession(sessionId: string, generation: number): Promise<SessionSnapshot> {
    const response = await this.request(`/api/session/${encodeURIComponent(sessionId)}`, { signal: this.abort?.signal });
    if (!this.current(generation)) throw new OwnershipConflict();
    if (!response.ok) throw httpError(response);
    return decodeSession(response.body, sessionId, this.target.soupId);
  }
  private async settleAsk(operation: Extract<PendingOperation, { kind: 'ask' }>, response: ApiJsonResponse, generation: number): Promise<void> {
    if (!this.current(generation)) return;
    if (!response.ok && (response.status !== 503 || !response.body || typeof response.body !== 'object'
        || !('state' in response.body))) throw httpError(response);
    const result = decodeTurn(response.body, operation);
    if (result.state === 'reserved') {
      if (response.status !== 202) throw new GameContractError();
      this.assertAskOwner(operation, generation);
      const session = await this.readSession(operation.sessionId, generation);
      this.reclaimVerifiedSession(operation, generation);
      if (this.holdSuspended(session, generation, operation)) return;
      this.publish({ phase: 'syncing', session, pending: operation,
        error: { category: 'service', message: '这次提问仍在处理，提交结果尚未确定，请稍后同步原请求', retryAfterSeconds: null } });
      return;
    }
    if (response.status !== (result.kind === 'system_error' ? 503 : 200)) throw new GameContractError();
    const session = await this.readSession(operation.sessionId, generation);
    this.reclaimVerifiedSession(operation, generation);
    if (this.holdSuspended(session, generation, operation)) return;
    if (!this.journal.clear(operation)) throw new OwnershipConflict();
    await this.acceptSession(session, generation, result.kind === 'system_error'
      ? { category: 'service', message: '本次提问失败，没有扣次数；可以重新提问', retryAfterSeconds: null } : null);
  }
  private async postAsk(operation: Extract<PendingOperation, { kind: 'ask' }>, generation: number): Promise<void> {
    this.assertAskOwner(operation, generation);
    const response = await this.request('/api/chat', { method: 'POST', signal: this.abort?.signal,
      body: JSON.stringify({ sessionId: operation.sessionId, soupId: operation.soupId, question: operation.question, requestId: operation.requestId }) });
    await this.settleAsk(operation, response, generation);
  }
  private async recoverAsk(operation: Extract<PendingOperation, { kind: 'ask' }>, generation: number): Promise<void> {
    for (let attempt = 0; attempt < 3; attempt++) {
      this.assertAskOwner(operation, generation);
      const response = await this.request(`/api/session/${encodeURIComponent(operation.sessionId)}/turns/${operation.requestId}`, { signal: this.abort?.signal });
      if (!this.current(generation)) return;
      if (response.status === 404) {
        // Validate original session, then retry only SAME persisted identity.
        const session = await this.readSession(operation.sessionId, generation);
        this.assertAskOwner(operation, generation);
        this.reclaimVerifiedSession(operation, generation);
        if (this.holdSuspended(session, generation, operation)) return;
        if (session.status !== 'playing') {
          // Missing turn alone says nothing about charging. The canonical
          // terminal session is authoritative, and must never receive a repost.
          if (!this.journal.clear(operation)) throw new OwnershipConflict();
          await this.acceptSession(session, generation);
          return;
        }
        await this.postAsk(operation, generation);
        return;
      }
      await this.settleAsk(operation, response, generation);
      if (this.state.pending === null || this.state.phase !== 'syncing' || attempt === 2) return;
      await this.sleep(1000, this.abort?.signal);
      if (!this.current(generation)) return;
    }
  }
  async ask(input: string): Promise<void> {
    const question = input.trim(), session = this.state.session;
    if (!question || this.abort?.signal.aborted || this.inFlight || this.state.phase !== 'playing' || !session || session.status !== 'playing'
        || session.ruleSuspended || this.state.pending || (session.remaining !== null && session.remaining <= 0)) return;
    const generation = this.generation;
    this.inFlight = true;
    try {
      const operation: Extract<PendingOperation, { kind: 'ask' }> = { ...this.target, kind: 'ask', sessionId: session.sessionId,
        question, requestId: this.newId() };
      this.journal.write(operation);
      this.publish({ phase: 'asking', pending: operation, error: null });
      await this.postAsk(operation, generation);
    } catch (error) {
      if (this.current(generation)) this.fail(error);
    } finally { if (this.current(generation)) this.inFlight = false; }
  }

  private finishReveal(operation: Extract<PendingOperation, { kind: 'reveal' }>, session: SessionSnapshot, generation: number): void {
    this.assertAskOwner(operation, generation);
    if (session.status === 'playing' || !session.evaluation) throw new GameContractError('结果尚未完整保存，请同步原对局');
    if (!this.journal.clear(operation)) throw new OwnershipConflict();
    this.publish({ phase: 'ended', session, pending: null, error: this.recordResult(session) });
  }
  private async postReveal(operation: Extract<PendingOperation, { kind: 'reveal' }>, generation: number): Promise<void> {
    this.assertAskOwner(operation, generation);
    const response = await this.request('/api/evaluate', { method: 'POST', signal: this.abort?.signal,
      body: JSON.stringify({ sessionId: operation.sessionId }) });
    if (!this.current(generation)) return;
    if (!response.ok) throw httpError(response);
    decodeEvaluation(response.body);
    // The saved session, not an unbound optimistic result, is the display authority.
    const session = await this.readSession(operation.sessionId, generation);
    this.finishReveal(operation, session, generation);
  }
  private async recoverReveal(operation: Extract<PendingOperation, { kind: 'reveal' }>, generation: number): Promise<void> {
    this.assertAskOwner(operation, generation);
    const session = await this.readSession(operation.sessionId, generation);
    this.reclaimVerifiedSession(operation, generation);
    if (this.holdSuspended(session, generation, operation)) return;
    this.publish({ phase: 'revealing', session, pending: operation, error: null });
    if (session.status !== 'playing' && session.evaluation) this.finishReveal(operation, session, generation);
    else await this.postReveal(operation, generation); // same session-idempotent operation only
  }
  async reveal(): Promise<void> {
    const session = this.state.session;
    if (this.abort?.signal.aborted || this.inFlight || this.retryAt > this.now() || this.state.phase !== 'playing' || !session
      || session.ruleSuspended || this.state.pending) return;
    const generation = this.generation;
    this.inFlight = true;
    try {
      const operation = { ...this.target, kind: 'reveal' as const, sessionId: session.sessionId };
      this.journal.write(operation);
      this.publish({ phase: 'revealing', pending: operation, error: null });
      await this.postReveal(operation, generation);
    } catch (error) { if (this.current(generation)) this.fail(error); }
    finally { if (this.current(generation)) this.inFlight = false; }
  }
}
