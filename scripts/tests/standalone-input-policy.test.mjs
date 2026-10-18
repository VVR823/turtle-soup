import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const workspace = fileURLToPath(new URL('../../', import.meta.url));
async function policy() {
  const location = new URL('../standalone-input-policy.mjs', import.meta.url);
  assert.ok(fs.existsSync(location), 'Owned standalone dependency input is missing');
  return import(location.href);
}
function fixture() {
  const root = fs.mkdtempSync(path.join(workspace, '.cache', 'ts17-deps-fixture-'));
  function put(name, bytes = 'public') {
    const full = path.join(root, name);
    fs.mkdirSync(path.dirname(full), { recursive: true });
    fs.writeFileSync(full, bytes);
  }
  for (const name of ['package.json', 'package-lock.json', 'tsconfig.json', 'next.config.ts',
    'src/app/page.tsx', 'public/demo.svg']) put(name);
  put('node_modules/demo/index.js', 'module.exports=1');
  put('node_modules/demo/package.json', '{}');
  put('node_modules/next/dist/bin/next', 'next');
  for (const name of ['.env', 'backend/data/sessions.db', 'private/example.json', 'src/private/private.ts']) {
    put(name, 'PRIVATE_TEST_CANARY');
  }
  fs.mkdirSync(path.join(root, '.cache'));
  return { root, put };
}

test('materialized dependencies are physical and independent of original installed bytes', async () => {
  const api = await policy();
  const f = fixture();
  const result = api.prepareStandaloneFrontend(f.root);
  assert.equal(path.dirname(result.directory), path.join(f.root, '.cache'));
  const modules = path.join(result.directory, 'node_modules');
  assert.ok(fs.lstatSync(modules).isDirectory());
  assert.equal(fs.lstatSync(modules).isSymbolicLink(), false);
  assert.equal(fs.readFileSync(path.join(modules, 'demo/index.js'), 'utf8'), 'module.exports=1');
  assert.equal(result.dependencies.files, 3);
  assert.equal(result.dependencies.bytes, 22);
  assert.match(result.dependencies.digest, /^[0-9a-f]{64}$/);
  f.put('node_modules/demo/index.js', 'CHANGED_SOURCE');
  assert.equal(fs.readFileSync(path.join(modules, 'demo/index.js'), 'utf8'), 'module.exports=1');
  for (const name of ['src/app/page.tsx', 'public/demo.svg', 'package.json']) {
    assert.equal(fs.readFileSync(path.join(result.directory, name), 'utf8'), 'public');
  }
  for (const name of ['.env', 'backend', 'private', 'src/private']) {
    assert.equal(fs.existsSync(path.join(result.directory, name)), false);
  }
});

for (const kind of ['dependency-root', 'nested-dependency', 'cache']) {
  test(`actual ${kind} junction is refused before creating a sterile directory`, async () => {
    const api = await policy();
    const f = fixture();
    const relative = kind === 'dependency-root' ? 'node_modules'
      : kind === 'nested-dependency' ? 'node_modules/demo' : '.cache';
    const moved = path.join(f.root, 'outside-' + kind);
    fs.renameSync(path.join(f.root, relative), moved);
    fs.symlinkSync(moved, path.join(f.root, relative), process.platform === 'win32' ? 'junction' : 'dir');
    const before = fs.readdirSync(path.join(f.root, '.cache'));
    assert.throws(() => api.prepareStandaloneFrontend(f.root));
    assert.deepEqual(fs.readdirSync(path.join(f.root, '.cache')), before);
  });
}

test('real source mutation during a copy refuses the input receipt', async () => {
  const api = await policy();
  const f = fixture();
  const source = path.join(f.root, 'node_modules/demo/index.js');
  const copy = fs.copyFileSync;
  try {
    fs.copyFileSync = (from, to, ...args) => {
      const result = copy(from, to, ...args);
      if (from === source) fs.writeFileSync(source, 'SOURCE_CHANGED_DURING_COPY');
      return result;
    };
    assert.throws(() => api.prepareStandaloneFrontend(f.root));
  } finally { fs.copyFileSync = copy; }
  assert.equal(fs.readFileSync(source, 'utf8'), 'SOURCE_CHANGED_DURING_COPY');
});

test('missing installed dependencies do not create a replacement or a sterile directory', async () => {
  const api = await policy();
  const f = fixture();
  fs.renameSync(path.join(f.root, 'node_modules'), path.join(f.root, 'preserved-installation'));
  assert.throws(() => api.prepareStandaloneFrontend(f.root));
  assert.deepEqual(fs.readdirSync(path.join(f.root, '.cache')), []);
  assert.equal(fs.existsSync(path.join(f.root, 'node_modules')), false);
});
