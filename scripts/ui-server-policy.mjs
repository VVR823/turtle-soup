/** Fixed-origin UI test policy, independent from production configuration. */
import net from 'node:net';
import fs from 'node:fs';
import { stopFixture } from './fixture-process.mjs';

export const UI_ORIGINS = Object.freeze(['http://127.0.0.1:18080', 'http://127.0.0.1:18081']);
export function assertOwnedOrigins(value) {
  const url = new URL(value);
  if (!UI_ORIGINS.includes(url.origin) || url.username || url.password) throw new Error('Refusing request outside an owned origin');
}
export function validateUiFixtureIdentity(health, expectedId) {
  if (!health || health.status !== 'ok' || health.testing !== true || health.provider !== 'fake'
      || typeof expectedId !== 'string' || !expectedId || health.instanceId !== expectedId) throw new Error('Invalid UI fixture identity');
}
export function assertNoUiOverrides(environment) {
  for (const name of ['TURTLE_SOUP_UI_BASE_URL', 'PLAYWRIGHT_BASE_URL', 'TURTLE_SOUP_UI_BACKEND_URL', 'TURTLE_SOUP_UI_PYTHON', 'TURTLE_SOUP_UI_ORIGIN', 'TURTLE_SOUP_UI_BROWSER_PATH']) {
    if (environment[name] !== undefined) throw new Error(`Forbidden UI override: ${name}`);
  }
}
export async function ensureOwnedPortsFree() {
  for (const port of [18080, 18081]) await new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.once('error', () => reject(new Error(`Owned fixture port ${port} is occupied; no server was reused`)));
    probe.listen(port, '127.0.0.1', () => probe.close(resolve));
  });
}
export function requireBrowserExecutable(candidates, exists = fs.existsSync) {
  for (const candidate of candidates) if (candidate && exists(candidate)) return candidate;
  throw new Error('Installed browser absent: UI not verified; browser download is disabled');
}
export async function stopOwnedUiChildren(entries) {
  const observations = await Promise.allSettled(entries.map(entry => stopFixture(entry.child, entry.finished,
    entry.hasExited ? { hasExited: entry.hasExited } : {})));
  if (observations.some(observation => observation.status !== 'fulfilled' || observation.value.code !== 0)) {
    throw new Error('Owned UI cleanup failed; inspect retained child evidence');
  }
}
