/** Public response boundaries; text or missing fields never grant game state. */
import { normalizeEvaluationDisplay, type EvaluationResult } from './evaluation';

export class GameContractError extends Error {
  constructor(message = '服务返回的数据暂时无法核验，请同步原对局') { super(message); this.name = 'GameContractError'; }
}

export const isRequestId = (value: unknown): value is string => typeof value === 'string'
  && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value);

function record(input: unknown): Record<string, unknown> {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new GameContractError();
  return input as Record<string, unknown>;
}
function text(input: unknown, maximum = Infinity, nonempty = true): string {
  if (typeof input !== 'string' || (nonempty && !input.trim()) || Array.from(input).length > maximum) throw new GameContractError();
  return input;
}
function count(input: unknown): number {
  if (typeof input !== 'number' || !Number.isSafeInteger(input) || input < 0) throw new GameContractError();
  return input;
}
function nullableCount(input: unknown): number | null { return input === null ? null : count(input); }
function nullableId(input: unknown): string | null { return input == null ? null : text(input, 200); }
function boolean(input: unknown): boolean { if (typeof input !== 'boolean') throw new GameContractError(); return input; }
function strings(input: unknown): string[] {
  if (!Array.isArray(input)) throw new GameContractError();
  return input.map(value => text(value, Infinity, false));
}

export interface CreationResponse {
  requestId: string; sessionId: string; soupTitle: string; soupSurface: string;
  questionLimit: number | null; unlocks: string | null;
}
export interface PublicMessage {
  role: 'user' | 'host'; content: string; timestamp: number; turnId?: string | null; isFreeReminder?: boolean;
}
export interface SessionSnapshot extends Omit<CreationResponse, 'requestId'> {
  soupId: string; status: 'playing' | 'solved' | 'given_up'; questionsAsked: number;
  remaining: number | null; messages: PublicMessage[]; evaluation: EvaluationResult | null;
  ruleSuspended?: boolean;
}
interface TurnIdentity { sessionId: string; requestId: string; turnId: string }
export type TurnResponse = (TurnIdentity & { state: 'reserved'; code: 'turn_in_progress'; detail: string })
  | (TurnIdentity & {
    state: 'completed' | 'failed' | 'expired'; kind: 'answer' | 'reminder' | 'win' | 'system_error';
    reply: string; remaining: number | null; isFreeReminder: boolean; isWin: boolean; isReveal: boolean;
    isGiveup: false; limitReached: boolean; code?: string | null; detail?: string | null;
  });

export function decodeCreation(input: unknown, expectedRequestId: string): CreationResponse {
  const data = record(input);
  if (!isRequestId(data.requestId) || data.requestId !== expectedRequestId) throw new GameContractError();
  return { requestId: data.requestId, sessionId: text(data.sessionId, 200), soupTitle: text(data.soupTitle),
    soupSurface: text(data.soupSurface, Infinity, false), questionLimit: nullableCount(data.questionLimit), unlocks: nullableId(data.unlocks) };
}

export function decodeEvaluation(input: unknown): EvaluationResult {
  const data = record(input);
  try { normalizeEvaluationDisplay(data); } catch { throw new GameContractError(); }
  const result: EvaluationResult = { completion: data.completion as number, evaluation: text(data.evaluation, Infinity, false),
    keyPointsCovered: strings(data.keyPointsCovered), keyPointsMissing: strings(data.keyPointsMissing), bottom: text(data.bottom, Infinity, false) };
  if (data.unlockSoupId !== undefined) result.unlockSoupId = nullableId(data.unlockSoupId);
  if (data.verifiedCoverage !== undefined) result.verifiedCoverage = data.verifiedCoverage as number | null;
  if (data.reconstructionScore !== undefined) result.reconstructionScore = null;
  if (data.scoreVersion !== undefined) result.scoreVersion = data.scoreVersion as 'coverage-v1' | null;
  if (data.plotProgress !== undefined) result.plotProgress = data.plotProgress as number | null;
  if (data.unknownTopics !== undefined) {
    result.unknownTopics = strings(data.unknownTopics);
    if (data.scoreVersion == null && result.unknownTopics.length) throw new GameContractError();
  }
  return result;
}

