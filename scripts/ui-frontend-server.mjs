import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { frontendEnvironment } from './frontend-build-policy.mjs';
import { superviseFrontend } from './ui-frontend-process.mjs';

const root = fs.realpathSync(fileURLToPath(new URL('../', import.meta.url)));
const sterile = fs.realpathSync(process.env.TURTLE_SOUP_UI_STERILE || '');
const relative = path.relative(path.join(root, '.cache'), sterile);
const instanceId = process.env.TURTLE_SOUP_TEST_INSTANCE_ID;
if (process.env.TURTLE_SOUP_UI_TESTING !== '1' || !instanceId || !/^ts07-frontend-[^\\/]+$/.test(relative)
    || !fs.existsSync(path.join(sterile, '.next', 'BUILD_ID'))) throw new Error('Owned built sterile UI fixture is required');
const child = spawn(process.execPath, [path.join(root, 'node_modules/next/dist/bin/next'), 'start', sterile, '-H', '127.0.0.1', '-p', '18081'], {
  cwd: sterile, env: frontendEnvironment(), stdio: ['pipe', 'pipe', 'inherit'], windowsHide: true,
  detached: process.platform !== 'win32',
});
child.stdin.on('error', error => { if (error.code !== 'EPIPE') console.error(error.message); });
const finished = new Promise((resolve, reject) => {
  child.once('error', reject); child.once('close', (code, signal) => resolve({ code, signal }));
});
finished.catch(() => {});
child.stdout.pipe(process.stdout);
const stop = () => process.stdin.emit('end');
process.on('SIGINT', stop); process.on('SIGTERM', stop);
try {
  await superviseFrontend({ child, finished, input: process.stdin, emit: console.log, instanceId });
  console.log('TS08_FRONTEND_CLOSED:0');
} catch (error) { console.error(error.message); process.exitCode = 1; }
finally { process.off('SIGINT', stop); process.off('SIGTERM', stop); }
