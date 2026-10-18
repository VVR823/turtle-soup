import { describe, expect, it } from 'vitest';
import { decodeCreation, decodeEvaluation, decodeSession, decodeTurn, GameContractError } from './game-contract';

const requestId = '29ab9f58-d899-41dd-a2ab-8e7b3667c9f1';
const creation = { requestId, sessionId: 'synthetic-session', soupTitle: 'Public', soupSurface: 'Public story', questionLimit: 3, unlocks: null };
const evaluation = { completion: 50, verifiedCoverage: 50, scoreVersion: 'coverage-v1', reconstructionScore: null,
  plotProgress: 80, evaluation: 'Synthetic', keyPointsCovered: ['A'], keyPointsMissing: ['B'], bottom: 'Synthetic truth', unknownTopics: [] };
const snapshot = { ...creation, soupId: 'synthetic', status: 'playing', questionsAsked: 1, remaining: 2,
  messages: [{ role: 'user', content: '合成问题吗', timestamp: 1, turnId: 'turn', isFreeReminder: false },
    { role: 'host', content: '是', timestamp: 2, turnId: 'turn', isFreeReminder: false }], evaluation: null };
const turn = { sessionId: creation.sessionId, requestId, turnId: 'turn', state: 'completed', kind: 'answer',
  reply: '是', remaining: 2, isFreeReminder: false, isWin: false, isReveal: false, isGiveup: false, limitReached: false };
const identity = { sessionId: creation.sessionId, requestId };

