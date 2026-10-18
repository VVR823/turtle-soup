import { describe, expect, it, vi } from 'vitest';

async function api() {
  vi.resetModules();
  return import('./api');
}

describe('isolated API client', () => {
  it('uses a test-only API origin and carries the site token', async () => {
    const client = await api();
    client.setSiteToken('synthetic-token');
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await client.apiFetch('/api/chat', { method: 'POST', body: '{}' });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://127.0.0.1:18080/api/chat');
    expect(init.headers.get('X-Site-Token')).toBe('synthetic-token');
    expect(init.headers.get('Content-Type')).toBe('application/json');
  });

  it('clears a rejected token and raises the typed authentication error', async () => {
    const client = await api();
    client.setSiteToken('synthetic-token');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 401 })));
    await expect(client.apiFetch('/api/soups')).rejects.toBeInstanceOf(client.ApiAuthError);
    expect(client.getSiteToken()).toBe('');
  });

  it('does not turn 503 into success or clear a still-unknown token', async () => {
    const client = await api();
    client.setSiteToken('synthetic-token');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 503 })));
    expect((await client.apiFetch('/api/soups')).status).toBe(503);
    expect(client.getSiteToken()).toBe('synthetic-token');
  });

  it('round-trips session state without using an existing browser profile', async () => {
    const client = await api();
    const session = { sessionId: 'synthetic-session', soupId: 'xin', level: 'xuermu' };
    client.saveLastSession(session);
    expect(client.getLastSession()).toEqual(session);
    client.saveLastSession(null);
    expect(client.getLastSession()).toBeNull();
  });

  it('rejects corrupt local session data', async () => {
    const client = await api();
    localStorage.setItem('last_session', '{invalid-json');
    expect(client.getLastSession()).toBeNull();
  });

  it('deduplicates unlocked and played soup ids', async () => {
    const client = await api();
    client.addUnlockedSoup('xin');
    client.addUnlockedSoup('xin');
    client.addPlayedSoup('xin');
    client.addPlayedSoup('xin');
    expect(client.getUnlockedSoups()).toEqual(['xin']);
    expect(client.getPlayedSoups()).toEqual(['xin']);
  });

  it('blocks an accidentally unstubbed real fetch', async () => {
    const client = await api();
    await expect(client.apiFetch('/health')).rejects.toThrow('Real fetch is disabled');
  });

  it.each([404, 410, 409, 429, 503])('classifies HTTP%s without treating it as success', async status => {
    const client = await api();
    client.setSiteToken('synthetic-retained');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"code":"synthetic_error","requestId":"owned","detail":"Synthetic"}', { status, headers: { 'Retry-After': '2' } })));
    await expect(client.apiJson('/api/session/owned')).rejects.toMatchObject({ status, code: 'synthetic_error', requestId: 'owned', retryAfterSeconds: 2 });
    expect(client.getSiteToken()).toBe('synthetic-retained');
  });
  it('keeps failed-turn JSON accessible before generic HTTP handling', async () => {
    const client = await api();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"state":"failed"}', { status: 503 })));
    expect(await client.apiResponseJson('/api/session/owned/turns/id')).toMatchObject({ status: 503, ok: false, body: { state: 'failed' } });
  });
  it('does not fabricate an empty object from invalid JSON or network failure', async () => {
    const client = await api();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{broken')));
    await expect(client.apiJson('/api/session/owned')).rejects.toThrow();
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Synthetic lost response')));
    await expect(client.apiJson('/api/chat', { method: 'POST', body: '{}' })).rejects.toThrow('Synthetic lost response');
  });
  it('preserves retry/status metadata even when an error body is not JSON', async () => {
    const client = await api();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('Synthetic proxy unavailable', { status: 429, headers: { 'Retry-After': '2.2' } })));
    await expect(client.apiJson('/api/session/owned')).rejects.toMatchObject({ status: 429, retryAfterSeconds: 3 });
  });
  it('respects an HTTP-date retry window without renewing a request identity', async () => {
    const client = await api();
    vi.spyOn(Date, 'now').mockReturnValue(100_000);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 429, headers: { 'Retry-After': new Date(112_000).toUTCString() } })));
    await expect(client.apiJson('/api/session/owned')).rejects.toMatchObject({ status: 429, retryAfterSeconds: 12 });
  });
  it('late 401 for an old token cannot clear a newly verified token', async () => {
    const client = await api();
    client.setSiteToken('synthetic-old');
    let resolve!: (response: Response) => void;
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise<Response>(finish => { resolve = finish; })));
    const request = client.apiFetch('/api/soups');
    client.setSiteToken('synthetic-new');
    resolve(new Response('{}', { status: 401 }));
    await expect(request).rejects.toBeInstanceOf(client.ApiAuthError);
    expect(client.getSiteToken()).toBe('synthetic-new');
  });
  it('rejecting a prospective token does not erase a different stored token', async () => {
    const client = await api();
    client.setSiteToken('synthetic-current');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 401 })));
    await expect(client.apiFetch('/api/soups', { headers: { 'X-Site-Token': 'synthetic-proposed' } })).rejects.toBeInstanceOf(client.ApiAuthError);
    expect(client.getSiteToken()).toBe('synthetic-current');
  });
});
