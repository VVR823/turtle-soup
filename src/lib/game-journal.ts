/** Durable browser intent. No retry may mint a new identity behind the player. */
import { isRequestId } from './game-contract';
import type { LastSession } from './api';

export interface GameTarget { soupId: string; level: string }
export type PendingOperation = GameTarget & (
  { kind: 'create'; requestId: string } | { kind: 'ask'; requestId: string; sessionId: string; question: string }
  | { kind: 'reveal'; sessionId: string }
);
export class GameStorageError extends Error {
  constructor(message = '无法读取保存的对局，请检查浏览器存储后重试') { super(message); this.name = 'GameStorageError'; }
}
function validText(value: unknown, max: number, allowEmpty = false): value is string {
  return typeof value === 'string' && (allowEmpty || !!value.trim()) && Array.from(value).length <= max;
}
function targetKey(target: GameTarget): string {
  if (!validText(target.soupId, 200) || !validText(target.level, 50, true)) throw new GameStorageError('保存的游戏目标格式无效');
  return 'game_operation_v1:' + JSON.stringify([target.soupId, target.level]);
}
function decode(input: unknown): PendingOperation {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new GameStorageError('保存的操作记录无法核验');
  const data = input as Record<string, unknown>;
  if (!validText(data.soupId, 200) || !validText(data.level, 50, true)) throw new GameStorageError('保存的操作目标无法核验');
  const target = { soupId: data.soupId, level: data.level };
  const allowed = ['soupId', 'level', 'kind', ...(data.kind === 'reveal' ? ['sessionId'] : ['requestId']), ...(data.kind === 'ask' ? ['sessionId', 'question'] : [])];
  if (Object.keys(data).some(key => !allowed.includes(key))) throw new GameStorageError('保存的操作包含未知字段');
  if (data.kind === 'reveal' && validText(data.sessionId, 200)) return { ...target, kind: 'reveal', sessionId: data.sessionId };
  if (!isRequestId(data.requestId)) throw new GameStorageError('保存的请求编号无法核验');
  if (data.kind === 'create') return { ...target, kind: 'create', requestId: data.requestId };
  if (data.kind === 'ask' && validText(data.sessionId, 200) && validText(data.question, 500) && data.question === data.question.trim()) {
    return { ...target, kind: 'ask', requestId: data.requestId, sessionId: data.sessionId, question: data.question };
  }
  throw new GameStorageError('保存的操作记录无法核验');
}
function storage(): Storage {
  try { if (typeof window !== 'undefined') return window.localStorage; } catch { /* handled below */ }
  throw new GameStorageError('浏览器存储不可用，暂未发送请求');
}
export function readPending(target: GameTarget): PendingOperation | null {
  const key = targetKey(target);
  try {
    const raw = storage().getItem(key);
    if (raw === null) return null;
    const data = JSON.parse(raw);
    if (!data || data.version !== 1 || Object.keys(data).some(key => !['version', 'operation'].includes(key))) throw new GameStorageError();
    const operation = decode(data.operation);
    if (targetKey(operation) !== key) throw new GameStorageError();
    return operation;
  } catch { throw new GameStorageError(); }
}
export function sameOperation(a: PendingOperation, b: PendingOperation): boolean {
  return JSON.stringify(decode(a)) === JSON.stringify(decode(b));
}
export function writePending(input: PendingOperation): void {
  const operation = decode(input), current = readPending(operation);
  if (current && !sameOperation(current, operation)) throw new GameStorageError('另一个操作尚未同步，暂未发送新请求');
  try { storage().setItem(targetKey(operation), JSON.stringify({ version: 1, operation })); }
  catch { throw new GameStorageError('无法保存请求编号，暂未发送请求'); }
}
export function clearPending(expected: PendingOperation): boolean {
  const operation = decode(expected), current = readPending(operation);
  if (!current || !sameOperation(current, operation)) return false;
  try { storage().removeItem(targetKey(operation)); } catch { throw new GameStorageError('无法更新保存的操作记录'); }
  return true;
}
export function readSavedSession(): LastSession | null {
  try {
    const raw = storage().getItem('last_session');
    if (raw === null) return null;
    const data = JSON.parse(raw);
    if (!data || !validText(data.sessionId, 200) || !validText(data.soupId, 200) || !validText(data.level, 50, true)) throw new GameStorageError();
    return { sessionId: data.sessionId, soupId: data.soupId, level: data.level };
  } catch { throw new GameStorageError('保存的对局暂时无法核验，原记录已保留'); }
}
export function newRequestId(): string {
  try {
    const crypto = globalThis.crypto;
    if (typeof crypto?.randomUUID === 'function') {
      const id = crypto.randomUUID();
      if (isRequestId(id)) return id;
      throw new Error('Invalid UUID');
    }
    if (typeof crypto?.getRandomValues !== 'function') throw new Error('Secure randomness unavailable');
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
    const id = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    if (isRequestId(id)) return id;
  } catch { /* handled below */ }
  throw new GameStorageError('无法生成安全请求编号，暂未发送请求');
}
