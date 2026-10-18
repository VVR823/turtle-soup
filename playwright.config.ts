import { defineConfig } from '@playwright/test';

if (!process.env.TURTLE_SOUP_TEST_INSTANCE_ID) {
  throw new Error('Use npm run test:e2e so the runner owns the temporary fixture');
}

// TS-01 is an API-only harness: no production URL, browser profile or model.
// Game UI/refresh/approval journeys are added at TS-08/15.
export default defineConfig({
  testDir: './tests/e2e',
  workers: 1,
  retries: 0,
  timeout: 10_000,
  globalTimeout: 30_000,
  use: { baseURL: 'http://127.0.0.1:18080' },
});
