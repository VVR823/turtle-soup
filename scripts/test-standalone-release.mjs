/** Actual LOCAL artifact HTTP/asset smoke, never a browser or production gate. */
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import { spawn } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { packageStandalone, verifyStandaloneRelease } from './standalone-release-policy.mjs';
import { frontendEnvironment } from './frontend-build-policy.mjs';
import { stopFixture } from './fixture-process.mjs';

const root = fs.realpathSync(fileURLToPath(new URL('../', import.meta.url)));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
async function freePort(requested = 0) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(requested, '127.0.0.1', () => {
      const port = server.address().port;
      server.close(error => error ? reject(error) : resolve(port));
    });
  });
}
export async function smokeStandaloneRelease(target) {
  const before = verifyStandaloneRelease(target);
  // The validated Windows CLI input may use forward separators. Normalize
  // before handing it to the child's strict physical-path identity check.
  target = path.resolve(target);
  const port = await freePort(), instance = randomUUID();
  const child = spawn(process.execPath, [path.join(root, 'scripts/tests/probe-standalone-server.mjs'),
    target, String(port), instance], {
    cwd: target, env: { ...frontendEnvironment(), HOSTNAME: '127.0.0.1', PORT: String(port) },
    windowsHide: true, detached: process.platform !== 'win32', stdio: ['pipe', 'pipe', 'pipe'],
  });
  child.stdin.on('error', error => { if (error.code !== 'EPIPE') console.error(error.message); });
  let output = '', errors = '', overflow = false, interrupted = false;
  const collect = (previous, buffer) => {
    if (previous.length + buffer.length > 64 * 1024) { overflow = true; return previous; }
    return previous + buffer.toString();
  };
  child.stdout.on('data', buffer => { output = collect(output, buffer).replaceAll('\r', ''); });
  child.stderr.on('data', buffer => { errors = collect(errors, buffer); });
  const finished = new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('close', (code, signal) => resolve({ code, signal }));
  });
  finished.catch(() => {});
  const interrupt = () => { interrupted = true; child.stdin.end(); };
  process.on('SIGINT', interrupt); process.on('SIGTERM', interrupt);
  let receipt;
  try {
    await new Promise((resolve, reject) => {
      let done = false;
      const finish = error => {
        if (done) return;
        done = true; clearTimeout(timer); child.stdout.off('data', ready);
        if (error) reject(error); else resolve();
      };
      const ready = () => {
        if (output.split('\n').includes(`TS17_ARTIFACT_LISTENING:${instance}`)) finish();
      };
      const timer = setTimeout(() => finish(new Error('Artifact did not own a listener within 30 seconds')), 30_000);
      child.stdout.on('data', ready);
      finished.then(() => finish(new Error(`Artifact exited before listening: ${errors}`)), finish);
      ready();
    });
    async function get(relative) {
      if (interrupted || overflow || child.exitCode !== null || child.signalCode !== null) throw new Error('Artifact is no longer live and owned');
      const response = await fetch(`http://127.0.0.1:${port}${relative}`, {
        redirect: 'error', signal: AbortSignal.timeout(8_000),
      });
      if (response.headers.get('x-ts17-instance') !== instance) throw new Error('Foreign artifact response');
      if (response.status !== 200) throw new Error('Artifact route did not return 200');
      return response;
    }
    const assets = new Set();
    const routes = ['/', '/game/demo-synthetic?level=tianyi', '/difficulty/demo-synthetic', '/admin/feedback'];
    for (const route of routes) {
      const response = await get(route);
      if (!response.headers.get('content-type')?.includes('text/html')) throw new Error('Artifact page is not HTML');
      const html = await response.text();
      for (const match of html.matchAll(/\b(?:src|href)="(\/_next\/static\/[^"\s]+)"/g)) assets.add(match[1].replaceAll('&amp;', '&'));
    }
    if (![...assets].some(name => new URL(name, 'http://127.0.0.1').pathname.endsWith('.js'))
      || ![...assets].some(name => new URL(name, 'http://127.0.0.1').pathname.endsWith('.css'))) throw new Error('Missing JS/CSS artifact assets');
    for (const asset of assets) {
      const pathname = decodeURIComponent(new URL(asset, 'http://127.0.0.1').pathname);
      const name = '.next' + pathname.slice('/_next'.length);
      if (!before.files[name]) throw new Error('Unsigned artifact asset');
      const bytes = Buffer.from(await (await get(asset)).arrayBuffer());
      if (sha(bytes) !== before.files[name]) throw new Error('Served artifact asset digest differs');
    }
    const publicName = Object.keys(before.files).find(name => name.startsWith('public/'));
    const publicRoute = '/' + publicName.slice('public/'.length).split('/').map(encodeURIComponent).join('/');
    const publicBytes = Buffer.from(await (await get(publicRoute)).arrayBuffer());
    if (sha(publicBytes) !== before.files[publicName]) throw new Error('Served public asset digest differs');
    receipt = { status: 'passed', localOnly: true, productionReady: false,
      routes: routes.length, staticAssets: assets.size, publicAssets: 1, ownedResourcesClosed: true };
  } finally {
    try {
      const stopped = await stopFixture(child, finished, { graceMs: 10_000 });
      if (stopped.code !== 143 || stopped.signal || overflow
        || !output.split('\n').includes(`TS17_ARTIFACT_EOF:${instance}`)
        || !output.split('\n').includes(`TS17_ARTIFACT_ORIGINS:${instance}`)) {
        throw new Error(`Artifact cooperative shutdown/origin proof failed: ${errors}`);
      }
      await freePort(port);
    } finally { process.off('SIGINT', interrupt); process.off('SIGTERM', interrupt); }
  }
  if (JSON.stringify(verifyStandaloneRelease(target)) !== JSON.stringify(before)) throw new Error('Artifact changed during HTTP smoke');
  return receipt;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    if (process.argv.length !== 4) throw new Error('Two absolute paths required: owned built input and new artifact');
    const target = process.argv[3];
    packageStandalone(process.argv[2], target);
    const receipt = await smokeStandaloneRelease(target);
    console.log(JSON.stringify({ ...receipt, artifact: path.relative(root, target),
      manifestSHA256: sha(fs.readFileSync(path.join(target, 'release-manifest.json'))) }));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
