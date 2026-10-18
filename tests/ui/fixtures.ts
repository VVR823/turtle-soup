import { test as base, expect } from '@playwright/test';
import { assertOwnedOrigins, validateUiFixtureIdentity } from '../../scripts/ui-server-policy.mjs';

export const API = 'http://127.0.0.1:18080';
export const test = base.extend<{ owned: void }>({
  owned: [async ({ context, request }, use) => {
    // The launcher owns sterile frontend/API processes; verify that instance
    // before use, then block browser requests outside the two owned origins.
    // Service workers are blocked by the UI config so routes remain observable.
    const health = await request.get(`${API}/health`, { maxRedirects: 0 });
    expect(health.ok()).toBeTruthy();
    validateUiFixtureIdentity(await health.json(), process.env.TURTLE_SOUP_TEST_INSTANCE_ID!);
    await context.route('**/*', async route => {
      try { assertOwnedOrigins(route.request().url()); }
      catch { await route.abort('blockedbyclient'); return; }
      await route.continue();
    });
    await use();
  }, { auto: true }],
});
export { expect };
