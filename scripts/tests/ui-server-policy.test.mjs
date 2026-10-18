import assert from 'node:assert/strict';
import test from 'node:test';
import net from 'node:net';
import * as policy from '../ui-server-policy.mjs';
const { assertOwnedOrigins, validateUiFixtureIdentity, ensureOwnedPortsFree, assertNoUiOverrides, stopOwnedUiChildren, requireBrowserExecutable } = policy;

test('UI requests may reach only the exact two owned origins', () => {
  for (const url of ['http://127.0.0.1:18080/api/session/owned', 'http://127.0.0.1:18081/game/synthetic']) assertOwnedOrigins(url);
  for (const url of ['https://example.com/api/chat', 'http://localhost:18080/api/chat', 'http://127.0.0.1:8000', 'http://127.0.0.1:18080@evil.test/', 'file:///D:/CODE/private']) {
    assert.throws(() => assertOwnedOrigins(url), /owned origin/);
  }
});
test('fixture health must prove matching instance, testing mode and fake provider', () => {
  const health = { status: 'ok', testing: true, instanceId: 'synthetic-owned', provider: 'fake' };
  validateUiFixtureIdentity(health, 'synthetic-owned');
  for (const changed of [{ instanceId: 'foreign' }, { testing: false }, { provider: 'openai' }, { status: 'bad' }]) {
    assert.throws(() => validateUiFixtureIdentity({ ...health, ...changed }, 'synthetic-owned'), /fixture identity/);
  }
});
test('an occupied fixture port fails before sending HTTP or reusing its server', async () => {
  const server = net.createServer();
  await new Promise(resolve => server.listen(18081, '127.0.0.1', resolve));
  let connections = 0; server.on('connection', () => { connections++; });
  try { await assert.rejects(ensureOwnedPortsFree(), /18081/); assert.equal(connections, 0); }
  finally { await new Promise(resolve => server.close(resolve)); }
});
test('production URL and executable override inputs are forbidden, not silently reused', () => {
  assertNoUiOverrides({});
  for (const name of ['TURTLE_SOUP_UI_BASE_URL', 'PLAYWRIGHT_BASE_URL', 'TURTLE_SOUP_UI_BACKEND_URL', 'TURTLE_SOUP_UI_PYTHON']) {
    assert.throws(() => assertNoUiOverrides({ [name]: 'https://example.com' }), /override/);
  }
});
test('missing installed browser reports not verified and never downloads one', () => {
  assert.throws(() => requireBrowserExecutable(['synthetic-missing'], () => false), /browser.*not verified/i);
  assert.equal(requireBrowserExecutable(['synthetic-missing', 'synthetic-installed'], value => value === 'synthetic-installed'), 'synthetic-installed');
});
test('both owned children are stopped even if one already failed', async () => {
  const ended = [];
  const entries = [1, 0].map((code, index) => ({ child: { stdin: { end() { ended.push(index); } } }, finished: Promise.resolve({ code }) }));
  await assert.rejects(stopOwnedUiChildren(entries), /cleanup/);
  assert.deepEqual(ended.sort(), [0, 1]);
});
test('normal pair cleanup requires both normal exits and never a foreign kill', async () => {
  const entries = [0, 1].map(() => ({ child: { stdin: { end() {} } }, finished: Promise.resolve({ code: 0 }) }));
  await stopOwnedUiChildren(entries);
});
