import { expect, test, vi } from 'vitest';
import { addPlayedSoup, addUnlockedSoup, clearSiteToken, clearUnlockedSoups, getLastSession,
  getPlayedSoups, getSiteToken, getUnlockedSoups, saveLastSession, setSiteToken } from './api';

const saved = { sessionId: 'synthetic-owned', soupId: 'synthetic', level: 'xuermu' };
const readers = [
  { key: 'unlocked_soups', read: getUnlockedSoups },
  { key: 'played_soups', read: getPlayedSoups },
];

test('server-side storage fallbacks neither read nor mutate a browser game pointer', () => {
  setSiteToken('synthetic-token'); saveLastSession(saved);
  addUnlockedSoup('synthetic-unlocked'); addPlayedSoup('synthetic-played');
  const storage = localStorage;
  const before = Object.fromEntries(Array.from({ length: storage.length }, (_, index) => {
    const key = storage.key(index)!; return [key, storage.getItem(key)];
  }));
  vi.stubGlobal('window', undefined);
  try {
    expect(getSiteToken()).toBe(''); expect(getLastSession()).toBeNull();
    expect(getUnlockedSoups()).toEqual([]); expect(getPlayedSoups()).toEqual([]);
    setSiteToken('other'); clearSiteToken(); saveLastSession(null);
    addUnlockedSoup('other'); clearUnlockedSoups(); addPlayedSoup('other');
    expect(Object.fromEntries(Array.from({ length: storage.length }, (_, index) => {
      const key = storage.key(index)!; return [key, storage.getItem(key)];
    }))).toEqual(before);
  } finally { vi.unstubAllGlobals(); }
  expect(getLastSession()).toEqual(saved);
  expect(getSiteToken()).toBe('synthetic-token');
});

for (const { key, read } of readers) {
  test.each(['{broken', 'null', '{}', '4', '"not-an-array"'])(`${key} damaged value %s returns no choices without deleting its source`, raw => {
    localStorage.setItem(key, raw);
    expect(read()).toEqual([]);
    expect(localStorage.getItem(key)).toBe(raw);
  });
  test(`${key} ignores non-string entries without rewriting stored history`, () => {
    const raw = JSON.stringify(['synthetic-a', 4, null, {}, 'synthetic-b']);
    localStorage.setItem(key, raw);
    expect(read()).toEqual(['synthetic-a', 'synthetic-b']);
    expect(localStorage.getItem(key)).toBe(raw);
  });
}

test.each([
  { key: 'unlocked_soups', read: getUnlockedSoups, expected: [] },
  { key: 'played_soups', read: getPlayedSoups, expected: [] },
  { key: 'last_session', read: getLastSession, expected: null },
])('$key storage denial preserves the raw value and other authentication state', ({ key, read, expected }) => {
  setSiteToken('synthetic-token'); localStorage.setItem(key, 'synthetic-original');
  const original = Storage.prototype.getItem;
  const blocked = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(function (this: Storage, name) {
    if (name === key) throw new DOMException('Synthetic storage denial', 'SecurityError');
    return original.call(this, name);
  });
  try { expect(read()).toEqual(expected); expect(getSiteToken()).toBe('synthetic-token'); }
  finally { blocked.mockRestore(); }
  expect(localStorage.getItem(key)).toBe('synthetic-original');
});

test.each([null, {}, { ...saved, sessionId: 4 }, { ...saved, soupId: null }])('invalid saved pointer %j is refused without clearing history', value => {
  const raw = JSON.stringify(value);
  localStorage.setItem('last_session', raw);
  expect(getLastSession()).toBeNull();
  expect(localStorage.getItem('last_session')).toBe(raw);
});

test('clearing unlocked choices preserves the session, authentication and played history', () => {
  saveLastSession(saved); setSiteToken('synthetic-token');
  addUnlockedSoup('synthetic-unlocked'); addPlayedSoup('synthetic-played');
  clearUnlockedSoups();
  expect(getUnlockedSoups()).toEqual([]);
  expect(getLastSession()).toEqual(saved);
  expect(getSiteToken()).toBe('synthetic-token');
  expect(getPlayedSoups()).toEqual(['synthetic-played']);
});
