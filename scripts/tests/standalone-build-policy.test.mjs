import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const workspace = fileURLToPath(new URL('../../', import.meta.url));
async function policy() {
  const location = new URL('../standalone-build-policy.mjs', import.meta.url);
  assert.ok(fs.existsSync(location), 'Standalone build boundary is missing');
  return import(location.href);
}
function fixture() {
  const directory = fs.mkdtempSync(path.join(workspace, '.cache', 'ts07-frontend-boundary-'));
  function put(name, value = 'SYNTHETIC_CODE') {
    const full = path.join(directory, name);
    fs.mkdirSync(path.dirname(full), { recursive: true });
    fs.writeFileSync(full, value);
  }
  for (const name of ['package.json', 'package-lock.json', 'tsconfig.json', 'next.config.ts',
    'node_modules/next/dist/bin/next', 'src/app/page.tsx', 'public/demo.svg']) put(name);
  return { directory, put };
}

test('closed configuration keeps standalone images and only the owned trace root', async () => {
  const api = await policy();
  const f = fixture();
  assert.deepEqual(api.standaloneConfiguration({ output: 'standalone', images: { unoptimized: true } }, f.directory),
    { output: 'standalone', images: { unoptimized: true }, outputFileTracingRoot: f.directory });
});
for (const config of [null, [], { output: 'export', images: { unoptimized: true } },
  { output: 'standalone', images: { unoptimized: false } },
  { output: 'standalone', images: { unoptimized: true, loaderFile: '../private' } },
  ...['outputFileTracingRoot', 'outputFileTracingIncludes', 'cacheHandler'].map(name =>
    ({ output: 'standalone', images: { unoptimized: true }, [name]: '../private' }))]) {
  test(`closed configuration refuses unsafe shape ${JSON.stringify(config)}`, async () => {
    const api = await policy();
    const f = fixture();
    assert.throws(() => api.standaloneConfiguration(config, f.directory));
  });
}

test('only an unbuilt physical owned input is accepted', async () => {
  const api = await policy();
  const f = fixture();
  assert.deepEqual(api.validateStandaloneBuildInput(f.directory), {
    directory: f.directory, nextCli: path.join(f.directory, 'node_modules/next/dist/bin/next'),
    configPath: path.join(f.directory, 'next.config.ts'),
  });
});
for (const mutation of ['built', 'private', 'junction']) {
  test(`input ${mutation} refuses before invoking Next`, async () => {
    const api = await policy();
    const f = fixture();
    if (mutation === 'built') f.put('.next/BUILD_ID');
    else if (mutation === 'private') f.put('.env', 'PRIVATE_TEST_CANARY');
    else {
      fs.renameSync(path.join(f.directory, 'node_modules'), path.join(f.directory, 'saved-deps'));
      fs.symlinkSync(path.join(f.directory, 'saved-deps'), path.join(f.directory, 'node_modules'),
        process.platform === 'win32' ? 'junction' : 'dir');
    }
    assert.throws(() => api.validateStandaloneBuildInput(f.directory));
  });
}
test('a real directory elsewhere cannot be used as a standalone build input', async () => {
  const api = await policy();
  assert.throws(() => api.validateStandaloneBuildInput(workspace));
});

test('relative trace traversal may reach owned deps but never leave the owned root', async () => {
  const api = await policy();
  const f = fixture();
  f.put('.next/server/app/page.js.nft.json', '{}');
  f.put('node_modules/demo/index.js');
  const trace = path.join(f.directory, '.next/server/app/page.js.nft.json');
  assert.equal(api.checkedTracePath(f.directory, trace, '../../../node_modules/demo/index.js'), 'node_modules/demo/index.js');
  for (const entry of ['../../../../package.json', path.join(f.directory, 'package.json'), '..\\..\\private']) {
    assert.throws(() => api.checkedTracePath(f.directory, trace, entry));
  }
});
test('a trace may not read through a real dependency junction', async () => {
  const api = await policy();
  const f = fixture();
  f.put('.next/server/app/page.js.nft.json', '{}');
  fs.renameSync(path.join(f.directory, 'node_modules'), path.join(f.directory, 'saved-deps'));
  fs.symlinkSync(path.join(f.directory, 'saved-deps'), path.join(f.directory, 'node_modules'),
    process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => api.checkedTracePath(f.directory,
    path.join(f.directory, '.next/server/app/page.js.nft.json'), '../../../node_modules/next/dist/bin/next'));
});
