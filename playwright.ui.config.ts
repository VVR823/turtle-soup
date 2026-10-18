import { defineConfig } from '@playwright/test';
import fs from 'node:fs';

if (process.env.TURTLE_SOUP_UI_TESTING !== '1' || !process.env.TURTLE_SOUP_TEST_INSTANCE_ID
  || !process.env.TURTLE_SOUP_UI_BROWSER_PATH || !fs.existsSync(process.env.TURTLE_SOUP_UI_BROWSER_PATH)) {
  throw new Error('Use npm run test:ui: owned synthetic servers and an installed browser are required');
}
const nonce = process.env.TURTLE_SOUP_TEST_INSTANCE_ID;
if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(nonce)) {
  throw new Error('Owned canonical UI nonce required');
}
const reportRoot = `.cache/ui-runs/${nonce}`;
export default defineConfig({
  testDir: './tests/ui', outputDir: `${reportRoot}/results`,
  reporter: [['list'], ['junit', { outputFile: `${reportRoot}/junit.xml` }]],
  workers: 1, retries: 0, timeout: 20_000, globalTimeout: 180_000,
  use: {
    baseURL: 'http://127.0.0.1:18081', serviceWorkers: 'block',
    launchOptions: { executablePath: process.env.TURTLE_SOUP_UI_BROWSER_PATH },
    screenshot: 'only-on-failure', trace: 'retain-on-failure',
  },
});