export function decodeSession(input: unknown, expectedSessionId: string, expectedSoupId: string): SessionSnapshot {
  const data = record(input);
  if (data.sessionId !== expectedSessionId || data.soupId !== expectedSoupId
      || typeof data.status !== 'string' || !['playing', 'solved', 'given_up'].includes(data.status)) throw new GameContractError();
  const questionLimit = nullableCount(data.questionLimit), questionsAsked = count(data.questionsAsked), remaining = nullableCount(data.remaining);
  if (remaining !== (questionLimit === null ? null : Math.max(0, questionLimit - questionsAsked))) throw new GameContractError();
  if (!Array.isArray(data.messages)) throw new GameContractError();
  const messages = data.messages.map(inputMessage => {
    const message = record(inputMessage);
    if ((message.role !== 'user' && message.role !== 'host') || typeof message.timestamp !== 'number'
        || !Number.isFinite(message.timestamp) || message.timestamp < 0) throw new GameContractError();
    const result: PublicMessage = { role: message.role, content: text(message.content, Infinity, false), timestamp: message.timestamp };
    if (message.turnId !== undefined) result.turnId = nullableId(message.turnId);
    if (message.isFreeReminder !== undefined) result.isFreeReminder = boolean(message.isFreeReminder);
    return result;
  });
  const evaluation = data.evaluation == null ? null : decodeEvaluation(data.evaluation);
  if ((data.status === 'playing' && evaluation !== null) || (data.status === 'given_up' && evaluation === null)) throw new GameContractError();
  return { sessionId: text(data.sessionId, 200), soupId: text(data.soupId, 200), soupTitle: text(data.soupTitle),
    soupSurface: text(data.soupSurface, Infinity, false), questionLimit, questionsAsked, remaining, unlocks: nullableId(data.unlocks),
    status: data.status as SessionSnapshot['status'], messages, evaluation,
    ruleSuspended: 'ruleSuspended' in data ? boolean(data.ruleSuspended) : false };
}

const modelErrorCodes = new Set(['model_timeout', 'model_busy', 'model_unavailable', 'model_output_invalid', 'model_policy_unknown',
  'model_auth', 'model_quota', 'model_transport_error', 'model_cancelled', 'model_cleanup_failed', 'context_too_large', 'turn_expired']);

export function decodeTurn(input: unknown, expected: { sessionId: string; requestId: string }): TurnResponse {
  const data = record(input);
  if (data.sessionId !== expected.sessionId || !isRequestId(data.requestId) || data.requestId !== expected.requestId) throw new GameContractError();
  const identity = { sessionId: text(data.sessionId, 200), requestId: data.requestId, turnId: text(data.turnId, 200) };
  if (data.state === 'reserved') {
    if (data.code !== 'turn_in_progress' || data.kind !== undefined || data.reply !== undefined || data.isFreeReminder !== undefined) throw new GameContractError();
    return { ...identity, state: 'reserved', code: 'turn_in_progress', detail: text(data.detail, 2000) };
  }
  if (typeof data.state !== 'string' || !['completed', 'failed', 'expired'].includes(data.state)
      || typeof data.kind !== 'string' || !['answer', 'reminder', 'win', 'system_error'].includes(data.kind)) throw new GameContractError();
  const kind = data.kind as 'answer' | 'reminder' | 'win' | 'system_error';
  const isFreeReminder = boolean(data.isFreeReminder), isWin = boolean(data.isWin), isReveal = boolean(data.isReveal);
  const limitReached = boolean(data.limitReached), remaining = nullableCount(data.remaining), reply = text(data.reply, 2000);
  const failure = data.state === 'failed' || data.state === 'expired';
  if (isFreeReminder !== (kind === 'reminder' || kind === 'system_error') || isWin !== (kind === 'win')
      || isReveal !== isWin || data.isGiveup !== false || failure !== (kind === 'system_error')
      || (limitReached && (kind !== 'reminder' || remaining !== 0))) throw new GameContractError();
  if (failure) {
    if (typeof data.code !== 'string' || !modelErrorCodes.has(data.code) || data.detail !== reply
        || (data.state === 'expired' && data.code !== 'turn_expired')) throw new GameContractError();
  } else if (data.code != null || data.detail != null) throw new GameContractError();
  return { ...identity, state: data.state as 'completed' | 'failed' | 'expired', kind, reply, remaining,
    isFreeReminder, isWin, isReveal, isGiveup: false, limitReached,
    ...(data.code !== undefined ? { code: data.code as string | null } : {}),
    ...(data.detail !== undefined ? { detail: data.detail as string | null } : {}) };
}
