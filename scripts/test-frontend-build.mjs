/** Local production-page build, never a production deploy/standalone proof. */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { createSterileFrontend, frontendEnvironment } from './frontend-build-policy.mjs';

const root = fs.realpathSync(fileURLToPath(new URL('../', import.meta.url)));
const sterile = createSterileFrontend(root, path.join(root, '.cache'));
const require = createRequire(import.meta.url);
const ts = require('typescript');
// Keep rendering/image settings. Only packaging is disabled in this owned
// fixture: standalone tracing/copy must not write across dependency junctions.
// This is not evidence for TS17's final production packaging/deployment gate.
const config = path.join(sterile, 'next.config.ts');
const transformed = ts.transpileModule(fs.readFileSync(config, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
fs.renameSync(config, path.join(sterile, 'next.config.source.ts'));
fs.writeFileSync(path.join(sterile, 'next.config.source.mjs'), transformed);
fs.writeFileSync(path.join(sterile, 'next.config.mjs'),
  'import config from "./next.config.source.mjs";\nexport default { ...config, output: undefined, outputFileTracingRoot: process.cwd() };\n');
console.log(`TS07_STERILE_FRONTEND:${sterile}`);
const child = spawn(process.execPath, [path.join(root, 'node_modules/next/dist/bin/next'), 'build', sterile, '--webpack'], {
  cwd: sterile, env: frontendEnvironment(), stdio: 'inherit', windowsHide: true,
});
let exited = false;
const stop = () => { if (!exited) child.kill('SIGTERM'); };
process.once('SIGINT', stop);
process.once('SIGTERM', stop);
try {
  const code = await new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('exit', () => { exited = true; });
    child.once('close', code => resolve(code ?? 1));
  });
  process.exitCode = code;
  console.log(`TS07_FRONTEND_BUILD_EXIT:${code}; fixture=${sterile}`);
} finally {
  process.off('SIGINT', stop);
  process.off('SIGTERM', stop);
}
// Retain this one owned source/build fixture for reproducible browser QA.
