/** Allowlisted sterile frontend: no dotenv/data/Git copy and no source links. */
import fs from 'node:fs';
import path from 'node:path';

const configFiles = ['package.json', 'package-lock.json', 'tsconfig.json', 'next.config.ts'];
const optionalConfigs = ['postcss.config.js', 'postcss.config.mjs', 'postcss.config.cjs'];
const sourceTypes = new Set(['.ts', '.tsx', '.js', '.jsx', '.css', '.svg', '.png', '.jpg', '.jpeg', '.ico', '.webp']);
const deniedDirectories = new Set(['data', 'backend', 'private', 'node_modules']);

export function createSterileFrontend(projectRoot, cacheRoot) {
  const root = fs.realpathSync(projectRoot);
  const cache = path.resolve(cacheRoot);
  if (path.relative(root, cache) !== '.cache') throw new Error('Frontend cache must be the project-owned .cache');
  fs.mkdirSync(cache, { recursive: true });
  if (fs.realpathSync(cache) !== cache) throw new Error('Frontend cache may not redirect outside the project');
  const output = fs.mkdtempSync(path.join(cache, 'ts07-frontend-'));
  function copy(source, target) {
    const stat = fs.lstatSync(source);
    if (stat.isSymbolicLink()) throw new Error('Source links may not redirect the sterile copy');
    if (stat.isDirectory()) {
      fs.mkdirSync(target, { recursive: true });
      for (const name of fs.readdirSync(source)) {
        if (name.startsWith('.') || deniedDirectories.has(name) || /\.(test|spec)\.[^.]+$/.test(name)) continue;
        copy(path.join(source, name), path.join(target, name));
      }
    } else if (stat.isFile() && sourceTypes.has(path.extname(source))) {
      fs.copyFileSync(source, target);
    }
  }
  for (const name of [...configFiles, ...optionalConfigs.filter(name => fs.existsSync(path.join(root, name)))]) {
    const source = path.join(root, name);
    if (fs.lstatSync(source).isSymbolicLink()) throw new Error('Configuration links may not redirect the sterile copy');
    fs.copyFileSync(source, path.join(output, name));
  }
  for (const name of ['src', 'public']) {
    const source = path.join(root, name);
    if (fs.existsSync(source)) copy(source, path.join(output, name));
  }
  // Explicit installed dependency directory only; never dereference arbitrary
  // source junctions. Webpack is used because the dependency link is outside
  // Turbopack's project root. No install or package/network fetch.
  const dependencies = fs.realpathSync(path.join(root, 'node_modules'));
  fs.symlinkSync(dependencies, path.join(output, 'node_modules'), process.platform === 'win32' ? 'junction' : 'dir');
  return output;
}

export function frontendEnvironment(inherited = process.env) {
  const env = {};
  for (const name of ['PATH', 'Path', 'SystemRoot', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'LOCALAPPDATA', 'APPDATA', 'USERPROFILE']) {
    if (inherited[name] !== undefined) env[name] = inherited[name];
  }
  return { ...env, NODE_ENV: 'production', NEXT_TELEMETRY_DISABLED: '1',
    NEXT_PUBLIC_API_BASE: 'http://127.0.0.1:18080' };
}
