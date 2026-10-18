import { describe, expect, it, vi } from 'vitest';
import { loadPublicCatalog } from './catalog';
import { addUnlockedSoup, getSiteToken } from './api';

const soup = { id: 'synthetic', title: 'Public', surface: 'Public story', tags: ['合成'], difficulty: 2, hidden: true,
  unlimited: true, difficultyLimits: null };

describe('truthful public directory transport', () => {
  it('uses encoded unlocked choices and query without reading private fields', async () => {
    addUnlockedSoup('egg/a?b');
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ soups: [{ ...soup, bottom: 'must-not-be-exported' }] })));
    vi.stubGlobal('fetch', fetchMock);
    const result = await loadPublicCatalog({ query: '合成 & 汤' });
    const url = new URL(fetchMock.mock.calls[0][0]);
    expect(url.searchParams.get('unlocked')).toBe('egg/a?b');
    expect(url.searchParams.get('q')).toBe('合成 & 汤');
    expect(result[0].hidden).toBe(true);
    expect(result[0]).not.toHaveProperty('bottom');
  });
  it('validates an explicit prospective token without saving it', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ soups: [] })));
    vi.stubGlobal('fetch', fetchMock);
    await loadPublicCatalog({ token: 'synthetic-proposed' });
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get('X-Site-Token')).toBe('synthetic-proposed');
    expect(getSiteToken()).toBe('');
  });
  it('only successful valid empty arrays mean there are no soups', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"soups":[]}')));
    expect(await loadPublicCatalog()).toEqual([]);
  });
  it.each([{}, [], { soups: null }, { soups: [{}] }, { soups: [{ ...soup, tags: [1] }] }, { soups: [{ ...soup, difficulty: '2' }] }])('refuses malformed directory %j', async body => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body))));
    await expect(loadPublicCatalog()).rejects.toThrow();
  });
  it.each([401, 404, 410, 409, 429, 503])('does not convert HTTP%s to an empty list', async status => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"detail":"Synthetic error"}', { status })));
    await expect(loadPublicCatalog()).rejects.toThrow();
  });
  it('propagates abort and network failure and refuses invalid JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Synthetic network failure')));
    await expect(loadPublicCatalog()).rejects.toThrow();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{invalid')));
    await expect(loadPublicCatalog()).rejects.toThrow();
  });
});
