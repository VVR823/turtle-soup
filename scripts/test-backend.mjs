import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const environment = process.env.UV_PROJECT_ENVIRONMENT || path.join(root, 'backend', '.venv-ts01');
const result = spawnSync('uv', [
  'run', '--project', path.join(root, 'backend'), '--offline', '--no-sync',
  'python', '-m', 'pytest', '--junitxml=.cache/ts01/pytest.xml', ...process.argv.slice(2),
], {
  cwd: root,
  stdio: 'inherit',
  env: {
    ...process.env, UV_PROJECT_ENVIRONMENT: environment,
    UV_CACHE_DIR: path.join(root, '.cache', 'uv'),
  },
});
if (result.error) console.error(result.error.message);
process.exitCode = result.status ?? 1;
