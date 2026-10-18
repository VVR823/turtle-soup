import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { packageStandalone } from '../standalone-release-policy.mjs';

const workspace = fileURLToPath(new URL('../../', import.meta.url));
async function smoke() {
  const location = new URL('../test-standalone-release.mjs', import.meta.url);
  assert.ok(fs.existsSync(location), 'Actual standalone HTTP wrapper is missing');
  return import(location.href);
}
function fixture(damagedResponse = false) {
  const source = fs.mkdtempSync(path.join(workspace, '.cache', 'ts07-frontend-http-'));
  const target = `${source}-artifact`;
  const put = (name, value) => {
    const full = path.join(source, name);
    fs.mkdirSync(path.dirname(full), { recursive: true });
    fs.writeFileSync(full, value);
  };
  // Native protocol fixture only, not a substitute for real Next artifact smoke.
  put('.next/standalone/server.js', 'require("next").start(__dirname);');
  put('.next/standalone/package.json', '{}');
  put('.next/standalone/.next/BUILD_ID', 'SYNTHETIC_PROTOCOL_ONLY');
  put('.next/standalone/node_modules/next/package.json', '{"main":"index.js"}');
  put('.next/standalone/node_modules/next/index.js', `
const http = require('node:http'), fs = require('node:fs'), path = require('node:path');
exports.start = root => {
  if (process.env.TS17_PRIVATE_TEST) throw new Error('Inherited private environment');
  const server = http.createServer((req,res) => {
    const pathname = new URL(req.url, 'http://127.0.0.1').pathname;
    if (pathname.startsWith('/_next/static/')) {
      const name = '.next' + pathname.slice('/_next'.length);
      res.setHeader('Content-Type', name.endsWith('.js') ? 'application/javascript' : 'text/css');
      res.end(BAD_RESPONSE ? 'WRONG_SERVED_BYTES' : fs.readFileSync(path.join(root,name)));
    } else if (pathname === '/demo.svg') res.end(fs.readFileSync(path.join(root,'public/demo.svg')));
    else {
      res.setHeader('Content-Type','text/html');
      res.end('<html><link href="/_next/static/css/demo.css"><script src="/_next/static/chunks/demo.js"></script></html>');
    }
  });
  server.listen(Number(process.env.PORT), '127.0.0.1');
  process.on('SIGTERM', () => server.close(() => process.exit(143)));
};
`.replace('BAD_RESPONSE', String(damagedResponse)));
  put('.next/static/chunks/demo.js', 'console.log("synthetic protocol")');
  put('.next/static/css/demo.css', 'body{color:black}');
  put('public/demo.svg', '<svg></svg>');
  packageStandalone(source, target);
  return { target };
}

test('native HTTP ownership protocol verifies routes/assets, excludes inherited env and closes its server', async () => {
  const api = await smoke();
  const f = fixture();
  const previous = process.env.TS17_PRIVATE_TEST;
  process.env.TS17_PRIVATE_TEST = 'PRIVATE_TEST_CANARY';
  try {
    assert.deepEqual(await api.smokeStandaloneRelease(f.target), { status: 'passed', localOnly: true,
      productionReady: false, routes: 4, staticAssets: 2, publicAssets: 1, ownedResourcesClosed: true });
  } finally {
    if (previous === undefined) delete process.env.TS17_PRIVATE_TEST;
    else process.env.TS17_PRIVATE_TEST = previous;
  }
});
test('a corrupted artifact refuses before importing server code', async () => {
  const api = await smoke();
  const f = fixture();
  fs.writeFileSync(path.join(f.target, 'server.js'), 'throw new Error("DAMAGED_CODE_MUST_NOT_EXECUTE");');
  await assert.rejects(api.smokeStandaloneRelease(f.target), /digest/);
});
test('Windows CLI forward-slash absolute paths preserve artifact ownership and native shutdown', async () => {
  const api = await smoke();
  const f = fixture();
  assert.deepEqual(await api.smokeStandaloneRelease(f.target.replaceAll('\\', '/')),
    { status: 'passed', localOnly: true, productionReady: false,
      routes: 4, staticAssets: 2, publicAssets: 1, ownedResourcesClosed: true });
});
test('served byte mismatches cannot become a passed HTTP receipt', async () => {
  const api = await smoke();
  const f = fixture(true);
  await assert.rejects(api.smokeStandaloneRelease(f.target), /asset/i);
});
