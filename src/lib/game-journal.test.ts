import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearPending, newRequestId, readPending, readSavedSession, sameOperation, writePending } from './game-journal';

const target = { soupId: 'synthetic', level: 'xuermu' };
const requestId = '29ab9f58-d899-41dd-a2ab-8e7b3667c9f1';
const creation = { ...target, kind: 'create' as const, requestId };
const ask = { ...target, kind: 'ask' as const, requestId, sessionId: 'owned', question: '合成问题吗' };

beforeEach(() => localStorage.clear());

describe('durable owned operation journal', () => {
  it('round-trips creation identity before a request can send', () => {
    writePending(creation);
    expect(readPending(target)).toEqual(creation);
    expect(sameOperation(creation, readPending(target)!)).toBe(true);
  });
  it('preserves original question and UUID rather than silently changing payload', () => {
    writePending(ask);
    expect(readPending(target)).toEqual(ask);
    expect(() => writePending({ ...ask, question: '不同的问题吗' })).toThrow();
    expect(readPending(target)).toEqual(ask);
  });
  it('uses an unambiguous route key, including slash and query punctuation', () => {
    writePending({ ...creation, soupId: 'a/b', level: 'c' });
    writePending({ ...creation, soupId: 'a', level: 'b/c' });
    expect(readPending({ soupId: 'a/b', level: 'c' })?.soupId).toBe('a/b');
    expect(readPending({ soupId: 'a', level: 'b/c' })?.soupId).toBe('a');
  });
  it('stale completion cannot remove a newer operation', () => {
    writePending(creation);
    expect(clearPending(creation)).toBe(true);
    writePending(ask);
    expect(clearPending(creation)).toBe(false);
    expect(readPending(target)).toEqual(ask);
  });
  it('reveal identity is per session and persisted for lost response recovery', () => {
    const reveal = { ...target, kind: 'reveal' as const, sessionId: 'owned' };
    writePending(reveal);
    expect(readPending(target)).toEqual(reveal);
    expect(sameOperation(reveal, { ...reveal, sessionId: 'other' })).toBe(false);
  });
  it('does not overwrite corrupt or future-version journal data', () => {
    writePending(creation);
    const key = localStorage.key(0)!;
    for (const raw of ['{broken', JSON.stringify({ version: 2, operation: creation }), JSON.stringify({ version: 1, operation: { ...creation, requestId: 'not-uuid' } })]) {
      localStorage.setItem(key, raw);
      expect(() => readPending(target)).toThrow();
      expect(() => writePending(creation)).toThrow();
      expect(localStorage.getItem(key)).toBe(raw);
    }
  });
  it('storage failure is visible; no in-memory success or invented request', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('Synthetic quota exceeded', 'QuotaExceededError'); });
    expect(() => writePending(creation)).toThrow('保存');
    expect(readPending(target)).toBeNull();
  });
  it('does not hide inaccessible storage as an empty journal', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new DOMException('Synthetic access blocked', 'SecurityError'); });
    expect(() => readPending(target)).toThrow();
  });
  it('rejects invalid input before writing and keeps original data', () => {
    for (const invalid of [{ ...creation, requestId: 'bad' }, { ...ask, question: '' }, { ...ask, question: 'x'.repeat(501) }]) {
      expect(() => writePending(invalid)).toThrow();
    }
    expect(localStorage.length).toBe(0);
  });
  it('strictly reads an old saved pointer without rewriting or discarding it', () => {
    const saved = { ...target, sessionId: 'legacy-id' };
    localStorage.setItem('last_session', JSON.stringify(saved));
    expect(readSavedSession()).toEqual(saved);
    for (const raw of ['{broken', JSON.stringify({ ...saved, level: 3 }), JSON.stringify({ ...saved, sessionId: '' })]) {
      localStorage.setItem('last_session', raw);
      expect(() => readSavedSession()).toThrow();
      expect(localStorage.getItem('last_session')).toBe(raw);
    }
  });
  it('gets request UUIDs from browser crypto, not time or retry counters', () => {
    expect(newRequestId()).toMatch(/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/);
    expect(newRequestId()).not.toBe(newRequestId());
  });
  it('reports unsupported browser UUID generation without an unsafe fallback', () => {
    vi.stubGlobal('crypto', {});
    expect(() => newRequestId()).toThrow('编号');
    expect(localStorage.length).toBe(0);
  });
});
