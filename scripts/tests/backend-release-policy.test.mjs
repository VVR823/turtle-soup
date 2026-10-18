import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const workspace = fileURLToPath(new URL('../../', import.meta.url));
async function policy() {
  const location = new URL('../backend-release-policy.mjs', import.meta.url);
  assert.ok(fs.existsSync(location), 'LOCAL backend release policy is missing');
  return import(location.href);
}
function fixture(api) {
  const parent = path.join(workspace, '.cache', 'ts17', 'release-fixtures');
  fs.mkdirSync(parent, { recursive: true });
  const root = fs.mkdtempSync(path.join(parent, 'case-'));
  const put = (name, value = 'PUBLIC_SYNTHETIC_SOURCE') => {
    const output = path.join(root, name);
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, value);
  };
  for (const name of api.backendReleaseFiles) put(name);
  for (const name of ['backend/app/soups.py', 'backend/app/soups_backup_20261005.py',
    'backend/app/_deploy_check.py', 'backend/app/test_server.py', 'backend/.env', '.env',
    'backend/data/sessions.db', 'backend/data/sessions.db-wal', 'backend/data/feedback.jsonl',
    'backend/eval/tests/case.json', 'backend/eval/datasets/private.json', 'backend/.venv/key', '.git/config']) {
    put(name, 'PRIVATE_TEST_CANARY');
  }
  fs.mkdirSync(path.join(root, '.cache'));
  return { root, put, target: path.join(root, '.cache', 'ts17-backend-demo') };
}

test('backend artifact includes real runtime modules and generated seed, not private inputs', async () => {
  const api = await policy();
  const f = fixture(api);
  const built = api.buildBackendRelease(f.root, f.target);
  assert.equal(built.localOnly, true);
  assert.equal(built.productionReady, false);
  assert.equal(built.dataKind, 'synthetic_demo');
  for (const name of ['backend/app/main.py', 'backend/app/db.py', 'backend/app/agents/worker.py',
    'backend/app/routers/admin_candidates.py', 'backend/eval/manifest.py', 'backend/uv.lock']) {
    assert.equal(fs.readFileSync(path.join(f.target, name), 'utf8'), 'PUBLIC_SYNTHETIC_SOURCE');
  }
  const seed = fs.readFileSync(path.join(f.target, 'backend/app/soups.py'), 'utf8');
  assert.ok(seed.includes('demo-synthetic'));
  assert.ok(!seed.includes('PRIVATE_TEST_CANARY'));
  assert.equal(fs.readFileSync(path.join(f.root, 'backend/app/soups.py'), 'utf8'), 'PRIVATE_TEST_CANARY');
  for (const name of ['backend/data', 'backend/.env', 'backend/.venv', 'backend/app/_deploy_check.py',
    'backend/app/test_server.py', 'backend/app/soups_backup_20261005.py', 'backend/eval/tests', 'backend/eval/datasets', '.git']) {
    assert.equal(fs.existsSync(path.join(f.target, name)), false, name);
  }
  assert.deepEqual(api.verifyBackendRelease(f.target), built);
});

test('existing release files cannot be overwritten', async () => {
  const api = await policy();
  const f = fixture(api);
  fs.mkdirSync(f.target);
  fs.writeFileSync(path.join(f.target, 'sentinel'), 'KEEP_EXISTING');
  assert.throws(() => api.buildBackendRelease(f.root, f.target));
  assert.equal(fs.readFileSync(path.join(f.target, 'sentinel'), 'utf8'), 'KEEP_EXISTING');
});

for (const kind of ['outside', 'source', 'cache-root']) {
  test(`release rejects ${kind} output before copying`, async () => {
    const api = await policy();
    const f = fixture(api);
    const target = kind === 'outside' ? path.join(f.root, 'outside') : kind === 'source' ? f.root : path.join(f.root, '.cache');
    assert.throws(() => api.buildBackendRelease(f.root, target));
    assert.equal(fs.existsSync(f.target), false);
  });
}

test('an actual source directory junction may not redirect an allowlisted module', async () => {
  const api = await policy();
  const f = fixture(api);
  // Preserve the generated fixture tree; replace only this owned directory name.
  fs.renameSync(path.join(f.root, 'backend/app/agents'), path.join(f.root, 'outside-agents'));
  fs.symlinkSync(path.join(f.root, 'outside-agents'), path.join(f.root, 'backend/app/agents'),
    process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => api.buildBackendRelease(f.root, f.target));
  assert.equal(fs.existsSync(f.target), false);
});

for (const mutation of ['bytes', 'missing', 'extra', 'schema-bool', 'escape', 'duplicate',
  'complete-duplicate', 'seed-resealed', 'empty-extra-directory', 'artifact-junction']) {
  test(`artifact verifier refuses ${mutation} tampering`, async () => {
    const api = await policy();
    const f = fixture(api);
    api.buildBackendRelease(f.root, f.target);
    const manifest = path.join(f.target, 'release-manifest.json');
    if (mutation === 'bytes') fs.writeFileSync(path.join(f.target, 'backend/app/main.py'), 'DAMAGED');
    else if (mutation === 'missing') fs.unlinkSync(path.join(f.target, 'backend/app/main.py'));
    else if (mutation === 'extra') fs.writeFileSync(path.join(f.target, '.env'), 'PRIVATE_TEST_CANARY');
    else if (mutation === 'duplicate') fs.writeFileSync(manifest, '{"schemaVersion":1,"schemaVersion":1}');
    else if (mutation === 'complete-duplicate') {
      const valid = fs.readFileSync(manifest, 'utf8');
      fs.writeFileSync(manifest, valid.replace('"schemaVersion": 1,', '"schemaVersion": 1,\n  "schemaVersion": 1,'));
    } else if (mutation === 'empty-extra-directory') fs.mkdirSync(path.join(f.target, 'private'));
    else if (mutation === 'artifact-junction') {
      fs.renameSync(path.join(f.target, 'backend/app/agents'), path.join(f.root, 'artifact-agents'));
      fs.symlinkSync(path.join(f.root, 'artifact-agents'), path.join(f.target, 'backend/app/agents'),
        process.platform === 'win32' ? 'junction' : 'dir');
    }
    else {
      const body = JSON.parse(fs.readFileSync(manifest, 'utf8'));
      if (mutation === 'schema-bool') body.schemaVersion = true;
      else if (mutation === 'seed-resealed') {
        const { createHash } = await import('node:crypto');
        const seed = Buffer.from('PRIVATE_TEST_CANARY');
        fs.writeFileSync(path.join(f.target, 'backend/app/soups.py'), seed);
        body.files['backend/app/soups.py'] = createHash('sha256').update(seed).digest('hex');
      }
      else body.files['../escaped'] = '0'.repeat(64);
      fs.writeFileSync(manifest, JSON.stringify(body, null, 2) + '\n');
    }
    assert.throws(() => api.verifyBackendRelease(f.target));
  });
}
