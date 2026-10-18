import test from 'node:test';
import assert from 'node:assert/strict';
import { ESLint } from 'eslint';

test('lint ignores backend and runtime/cache roots without hiding frontend or harness code', async () => {
  const lint = new ESLint();
  for (const name of ['backend/app/main.py', 'backend/.venv-ts01/Lib/private.js', '.cache/probe.js', '.pytest_cache/probe.js', 'data/private.js', '.venv/probe.js', 'dist/dev/types/validator.ts']) {
    assert.equal(await lint.isPathIgnored(name), true, name);
  }
  for (const name of ['src/lib/game-controller.ts', 'scripts/e2e-server.mjs', 'scripts/tests/lint-boundary.test.mjs', 'tests/e2e/api-smoke.spec.ts', 'eslint.config.mjs']) {
    assert.equal(await lint.isPathIgnored(name), false, name);
  }
});
