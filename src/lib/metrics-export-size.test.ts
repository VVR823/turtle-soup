import { expect, test } from 'vitest';
import { metricKeys, readMetricsExport } from './metrics-contract';
import { metricsExport } from '../../tests/frontend/metrics-fixtures';

test.each(['escaped', 'unicode'])('100 legal export groups retain their exact identifiers and remain below the byte cap: %s', kind => {
  const data = metricsExport();
  data.summary.counts.sessionsCreated = 100;
  data.groups = Array.from({ length: 100 }, (_, index) => ({
    ...data.groups[0],
    soupId: (kind === 'escaped' ? '\u0000' : '😀').repeat(197) + String(index).padStart(3, '0'),
    counts: { ...data.groups[0].counts, sessionsCreated: 1 },
  }));
  const result = readMetricsExport(data);
  expect(result.groups).toEqual(data.groups);
  expect(result.groups).toHaveLength(100);
  expect(new TextEncoder().encode(JSON.stringify(result)).byteLength).toBeLessThan(512 * 1024);
});

test('a conservative serialized group bound leaves the 512KiB guard redundant under the current closed schema', () => {
  // Every code point serializes to at most six ASCII bytes (JSON escapes).
  // Version fields are ASCII; each nonnegative safe integer is <=16 digits.
  const envelope = { day: '9999-12-31', soupId: '', puzzleVersion: '', ruleVersion: '',
    counts: Object.fromEntries(metricKeys.map(key => [key, 0])) };
  const groupUpperBound = new TextEncoder().encode(JSON.stringify(envelope)).byteLength
    + 200 * 6 + 2 * 67 + metricKeys.length * 16;
  // 16KiB conservatively bounds the fixed closed summary/coverage/filter fields.
  expect(groupUpperBound).toBeLessThan(2048);
  expect(100 * groupUpperBound + 16 * 1024).toBeLessThan(512 * 1024);
});
