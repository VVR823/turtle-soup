import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { buildBackendRelease } from '../backend-release-policy.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
async function smoke() {
  const location = new URL('../test-backend-release.mjs', import.meta.url);
  assert.ok(fs.existsSync(location), 'Fresh-process backend artifact smoke is missing');
  return import(location.href);
}
function paths() {
  const parent = fs.mkdtempSync(path.join(root, '.cache', 'ts17-smoke-'));
  // Each target is a NEW direct cache child, not nested in an arbitrary tree.
  return { target: `${parent}-artifact`, data: `${parent}-data`, parent };
}

test('fresh isolated process serves the actual demo artifact and closes its owners', async () => {
  const api = await smoke();
  const f = paths();
  buildBackendRelease(root, f.target);
  const result = await api.probeBackendRelease(f.target, f.data);
  assert.deepEqual(result, { status: 'passed', localOnly: true, productionReady: false,
    dataKind: 'synthetic_demo', health: true, publicSeed: true, chatReplay: true,
    moduleOriginsVerified: true, fixedSuiteSourcesVerified: true,
    ownedResourcesClosed: true, networkAttempts: 0 });
  assert.equal(fs.existsSync(path.join(f.data, 'sessions.db')), true);
});

test('smoke never overwrites an existing data directory', async () => {
  const api = await smoke();
  const f = paths();
  buildBackendRelease(root, f.target);
  fs.mkdirSync(f.data);
  fs.writeFileSync(path.join(f.data, 'sentinel'), 'KEEP_EXISTING');
  await assert.rejects(api.probeBackendRelease(f.target, f.data));
  assert.equal(fs.readFileSync(path.join(f.data, 'sentinel'), 'utf8'), 'KEEP_EXISTING');
});

test('smoke refuses non-sibling data without creating it', async () => {
  const api = await smoke();
  const f = paths();
  buildBackendRelease(root, f.target);
  const forbidden = path.join(f.target, 'backend', 'data');
  await assert.rejects(api.probeBackendRelease(f.target, forbidden));
  assert.equal(fs.existsSync(forbidden), false);
});

test('damaged artifact cannot start a child or create its data directory', async () => {
  const api = await smoke();
  const f = paths();
  buildBackendRelease(root, f.target);
  fs.writeFileSync(path.join(f.target, 'backend/app/main.py'), 'raise RuntimeError("DAMAGED")');
  await assert.rejects(api.probeBackendRelease(f.target, f.data));
  assert.equal(fs.existsSync(f.data), false);
});
