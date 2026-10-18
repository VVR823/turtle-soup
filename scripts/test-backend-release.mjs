/** Smoke the LOCAL artifact in a fresh interpreter; never load default settings. */
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { buildBackendRelease, verifyBackendRelease } from './backend-release-policy.mjs';
import { frontendEnvironment } from './frontend-build-policy.mjs';
import { stopFixture } from './fixture-process.mjs';

const root = fs.realpathSync(fileURLToPath(new URL('../', import.meta.url)));
export async function probeBackendRelease(target, data) {
  const original = verifyBackendRelease(target);
  const cache = path.join(root, '.cache');
  if (typeof data !== 'string' || !path.isAbsolute(data)
    || path.dirname(path.resolve(target)) !== cache || path.dirname(path.resolve(data)) !== cache
    || fs.lstatSync(cache).isSymbolicLink() || fs.realpathSync(cache) !== cache) {
    throw new Error('Smoke requires project-owned sibling artifact and new data');
  }
  try {
    fs.lstatSync(data);
    throw new Error('Smoke data already exists');
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  fs.mkdirSync(data);
  const python = path.join(root, 'backend', '.venv-ts01', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const child = spawn(python, ['-I', '-B', path.join(root, 'scripts/tests/probe-backend-release.py'),
    path.join(target, 'backend'), data], {
    cwd: target, windowsHide: true, detached: process.platform !== 'win32',
    stdio: ['pipe', 'pipe', 'pipe'],
    env: { ...frontendEnvironment(), LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' },
  });
  child.stdin.on('error', error => { if (error.code !== 'EPIPE') console.error(error.message); });
  let output = '', errors = '', overflow = false;
  const capture = (buffer, prior) => {
    if (prior.length + buffer.length > 64 * 1024) { overflow = true; return prior; }
    return prior + buffer.toString();
  };
  child.stdout.on('data', buffer => { output = capture(buffer, output); });
  child.stderr.on('data', buffer => { errors = capture(buffer, errors); });
  const finished = new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('close', (code, signal) => resolve({ code, signal }));
  });
  finished.catch(() => {});
  let timer;
  try {
    const result = await Promise.race([finished, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('Artifact smoke exceeded 45 seconds')), 45_000);
    })]);
    if (result.code !== 0 || result.signal || overflow) {
      throw new Error(`Artifact smoke failed: ${errors || 'no successful native receipt'}`);
    }
    const receipt = JSON.parse(output);
    const expected = { status: 'passed', localOnly: true, productionReady: false,
      dataKind: 'synthetic_demo', health: true, publicSeed: true, chatReplay: true,
      moduleOriginsVerified: true, fixedSuiteSourcesVerified: true,
      ownedResourcesClosed: true, networkAttempts: 0 };
    if (JSON.stringify(receipt) !== JSON.stringify(expected)) throw new Error('Incomplete artifact smoke receipt');
    if (JSON.stringify(verifyBackendRelease(target)) !== JSON.stringify(original)) {
      throw new Error('Artifact changed during smoke');
    }
    return receipt;
  } finally {
    clearTimeout(timer);
    const stopped = await stopFixture(child, finished);
    if (stopped.code !== 0) throw new Error(`Artifact child did not exit normally: ${errors || 'no native error receipt'}`);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const cache = path.join(root, '.cache');
    fs.mkdirSync(cache, { recursive: true });
    if (fs.lstatSync(cache).isSymbolicLink() || fs.realpathSync(cache) !== cache) throw new Error('Redirected cache');
    const reservation = fs.mkdtempSync(path.join(cache, 'ts17-backend-'));
    const target = `${reservation}-artifact`, data = `${reservation}-data`;
    buildBackendRelease(root, target);
    const receipt = await probeBackendRelease(target, data);
    console.log(JSON.stringify({ ...receipt, artifact: path.relative(root, target) }));
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
