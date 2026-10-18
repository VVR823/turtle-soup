import { expect, test } from 'vitest';
import { normalizeEvaluationDisplay } from './evaluation';

const current = { completion: 50, verifiedCoverage: 50, reconstructionScore: null,
  scoreVersion: 'coverage-v1', plotProgress: null, unknownTopics: [] };

test('new result means confirmed fact coverage, never reconstruction', () => {
  expect(normalizeEvaluationDisplay(current)).toEqual({
    coverageValue: 50, coverageLabel: '已确认事实覆盖',
    reconstructionLabel: '尚未独立评估', plotValue: null,
  });
});

test('real narrative win does not replace zero fact coverage', () => {
  expect(normalizeEvaluationDisplay({ ...current, completion: 0, verifiedCoverage: 0, plotProgress: 100 })).toEqual({
    coverageValue: 0, coverageLabel: '已确认事实覆盖',
    reconstructionLabel: '尚未独立评估', plotValue: 100,
  });
});

test.each([undefined, null])('old stored score is clearly old, version=%s', (scoreVersion) => {
  expect(normalizeEvaluationDisplay({ completion: 83, scoreVersion })).toEqual({
    coverageValue: 83, coverageLabel: '历史分数（旧口径）',
    reconstructionLabel: '尚未独立评估', plotValue: null,
  });
});

test('null default fields on old replay do not magically upgrade it', () => {
  expect(normalizeEvaluationDisplay({ ...current, completion: 83, verifiedCoverage: null, scoreVersion: null })
    .coverageLabel).toBe('历史分数（旧口径）');
});

test.each([
  { ...current, completion: 100 }, { ...current, verifiedCoverage: null },
  { ...current, verifiedCoverage: '50' }, { ...current, completion: true, verifiedCoverage: true },
  { ...current, completion: -1, verifiedCoverage: -1 }, { ...current, plotProgress: 101 },
  { ...current, reconstructionScore: 100 }, { ...current, scoreVersion: 'unknown' },
  { completion: 100, verifiedCoverage: 100 }, { ...current, completion: 1.5, verifiedCoverage: 1.5 },
  { ...current, plotProgress: Number.NaN }, { ...current, plotProgress: true },
  { ...current, scoreVersion: null, verifiedCoverage: null, plotProgress: 100 },
  null, undefined,
])('malformed score is refused, not displayed as a perfect score: %j', (input) => {
  expect(() => normalizeEvaluationDisplay(input)).toThrow();
});
