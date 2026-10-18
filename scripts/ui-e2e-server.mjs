/** Own both sterile servers; never reuse root Next or a running user server. */
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';
import { frontendEnvironment } from './frontend-build-policy.mjs';
import { assertNoUiOverrides, ensureOwnedPortsFree, requireBrowserExecutable,
  validateUiFixtureIdentity, stopOwnedUiChildren } from './ui-server-policy.mjs';

const root = fs.realpathSync(fileURLToPath(new URL('../', import.meta.url)));
assertNoUiOverrides(process.env);
if (process.argv.length !== 2) throw new Error('UI gate has fixed configuration; CLI overrides are forbidden');
await ensureOwnedPortsFree();
const browserPath = requireBrowserExecutable(process.platform === 'win32'
  ? ['C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe', 'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe']
  : [chromium.executablePath()]);
const cache = path.join(root, '.cache'); fs.mkdirSync(cache, { recursive: true });
if (fs.realpathSync(cache) !== cache) throw new Error('UI cache cannot redirect outside the project');
const instanceId = randomUUID();
const data = fs.mkdtempSync(path.join(cache, 'ts08-ui-'));
const env = { ...frontendEnvironment(), TURTLE_SOUP_TESTING: '1', TURTLE_SOUP_UI_TESTING: '1',
  TURTLE_SOUP_DATA_DIR: data, TURTLE_SOUP_TEST_INSTANCE_ID: instanceId,
  TURTLE_SOUP_UI_BROWSER_PATH: browserPath, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' };
const entries = []; let build; let tests; let interrupted = false;
function owned(command, args, cwd, environment) {
  const child = spawn(command, args, { cwd, env: environment, stdio: ['pipe', 'pipe', 'inherit'],
    windowsHide: true, detached: process.platform !== 'win32' });
  let exited = false; child.once('exit', () => { exited = true; });
  child.stdin.on('error', error => { if (error.code !== 'EPIPE') console.error(error.message); });
  const finished = new Promise((resolve, reject) => {
    child.once('error', reject); child.once('close', (code, signal) => resolve({ code, signal }));
  });
  finished.catch(() => {});
  return { child, finished, hasExited: () => exited };
}
async function waitReady(entry, marker) {
  await new Promise((resolve, reject) => {
    let output = ''; let done = false;
    const finish = error => {
      if (done) return; done = true; clearTimeout(timer); entry.child.stdout.off('data', onData);
      if (error) reject(error); else resolve();
    };
    const onData = buffer => {
      output += buffer.toString().replaceAll('\r', '');
      if (output.split('\n').includes(marker)) finish();
    };
    const timer = setTimeout(() => finish(new Error(`Owned readiness timed out: ${marker}`)), 30_000);
    entry.child.stdout.on('data', onData);
    entry.finished.then(() => finish(new Error('Owned child exited before readiness')), finish);
  });
}
const interrupt = () => {
  interrupted = true;
  for (const entry of entries) entry.child.stdin.end();
  for (const entry of [build, tests]) if (entry && !entry.hasExited()) entry.child.kill('SIGTERM');
};
process.on('SIGINT', interrupt); process.on('SIGTERM', interrupt);
try {
  let sterile = '';
  build = owned(process.execPath, [path.join(root, 'scripts/test-frontend-build.mjs')], root, frontendEnvironment());
  let output = '';
  build.child.stdout.on('data', buffer => {
    process.stdout.write(buffer); output += buffer.toString().replaceAll('\r', '');
    const line = output.split('\n').find(line => line.startsWith('TS07_STERILE_FRONTEND:'));
    if (line) sterile = line.slice('TS07_STERILE_FRONTEND:'.length);
  });
  const built = await build.finished;
  if (interrupted || built.code !== 0 || !sterile) throw new Error('Owned sterile build failed or interrupted');
  // Check again after build: occupied ports are never queried or reused.
  await ensureOwnedPortsFree();
  const python = path.join(root, 'backend/.venv-ts01', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const backend = owned(python, ['-m', 'app.test_server'], path.join(root, 'backend'), env); entries.push(backend);
  await waitReady(backend, `TS01_READY:${instanceId}`); backend.child.stdout.pipe(process.stdout);
  validateUiFixtureIdentity(await (await fetch('http://127.0.0.1:18080/health', {
    redirect: 'error', signal: AbortSignal.timeout(3_000),
  })).json(), instanceId);
  const frontend = owned(process.execPath, [path.join(root, 'scripts/ui-frontend-server.mjs')], root,
    { ...env, TURTLE_SOUP_UI_STERILE: sterile }); entries.push(frontend);
  await waitReady(frontend, `TS08_FRONTEND_READY:${instanceId}`); frontend.child.stdout.pipe(process.stdout);
  if (interrupted || entries.some(entry => entry.hasExited())) throw new Error('UI fixture no longer owned and live');
  console.log(`TS08_UI_OWNED:${instanceId}; data=${data}; frontend=${sterile}`);
  tests = owned(process.execPath, [path.join(root, 'node_modules/@playwright/test/cli.js'), 'test', '--config=playwright.ui.config.ts'], root, env);
  tests.child.stdout.pipe(process.stdout);
  const result = await tests.finished; process.exitCode = result.code === 0 && !interrupted ? 0 : 1;
} catch (error) { console.error(error.message); process.exitCode = 1; }
finally {
  try { await stopOwnedUiChildren(entries); console.log('TS08_UI_CLEANUP:0; both owned fixtures closed'); }
  catch (error) {
    console.error(`${error.message}; owned launch PIDs=${entries.map(entry => entry.child.pid).join(',')}`);
    process.exitCode = 1;
    for (const entry of entries) { entry.child.stdin.destroy(); entry.child.stdout.destroy(); entry.child.unref(); }
  }
  process.off('SIGINT', interrupt); process.off('SIGTERM', interrupt);
}
// Retain only this run's synthetic data/build for diagnosis, never delete user data.