describe('strict public game DTOs', () => {
  it('decodes an owned creation and rejects another request identity', () => {
    expect(decodeCreation(creation, requestId)).toEqual(creation);
    expect(() => decodeCreation({ ...creation, requestId: 'another' }, requestId)).toThrow();
  });
  it('uses nullable unlimited counts without coercing strings or booleans', () => {
    expect(decodeCreation({ ...creation, questionLimit: null }, requestId).questionLimit).toBeNull();
    for (const value of [-1, 1.5, '3', true]) expect(() => decodeCreation({ ...creation, questionLimit: value }, requestId)).toThrow();
  });
  it('requires questionLimit on creation, rather than interpreting absence as unlimited', () => {
    const missing = { ...creation } as Record<string, unknown>; delete missing.questionLimit;
    expect(() => decodeCreation(missing, requestId)).toThrow(GameContractError);
  });
  it.each(['questionLimit', 'remaining', 'both'])('requires session counts: missing %s is not unlimited', missingField => {
    const missing = { ...snapshot, questionLimit: null, remaining: null } as Record<string, unknown>;
    if (missingField !== 'remaining') delete missing.questionLimit;
    if (missingField !== 'questionLimit') delete missing.remaining;
    expect(() => decodeSession(missing, creation.sessionId, 'synthetic')).toThrow(GameContractError);
  });
  it('requires remaining on terminal turns, while explicit null unlimited remains valid', () => {
    const missing = { ...turn } as Record<string, unknown>; delete missing.remaining;
    expect(() => decodeTurn(missing, identity)).toThrow(GameContractError);
    expect(decodeTurn({ ...turn, remaining: null }, identity)).toMatchObject({ remaining: null });
    expect(decodeSession({ ...snapshot, questionLimit: null, remaining: null }, creation.sessionId, 'synthetic')).toMatchObject({ questionLimit: null, remaining: null });
  });
  it('decodes a consistent public session and rejects wrong route identity', () => {
    expect(decodeSession(snapshot, creation.sessionId, 'synthetic').remaining).toBe(2);
    expect(() => decodeSession(snapshot, 'other-session', 'synthetic')).toThrow();
    expect(() => decodeSession(snapshot, creation.sessionId, 'other-soup')).toThrow();
  });
  it.each([
    { remaining: 3 }, { questionsAsked: -1 }, { questionsAsked: true }, { status: 'unknown' },
    { messages: [{ role: 'assistant', content: 'x', timestamp: 1 }] },
    { messages: [{ role: 'host', content: {}, timestamp: 1 }] },
    { messages: [{ role: 'host', content: 'x', timestamp: Infinity }] },
    { evaluation },
  ])('rejects invalid counts, roles and active truth result %j', changed => {
    expect(() => decodeSession({ ...snapshot, ...changed }, creation.sessionId, 'synthetic')).toThrow();
  });
  it('restores immutable ended evaluation; solved may await its first evaluation', () => {
    const ended = decodeSession({ ...snapshot, status: 'given_up', evaluation }, creation.sessionId, 'synthetic');
    expect(ended.evaluation?.verifiedCoverage).toBe(50);
    expect(decodeSession({ ...snapshot, status: 'solved' }, creation.sessionId, 'synthetic').evaluation).toBeNull();
    expect(() => decodeSession({ ...snapshot, status: 'given_up' }, creation.sessionId, 'synthetic')).toThrow();
  });
  it('strips internal fields from public history instead of giving them authority', () => {
    const data = decodeSession({ ...snapshot, messages: snapshot.messages.map(m => ({ ...m, hostResult: { kind: 'win' }, evidenceIds: ['private'] })) }, creation.sessionId, 'synthetic');
    expect(data.messages[0]).not.toHaveProperty('hostResult');
    expect(data.messages[0]).not.toHaveProperty('evidenceIds');
  });
  it('decodes a committed answer and refuses cross-operation or inconsistent state', () => {
    const decoded = decodeTurn(turn, identity);
    expect(decoded.state).toBe('completed');
    expect(decoded.state === 'completed' && decoded.reply).toBe('是');
    for (const change of [{ requestId: 'other' }, { sessionId: 'other' }, { isWin: true }, { isFreeReminder: true }, { kind: 'made_up' }, { remaining: -1 }]) {
      expect(() => decodeTurn({ ...turn, ...change }, identity)).toThrow();
    }
  });
  it('reserved responses carry no invented answer or charge result', () => {
    const reserved = { ...identity, turnId: 'turn', state: 'reserved', code: 'turn_in_progress', detail: '处理中' };
    expect(decodeTurn(reserved, identity).state).toBe('reserved');
    expect(() => decodeTurn({ ...reserved, reply: '是', kind: 'answer' }, identity)).toThrow();
  });
  it('only validated failed/expired free system results establish no charge', () => {
    const failed = { ...turn, state: 'failed', kind: 'system_error', reply: '合成失败', code: 'model_busy', detail: '合成失败', isFreeReminder: true };
    expect(decodeTurn(failed, identity).state).toBe('failed');
    expect(decodeTurn({ ...failed, state: 'expired', code: 'turn_expired' }, identity).state).toBe('expired');
    for (const change of [{ isFreeReminder: false }, { kind: 'answer' }, { code: null }, { state: 'completed' }]) {
      expect(() => decodeTurn({ ...failed, ...change }, identity)).toThrow();
    }
  });
  it('retains full legacy result meaning without minting confirmed coverage', () => {
    const legacy = { completion: 83, evaluation: 'Old', keyPointsCovered: [], keyPointsMissing: [], bottom: 'Old truth' };
    expect(decodeEvaluation(legacy)).toEqual(legacy);
    expect(decodeEvaluation(evaluation)).toEqual(evaluation);
    for (const change of [{ completion: 100 }, { keyPointsCovered: [1] }, { bottom: {} }, { unknownTopics: [false] }, { evaluation: null }]) {
      expect(() => decodeEvaluation({ ...evaluation, ...change })).toThrow();
    }
  });
  it('does not stringify status/kind arrays into valid business enums', () => {
    expect(() => decodeSession({ ...snapshot, status: ['playing'] }, creation.sessionId, 'synthetic')).toThrow(GameContractError);
    expect(() => decodeTurn({ ...turn, state: ['completed'] }, identity)).toThrow(GameContractError);
    expect(() => decodeTurn({ ...turn, kind: ['answer'] }, identity)).toThrow(GameContractError);
  });
  it('classifies inconsistent scores as protocol errors, not lost network replies', () => {
    expect(() => decodeEvaluation({ ...evaluation, completion: 100 })).toThrow(GameContractError);
  });
});
