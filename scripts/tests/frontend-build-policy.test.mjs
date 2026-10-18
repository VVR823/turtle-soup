import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { createSterileFrontend, frontendEnvironment } from '../frontend-build-policy.mjs';

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ts07-build-policy-'));
  // Only this generated synthetic fixture is recursively cleaned; never a
  // repository/cache root, user directory or an unresolved computed path.
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  function put(name, contents = 'synthetic') {
    const target = path.join(root, name);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, contents);
  }
  for (const name of ['package.json', 'package-lock.json', 'tsconfig.json', 'next.config.ts', 'postcss.config.mjs']) put(name, '{}');
  put('node_modules/installed/package.json', '{}');
  return { root, put, cache: path.join(root, '.cache') };
}

test('sterile copy includes public source/config/assets but excludes private files and test code', t => {
  const f = fixture(t);
  f.put('src/app/page.tsx', 'public-page');
  f.put('src/lib/logic.ts', 'public-logic');
  f.put('public/icon.svg', '<svg/>');
  f.put('src/lib/logic.test.ts', 'unit-test');
  for (const name of ['.env', '.env.local', 'backend/data/users.db', 'data/feedback.json', '.git/config',
    'src/.env', 'src/private/secret.ts', 'src/data/secret.json', 'public/.env', 'public/secret.txt']) f.put(name, 'do-not-copy');
  const output = createSterileFrontend(f.root, f.cache);
  assert.equal(fs.readFileSync(path.join(output, 'src/app/page.tsx'), 'utf8'), 'public-page');
  assert.equal(fs.readFileSync(path.join(output, 'public/icon.svg'), 'utf8'), '<svg/>');
  for (const name of ['.env', '.env.local', 'backend', 'data', '.git', 'src/.env', 'src/private', 'src/data',
    'public/.env', 'public/secret.txt', 'src/lib/logic.test.ts']) assert.equal(fs.existsSync(path.join(output, name)), false, name);
  assert.equal(fs.realpathSync(path.join(output, 'node_modules')), fs.realpathSync(path.join(f.root, 'node_modules')));
});

test('source directory junction cannot copy an outside tree', t => {
  const f = fixture(t);
  f.put('outside/secret.ts', 'private');
  fs.mkdirSync(path.join(f.root, 'src'), { recursive: true });
  fs.symlinkSync(path.join(f.root, 'outside'), path.join(f.root, 'src/escaped'), process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => createSterileFrontend(f.root, f.cache), /link|redirect/i);
});

test('cache may not resolve outside intended project', t => {
  const f = fixture(t);
  assert.throws(() => createSterileFrontend(f.root, path.dirname(f.root)), /cache|outside/i);
});

test('inherited credentials, preload and production URLs are absent from build environment', () => {
  const env = frontendEnvironment({ PATH: 'synthetic-path', SystemRoot: 'synthetic-system',
    OPENAI_API_KEY: 'private', NEXT_PUBLIC_API_BASE: 'https://production.invalid', NODE_OPTIONS: '--require private.js',
    LANGSMITH_API_KEY: 'private', ADMIN_PASSWORD: 'private' });
  assert.equal(env.PATH, 'synthetic-path');
  assert.equal(env.NEXT_PUBLIC_API_BASE, 'http://127.0.0.1:18080');
  assert.equal(env.NEXT_TELEMETRY_DISABLED, '1');
  assert.equal(env.NODE_ENV, 'production');
  assert.equal(env.OPENAI_API_KEY, undefined);
  assert.equal(env.NODE_OPTIONS, undefined);
  assert.equal(env.LANGSMITH_API_KEY, undefined);
  assert.equal(env.ADMIN_PASSWORD, undefined);
});

test('actual postcss js configuration works without an mjs variant', t => {
  const f = fixture(t);
  // Remove only this generated fixture file, never a project configuration.
  fs.unlinkSync(path.join(f.root, 'postcss.config.mjs'));
  f.put('postcss.config.js', 'module.exports = { plugins: {} };');
  const output = createSterileFrontend(f.root, f.cache);
  assert.equal(fs.readFileSync(path.join(output, 'postcss.config.js'), 'utf8'), 'module.exports = { plugins: {} };');
});

test('repository cjs PostCSS plugin config is preserved, not silently omitted', t => {
  const f = fixture(t);
  fs.unlinkSync(path.join(f.root, 'postcss.config.mjs'));
  f.put('postcss.config.cjs', "module.exports = { plugins: { '@tailwindcss/postcss': {} } };");
  const output = createSterileFrontend(f.root, f.cache);
  assert.equal(fs.readFileSync(path.join(output, 'postcss.config.cjs'), 'utf8'),
    "module.exports = { plugins: { '@tailwindcss/postcss': {} } };");
});
