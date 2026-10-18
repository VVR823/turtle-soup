import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const workspace = fileURLToPath(new URL('../../', import.meta.url));
async function policy() {
  const location = new URL('../standalone-release-policy.mjs', import.meta.url);
  assert.ok(fs.existsSync(location), 'Independent standalone package is missing');
  return import(location.href);
}
function fixture() {
  const source = fs.mkdtempSync(path.join(workspace, '.cache', 'ts07-frontend-package-'));
  const target = `${source}-artifact`;
  const put = (name, value = 'SYNTHETIC_CODE') => {
    const full = path.join(source, name);
    fs.mkdirSync(path.dirname(full), { recursive: true });
    fs.writeFileSync(full, value);
  };
  for (const name of ['.next/standalone/server.js', '.next/standalone/package.json',
    '.next/standalone/.next/BUILD_ID', '.next/standalone/node_modules/next/package.json',
    '.next/static/chunks/demo.js', '.next/static/css/demo.css', 'public/demo.svg']) put(name);
  for (const name of ['.env', 'backend/data/sessions.db', 'private/private.json', 'src/private.ts']) put(name, 'PRIVATE_TEST_CANARY');
  return { source, target, put };
}

test('independent package carries actual entry, traced deps, static and public, not source private roots', async () => {
  const api = await policy();
  const f = fixture();
  const manifest = api.packageStandalone(f.source, f.target);
  assert.equal(manifest.schemaVersion, 1);
  assert.equal(manifest.localOnly, true);
  assert.equal(manifest.productionReady, false);
  assert.equal(manifest.dataKind, 'code_only');
  assert.deepEqual(Object.keys(manifest.files).sort(), ['.next/BUILD_ID', '.next/static/chunks/demo.js',
    '.next/static/css/demo.css', 'node_modules/next/package.json', 'package.json', 'public/demo.svg', 'server.js']);
  for (const name of Object.keys(manifest.files)) {
    assert.equal(fs.readFileSync(path.join(f.target, name), 'utf8'), 'SYNTHETIC_CODE');
  }
  for (const name of ['.env', 'backend', 'private', 'src']) assert.equal(fs.existsSync(path.join(f.target, name)), false);
  assert.equal(fs.readFileSync(path.join(f.source, '.env'), 'utf8'), 'PRIVATE_TEST_CANARY');
  assert.deepEqual(api.verifyStandaloneRelease(f.target), manifest);
});

test('existing target sentinel is never overwritten', async () => {
  const api = await policy();
  const f = fixture();
  fs.mkdirSync(f.target);
  fs.writeFileSync(path.join(f.target, 'sentinel'), 'KEEP_EXISTING');
  assert.throws(() => api.packageStandalone(f.source, f.target));
  assert.equal(fs.readFileSync(path.join(f.target, 'sentinel'), 'utf8'), 'KEEP_EXISTING');
});
test('outside output and source overlap cannot receive a package', async () => {
  const api = await policy();
  const f = fixture();
  for (const target of [workspace, f.source, path.join(f.source, 'inside')]) {
    assert.throws(() => api.packageStandalone(f.source, target));
  }
});
for (const missing of ['.next/standalone/server.js', '.next/standalone/.next/BUILD_ID',
  '.next/standalone/node_modules/next/package.json', '.next/static', 'public']) {
  test(`missing required ${missing} refuses before target creation`, async () => {
    const api = await policy();
    const f = fixture();
    fs.renameSync(path.join(f.source, missing), path.join(f.source, 'preserved-missing'));
    assert.throws(() => api.packageStandalone(f.source, f.target));
    assert.equal(fs.existsSync(f.target), false);
  });
}
test('source static junction refuses before target creation', async () => {
  const api = await policy();
  const f = fixture();
  fs.renameSync(path.join(f.source, '.next/static'), path.join(f.source, 'saved-static'));
  fs.symlinkSync(path.join(f.source, 'saved-static'), path.join(f.source, '.next/static'),
    process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => api.packageStandalone(f.source, f.target));
  assert.equal(fs.existsSync(f.target), false);
});

for (const mutation of ['bytes', 'missing', 'extra', 'emptydir', 'schema-bool', 'escape', 'duplicate', 'junction']) {
  test(`standalone receipt refuses ${mutation} tampering`, async () => {
    const api = await policy();
    const f = fixture();
    api.packageStandalone(f.source, f.target);
    const receipt = path.join(f.target, 'release-manifest.json');
    if (mutation === 'bytes') fs.writeFileSync(path.join(f.target, 'server.js'), 'DAMAGED');
    else if (mutation === 'missing') fs.renameSync(path.join(f.target, 'server.js'), path.join(f.source, 'saved-server.js'));
    else if (mutation === 'extra') fs.writeFileSync(path.join(f.target, '.env'), 'PRIVATE_TEST_CANARY');
    else if (mutation === 'emptydir') fs.mkdirSync(path.join(f.target, 'private'));
    else if (mutation === 'duplicate') {
      const bytes = fs.readFileSync(receipt, 'utf8');
      fs.writeFileSync(receipt, bytes.replace('"schemaVersion": 1,', '"schemaVersion": 1,\n  "schemaVersion": 1,'));
    } else if (mutation === 'junction') {
      fs.renameSync(path.join(f.target, 'node_modules'), path.join(f.source, 'saved-modules'));
      fs.symlinkSync(path.join(f.source, 'saved-modules'), path.join(f.target, 'node_modules'),
        process.platform === 'win32' ? 'junction' : 'dir');
    } else {
      const body = JSON.parse(fs.readFileSync(receipt, 'utf8'));
      if (mutation === 'schema-bool') body.schemaVersion = true;
      else body.files['../private'] = '0'.repeat(64);
      fs.writeFileSync(receipt, JSON.stringify(body, null, 2) + '\n');
    }
    assert.throws(() => api.verifyStandaloneRelease(f.target));
  });
}
test('a real selected source change during copying refuses a passed manifest', async () => {
  const api = await policy();
  const f = fixture();
  const source = path.join(f.source, '.next/standalone/server.js');
  const copy = fs.copyFileSync;
  try {
    fs.copyFileSync = (from, to, ...args) => {
      const result = copy(from, to, ...args);
      if (from === source) fs.writeFileSync(source, 'SOURCE_CHANGED_DURING_COPY');
      return result;
    };
    assert.throws(() => api.packageStandalone(f.source, f.target));
  } finally { fs.copyFileSync = copy; }
  assert.equal(fs.existsSync(path.join(f.target, 'release-manifest.json')), false);
});
