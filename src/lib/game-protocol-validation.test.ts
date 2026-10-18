import { expect, test } from 'vitest';
import { decodeCreation, decodeEvaluation, decodeSession, decodeTurn, GameContractError } from './game-contract';

const requestId = 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa';
const identity = { sessionId: 'synthetic-session', requestId };
const evaluation = () => ({ completion: 50, evaluation: '合成旧版评语', keyPointsCovered: ['A'],
  keyPointsMissing: ['B'], bottom: '合成汤底' });
const turn = () => ({ ...identity, turnId: 'synthetic-turn', state: 'completed', kind: 'answer', reply: '是',
  remaining: 2, isFreeReminder: false, isWin: false, isReveal: false, isGiveup: false, limitReached: false });

test.each([null, [], false, 'session'])('a non-object creation body grants no new session: %j', value => {
  expect(() => decodeCreation(value, requestId)).toThrow(GameContractError);
});

test.each(['keyPointsCovered', 'keyPointsMissing'] as const)('evaluation %s must be an array rather than text', field => {
  expect(() => decodeEvaluation({ ...evaluation(), [field]: 'invented list' })).toThrow(GameContractError);
});

test.each([undefined, null])('unversioned evaluation refuses unknown-topic claims (scoreVersion=%s)', scoreVersion => {
  expect(() => decodeEvaluation({ ...evaluation(), scoreVersion, unknownTopics: ['未核验结论'] })).toThrow(GameContractError);
});

test('legacy evaluation may explicitly preserve an empty unknown-topic list', () => {
  expect(decodeEvaluation({ ...evaluation(), unknownTopics: [] }).unknownTopics).toEqual([]);
});

test.each([null, {}, 'history'])('session messages must be an array: %j', messages => {
  const session = { sessionId: identity.sessionId, soupId: 'synthetic', status: 'playing', questionLimit: 3,
    questionsAsked: 0, remaining: 3, messages, evaluation: null };
  expect(() => decodeSession(session, identity.sessionId, 'synthetic')).toThrow(GameContractError);
});

test.each([{ code: 'model_timeout' }, { detail: 'synthetic server error' }])(
  'a completed answer cannot simultaneously carry failure metadata %j', change => {
    expect(() => decodeTurn({ ...turn(), ...change }, identity)).toThrow(GameContractError);
  },
);

test.each([{ kind: 'answer', isFreeReminder: false, remaining: 0 },
  { kind: 'reminder', isFreeReminder: true, remaining: 2 }])('limitReached requires a reminder with exactly zero remaining %j', change => {
  expect(() => decodeTurn({ ...turn(), ...change, limitReached: true }, identity)).toThrow(GameContractError);
});

test('a valid limit reminder is preserved without claiming that a question was charged', () => {
  expect(decodeTurn({ ...turn(), kind: 'reminder', isFreeReminder: true, remaining: 0, limitReached: true }, identity))
    .toMatchObject({ kind: 'reminder', isFreeReminder: true, remaining: 0, limitReached: true });
});
