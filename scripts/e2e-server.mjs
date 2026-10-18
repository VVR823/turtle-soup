import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { stopFixture } from './fixture-process.mjs';

const root = fs.realpathSync(fileURLToPath(new URL('../', import.meta.url)));
// Fail before sending HTTP to an unrelated server on the fixed test port.
await new Promise((resolve, reject) => {
  const probe = net.createServer();
  probe.once('error', reject);
  probe.listen(18080, '127.0.0.1', () => probe.close(resolve));
});
const cache = path.join(root, '.cache');
fs.mkdirSync(cache, { recursive: true });
if (fs.realpathSync(cache) !== cache) throw new Error('Test cache cannot redirect outside the project');
const data = fs.mkdtempSync(path.join(cache, 'e2e-'));
const instanceId = randomUUID();
const environment = path.resolve(process.env.UV_PROJECT_ENVIRONMENT || path.join(root, 'backend', '.venv-ts01'));
const python = path.join(environment, process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const env = {
  ...process.env, TURTLE_SOUP_TESTING: '1', TURTLE_SOUP_DATA_DIR: data,
  TURTLE_SOUP_TEST_INSTANCE_ID: instanceId,
};
for (const name of ['OPENAI_API_KEY', 'QWEN_API_KEY', 'SILICONFLOW_API_KEY', 'ZHIPU_API_KEY', 'LANGSMITH_API_KEY', 'LANGCHAIN_API_KEY']) {
  delete env[name];
}
env.LANGSMITH_TRACING = 'false';
env.LANGCHAIN_TRACING_V2 = 'false';
const child = spawn(python, ['-m', 'app.test_server'], {
  cwd: path.join(root, 'backend'), stdio: ['pipe', 'pipe', 'inherit'], env,
  windowsHide: true, detached: process.platform !== 'win32',
});
child.stdin.on('error', error => {
  if (error.code !== 'EPIPE') console.error(error.message);
});
let fixtureExited = false;
child.once('exit', () => { fixtureExited = true; });
const finished = new Promise((resolve, reject) => {
  child.once('error', reject);
  child.once('close', (code, signal) => resolve({ code, signal }));
});
// Register rejection handling immediately, even while waiting for readiness.
finished.catch(() => {});
let tests;
let interrupted = false;
const shutdown = () => {
  interrupted = true;
  child.stdin.end(); // EOF reaches the real interpreter, including the Windows venv launcher.
  if (tests && tests.exitCode === null) tests.kill('SIGTERM');
};
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
try {
  await new Promise((resolve, reject) => {
    let output = '';
    const finish = error => {
      clearTimeout(timer);
      child.stdout.off('data', onData);
      if (error) reject(error);
      else resolve();
    };
    const timer = setTimeout(() => finish(new Error('Fixture did not start within 30 seconds')), 30_000);
    const onData = buffer => {
      output += buffer.toString().replaceAll('\r', '');
      if (output.includes(`TS01_READY:${instanceId}\n`)) finish();
    };
    child.stdout.on('data', onData);
    finished.then(() => finish(new Error('Fixture exited before readiness')), finish);
  });
  child.stdout.pipe(process.stdout);
  if (interrupted) throw new Error('Test run interrupted');
  tests = spawn(process.execPath, [path.join(root, 'node_modules/@playwright/test/cli.js'), 'test', ...process.argv.slice(2)], {
    cwd: root, stdio: 'inherit', env, windowsHide: true,
  });
  process.exitCode = await new Promise((resolve, reject) => {
    tests.once('error', reject);
    tests.once('close', code => resolve(code ?? 1));
  });
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  try {
    // Do not claim success before the fixture has actually released its port.
    const result = await stopFixture(child, finished, { hasExited: () => fixtureExited });
    if (result.code !== 0) process.exitCode = 1;
  } catch (error) {
    console.error(`${error.message}; fixture launch PID=${child.pid}. Verify current ownership before manual recovery.`);
    process.exitCode = 1;
    child.stdin.destroy();
    child.stdout.destroy();
    child.unref();
  }
  process.off('SIGINT', shutdown);
  process.off('SIGTERM', shutdown);
}
// Preserve only this run's synthetic data for debugging; never remove user data.
