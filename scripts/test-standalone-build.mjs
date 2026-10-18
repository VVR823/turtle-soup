/** Build only a new physical LOCAL input, not the original checkout. */
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { validateStandaloneBuildInput, standaloneConfiguration, checkedTracePath } from './standalone-build-policy.mjs';
import { frontendEnvironment } from './frontend-build-policy.mjs';
import { stopFixture } from './fixture-process.mjs';

if (process.argv.length !== 3) throw new Error('One absolute new owned input directory required');
const input = validateStandaloneBuildInput(process.argv[2]);
const require = createRequire(import.meta.url);
const ts = require('typescript');
const transformed = ts.transpileModule(fs.readFileSync(input.configPath, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const sourceModule = path.join(input.directory, 'next.config.source.mjs');
fs.writeFileSync(sourceModule, transformed, { flag: 'wx' });
const supplied = (await import(pathToFileURL(sourceModule).href)).default;
const config = standaloneConfiguration(supplied, input.directory);
fs.renameSync(input.configPath, path.join(input.directory, 'next.config.source.ts'));
fs.writeFileSync(path.join(input.directory, 'next.config.mjs'),
  'export default ' + JSON.stringify(config) + ';\n', { flag: 'wx' });
console.log(`TS17_OWNED_STANDALONE_BUILD:${input.directory}`);
const child = spawn(process.execPath, [input.nextCli, 'build', input.directory, '--webpack'], {
  cwd: input.directory, env: frontendEnvironment(), stdio: ['pipe', 'inherit', 'inherit'],
  windowsHide: true, detached: process.platform !== 'win32',
});
child.stdin.on('error', error => { if (error.code !== 'EPIPE') console.error(error.message); });
const finished = new Promise((resolve, reject) => {
  child.once('error', reject);
  child.once('close', (code, signal) => resolve({ code, signal }));
});
finished.catch(() => {});
let interrupted = false;
const interrupt = () => { interrupted = true; child.stdin.end(); };
process.on('SIGINT', interrupt); process.on('SIGTERM', interrupt);
try {
  const result = await finished;
  if (result.code !== 0 || result.signal || interrupted) throw new Error('Owned standalone build failed or interrupted');
  for (const relative of ['.next/BUILD_ID', '.next/standalone/server.js']) {
    if (!fs.lstatSync(path.join(input.directory, relative)).isFile()) throw new Error('Incomplete actual standalone build');
  }
  let traceManifests = 0, tracedPaths = 0;
  function inspect(folder) {
    for (const name of fs.readdirSync(folder)) {
      const full = path.join(folder, name), stat = fs.lstatSync(full);
      if (stat.isSymbolicLink() || fs.realpathSync(full) !== full) throw new Error('Build output link forbidden');
      if (stat.isDirectory()) inspect(full);
      else if (name.endsWith('.nft.json')) {
        const trace = JSON.parse(fs.readFileSync(full, 'utf8'));
        if (trace.version !== 1 || !Array.isArray(trace.files)) throw new Error('Invalid actual NFT manifest');
        for (const entry of trace.files) { checkedTracePath(input.directory, full, entry); tracedPaths++; }
        traceManifests++;
      }
    }
  }
  inspect(path.join(input.directory, '.next'));
  if (!traceManifests || !tracedPaths) throw new Error('No actual standalone trace proof');
  console.log('TS17_STANDALONE_BUILD_RECEIPT:' + JSON.stringify({ status: 'passed', localOnly: true,
    productionReady: false, directory: input.directory, traceManifests, tracedPaths,
    publicStaticPackaged: false, serverSmokePassed: false }));
} catch (error) {
  console.error(error.message); process.exitCode = 1;
} finally {
  try {
    const stopped = await stopFixture(child, finished);
    if (stopped.code !== 0) process.exitCode = 1;
  } catch (error) { console.error(error.message); process.exitCode = 1; }
  process.off('SIGINT', interrupt); process.off('SIGTERM', interrupt);
}
