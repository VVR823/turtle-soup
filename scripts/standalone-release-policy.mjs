/** LOCAL code-only standalone packaging. Hashes are not source authentication. */
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const project = fs.realpathSync(fileURLToPath(new URL('../', import.meta.url)));
const cache = path.join(project, '.cache');
const manifestName = 'release-manifest.json';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const encoded = value => JSON.stringify(value, null, 2) + '\n';
function physical(input) {
  if (typeof input !== 'string' || !path.isAbsolute(input)) throw new Error('Absolute package path required');
  const absolute = path.resolve(input), anchor = path.parse(absolute).root;
  let current = anchor;
  for (const part of path.relative(anchor, absolute).split(path.sep).filter(Boolean)) {
    current = path.join(current, part);
    try {
      const stat = fs.lstatSync(current);
      if (stat.isSymbolicLink() || fs.realpathSync(current) !== current) throw new Error('Package path may not redirect');
    } catch (error) {
      if (error.code === 'ENOENT') break;
      throw error;
    }
  }
  return absolute;
}
function allowedFile(name) {
  if (typeof name !== 'string' || !name || name.includes('\\') || path.posix.isAbsolute(name)
    || name.split('/').some(part => !part || part === '.' || part === '..')) return false;
  if (name !== 'server.js' && name !== 'package.json'
    && !name.startsWith('.next/') && !name.startsWith('node_modules/') && !name.startsWith('public/')) return false;
  if (name.startsWith('.next/cache/') || name === '.next/trace') return false;
  return !name.split('/').some(part => /^\.env(?:$|\.)/.test(part)
    || /(?:\.db|\.sqlite|\.sqlite3|\.jsonl|\.log|\.db-wal|\.db-shm)$/.test(part));
}
function requirements(files) {
  for (const name of ['server.js', 'package.json', '.next/BUILD_ID', 'node_modules/next/package.json']) {
    if (!(name in files)) throw new Error('Required standalone file missing');
  }
  for (const prefix of ['.next/static/', 'public/']) {
    if (!Object.keys(files).some(name => name.startsWith(prefix))) throw new Error('Required asset tree missing');
  }
}
function metadata(files) {
  return { schemaVersion: 1, localOnly: true, productionReady: false, dataKind: 'code_only', files };
}
function sourceInventory(sterile) {
  const entries = new Map();
  function collect(root, prefix) {
    physical(root);
    if (!fs.lstatSync(root).isDirectory()) throw new Error('Required standalone tree missing');
    function walk(directory, relative = '') {
      for (const name of fs.readdirSync(directory)) {
        const input = physical(path.join(directory, name)), stat = fs.lstatSync(input);
        const tail = relative ? `${relative}/${name}` : name;
        if (stat.isDirectory()) walk(input, tail);
        else if (stat.isFile()) {
          const output = prefix + tail;
          if (!allowedFile(output) || entries.has(output)) throw new Error('Unexpected standalone input');
          entries.set(output, { input, digest: sha(fs.readFileSync(input)) });
        } else throw new Error('Standalone inputs must be regular files');
      }
    }
    walk(root);
  }
  const standalone = path.join(sterile, '.next/standalone');
  physical(standalone);
  const top = new Set(['server.js', 'package.json', '.next', 'node_modules']);
  for (const name of fs.readdirSync(standalone)) if (!top.has(name)) throw new Error('Unexpected standalone root');
  collect(standalone, '');
  collect(path.join(sterile, '.next/static'), '.next/static/');
  collect(path.join(sterile, 'public'), 'public/');
  const sorted = new Map([...entries].sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0));
  requirements(Object.fromEntries([...sorted].map(([name, file]) => [name, file.digest])));
  return sorted;
}

export function packageStandalone(sterile, target) {
  const source = physical(sterile), output = physical(target);
  if (path.dirname(source) !== cache || !/^ts07-frontend-[^\\/]+$/.test(path.basename(source))
    || path.dirname(output) !== cache || source === output || fs.existsSync(output)) {
    throw new Error('Package needs owned built input and a new direct cache child');
  }
  const before = sourceInventory(source);
  fs.mkdirSync(output);
  const files = {};
  for (const [name, file] of before) {
    const destination = path.join(output, name);
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.copyFileSync(file.input, destination, fs.constants.COPYFILE_EXCL);
    if (sha(fs.readFileSync(destination)) !== file.digest) throw new Error('Copied standalone bytes differ');
    files[name] = file.digest;
  }
  if (JSON.stringify([...sourceInventory(source)]) !== JSON.stringify([...before])) {
    throw new Error('Selected standalone source changed during copy');
  }
  fs.writeFileSync(path.join(output, manifestName), encoded(metadata(files)), { flag: 'wx' });
  return verifyStandaloneRelease(output);
}

export function verifyStandaloneRelease(target) {
  const root = physical(target);
  if (path.dirname(root) !== cache || !fs.lstatSync(root).isDirectory()) throw new Error('Owned artifact required');
  const receipt = physical(path.join(root, manifestName));
  const bytes = fs.readFileSync(receipt, 'utf8');
  const body = JSON.parse(bytes);
  if (!body || Array.isArray(body) || typeof body !== 'object' || !body.files
    || Array.isArray(body.files) || typeof body.files !== 'object') throw new Error('Invalid standalone manifest');
  const names = Object.keys(body.files).sort();
  const files = Object.fromEntries(names.map(name => [name, body.files[name]]));
  if (names.some(name => !allowedFile(name)) || bytes !== encoded(metadata(files))) throw new Error('Invalid standalone scope or encoding');
  requirements(files);
  const allowedDirectories = new Set();
  for (const name of names) {
    let parent = path.posix.dirname(name);
    while (parent !== '.') { allowedDirectories.add(parent); parent = path.posix.dirname(parent); }
  }
  const observed = new Set();
  function walk(directory, prefix = '') {
    for (const name of fs.readdirSync(directory)) {
      const relative = prefix ? `${prefix}/${name}` : name;
      const full = physical(path.join(directory, name)), stat = fs.lstatSync(full);
      if (stat.isDirectory()) {
        if (!allowedDirectories.has(relative)) throw new Error('Unexpected artifact directory');
        walk(full, relative);
      } else if (stat.isFile()) {
        if (relative === manifestName) continue;
        if (!(relative in files) || typeof files[relative] !== 'string' || !/^[0-9a-f]{64}$/.test(files[relative])
          || sha(fs.readFileSync(full)) !== files[relative]) throw new Error('Unexpected artifact file or digest');
        observed.add(relative);
      } else throw new Error('Artifact must contain regular files');
    }
  }
  walk(root);
  if (observed.size !== names.length) throw new Error('Incomplete standalone artifact');
  return metadata(files);
}
