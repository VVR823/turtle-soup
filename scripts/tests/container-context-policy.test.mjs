import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { backendReleaseFiles, buildBackendRelease } from '../backend-release-policy.mjs';
import { packageStandalone } from '../standalone-release-policy.mjs';

const project = fs.realpathSync(fileURLToPath(new URL('../../', import.meta.url)));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
async function policy() {
  const url = new URL('../container-context-policy.mjs', import.meta.url);
  assert.ok(fs.existsSync(url), 'Verified container input policy is missing');
  return import(url.href);
}
function put(root, name, bytes = 'SYNTHETIC_CODE') {
  const full = path.join(root, name);
  fs.mkdirSync(path.dirname(full), { recursive: true });
  fs.writeFileSync(full, bytes);
}
function fixture(kind) {
  const root = fs.mkdtempSync(path.join(project, '.cache', 'ts07-frontend-context-'));
  const artifact = `${root}-artifact`, target = `${root}-context`;
  if (kind === 'backend') {
    for (const name of backendReleaseFiles) put(root, name);
    put(root, 'backend/app/soups.py', 'PRIVATE_TEST_CANARY');
    fs.mkdirSync(path.join(root, '.cache'));
    buildBackendRelease(root, path.join(root, '.cache', 'demo'));
    fs.renameSync(path.join(root, '.cache', 'demo'), artifact);
  } else {
    for (const name of ['.next/standalone/server.js', '.next/standalone/package.json',
      '.next/standalone/.next/BUILD_ID', '.next/standalone/node_modules/next/package.json',
      '.next/static/chunks/demo.js', 'public/demo.svg']) put(root, name);
    packageStandalone(root, artifact);
  }
  for (const name of ['.env', 'backend/data/session.db', '.cache/private.json']) put(root, name, 'PRIVATE_TEST_CANARY');
  return { root, artifact, target };
}

for (const kind of ['backend', 'frontend']) {
  test(`${kind} context copies only verified release bytes and remains source-only`, async () => {
    const api = await policy(), f = fixture(kind);
    const receipt = fs.readFileSync(path.join(f.artifact, 'release-manifest.json'));
    const original = JSON.parse(receipt);
    const result = api.buildContainerContext(kind, f.artifact, f.target);
    assert.equal(result.productionReady, false);
    assert.equal(result.containerBuildVerified, false);
    assert.equal(result.sourceManifestDigest, sha(receipt));
    assert.deepEqual(Object.keys(result.files).sort(), [...Object.keys(original.files), 'release-manifest.json'].map(n => `release/${n}`).sort());
    for (const name of Object.keys(result.files)) {
      assert.deepEqual(fs.readFileSync(path.join(f.target, name)), fs.readFileSync(path.join(f.artifact, name.slice(8))));
    }
    assert.deepEqual(fs.readdirSync(f.target).sort(), ['context-manifest.json', 'release']);
    assert.equal(fs.existsSync(path.join(f.target, 'release/.env')), false);
    assert.equal(fs.readFileSync(path.join(f.root, '.env'), 'utf8'), 'PRIVATE_TEST_CANARY');
    assert.deepEqual(api.verifyContainerContext(kind, f.artifact, f.target), result);
  });
}
for (const mutation of ['bytes', 'missing', 'extra', 'empty-directory', 'resealed', 'source', 'junction']) {
  test(`container input refuses ${mutation} rather than signing a misleading receipt`, async () => {
    const api = await policy(), f = fixture('backend');
    api.buildContainerContext('backend', f.artifact, f.target);
    const entry = 'release/backend/app/main.py';
    if (mutation === 'bytes') put(f.target, entry, 'CORRUPT');
    if (mutation === 'missing') fs.unlinkSync(path.join(f.target, entry));
    if (mutation === 'extra') put(f.target, '.env', 'PRIVATE_TEST_CANARY');
    if (mutation === 'empty-directory') fs.mkdirSync(path.join(f.target, 'private'));
    if (mutation === 'source') put(f.artifact, 'backend/app/main.py', 'CORRUPT');
    if (mutation === 'resealed') {
      put(f.target, entry, 'CORRUPT');
      const name = path.join(f.target, 'context-manifest.json');
      const body = JSON.parse(fs.readFileSync(name));
      body.files[entry] = sha(Buffer.from('CORRUPT'));
      fs.writeFileSync(name, JSON.stringify(body, null, 2) + '\n');
    }
    if (mutation === 'junction') {
      fs.renameSync(path.join(f.target, 'release/backend/app'), path.join(f.root, 'redirected-app'));
      fs.symlinkSync(path.join(f.root, 'redirected-app'), path.join(f.target, 'release/backend/app'), process.platform === 'win32' ? 'junction' : 'dir');
    }
    assert.throws(() => api.verifyContainerContext('backend', f.artifact, f.target));
  });
}
test('unsafe targets, existing sentinel and wrong kind refuse before writes', async () => {
  const api = await policy(), f = fixture('backend');
  fs.mkdirSync(f.target);
  put(f.target, 'sentinel', 'KEEP');
  for (const target of [f.target, f.artifact, path.join(f.artifact, 'inside'), project, path.join(project, '.cache')]) {
    assert.throws(() => api.buildContainerContext('backend', f.artifact, target));
  }
  assert.throws(() => api.buildContainerContext('unknown', f.artifact, `${f.target}-new`));
  assert.equal(fs.existsSync(`${f.target}-new`), false);
  assert.equal(fs.readFileSync(path.join(f.target, 'sentinel'), 'utf8'), 'KEEP');
});
test('redirected source and cache ancestor cannot authorize a context', async () => {
  const api = await policy(), f = fixture('backend');
  const link = `${f.artifact}-link`;
  fs.symlinkSync(f.artifact, link, process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => api.buildContainerContext('backend', link, f.target));
  const cacheAlias = path.join(f.root, 'cache-alias');
  fs.symlinkSync(path.join(project, '.cache'), cacheAlias, process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => api.buildContainerContext('backend', f.artifact, path.join(cacheAlias, 'do-not-create')));
  assert.equal(fs.existsSync(f.target), false);
});

test('a real source change during copy refuses without issuing a context receipt', async () => {
  const api = await policy(), f = fixture('backend');
  const originalCopy = fs.copyFileSync;
  let changed = false;
  fs.copyFileSync = function (source, destination, flags) {
    originalCopy.call(fs, source, destination, flags);
    if (!changed) {
      changed = true;
      // Keep real copy side effects; mutate the owned source, not its return.
      put(f.artifact, 'backend/app/main.py', 'CHANGED_DURING_COPY');
    }
  };
  try { assert.throws(() => api.buildContainerContext('backend', f.artifact, f.target)); }
  finally { fs.copyFileSync = originalCopy; }
  assert.equal(changed, true);
  assert.equal(fs.existsSync(path.join(f.target, 'context-manifest.json')), false);
  assert.equal(fs.readFileSync(path.join(f.artifact, 'backend/app/main.py'), 'utf8'), 'CHANGED_DURING_COPY');
});

for (const kind of ['backend', 'frontend']) {
  test(`${kind} input containing private canary is refused before creating output`, async () => {
    const api = await policy(), f = fixture(kind);
    put(f.artifact, '.env', 'PRIVATE_TEST_CANARY');
    assert.throws(() => api.buildContainerContext(kind, f.artifact, f.target));
    assert.equal(fs.existsSync(f.target), false);
  });
}
