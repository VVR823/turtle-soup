/** Closed LOCAL standalone inputs and trace boundaries, not an OS sandbox. */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const project = fs.realpathSync(fileURLToPath(new URL('../', import.meta.url)));
const cache = path.join(project, '.cache');
function physical(input) {
  if (typeof input !== 'string' || !path.isAbsolute(input)) throw new Error('Absolute owned path required');
  const absolute = path.resolve(input), anchor = path.parse(absolute).root;
  let current = anchor;
  for (const part of path.relative(anchor, absolute).split(path.sep).filter(Boolean)) {
    current = path.join(current, part);
    const stat = fs.lstatSync(current);
    if (stat.isSymbolicLink() || fs.realpathSync(current) !== current) throw new Error('Standalone path may not redirect');
  }
  return absolute;
}
function ownedRoot(directory) {
  const root = physical(directory);
  if (path.dirname(root) !== cache || !/^ts07-frontend-[^\\/]+$/.test(path.basename(root))
    || !fs.lstatSync(root).isDirectory()) throw new Error('Owned standalone input required');
  return root;
}
function inside(root, name) {
  const relative = path.relative(root, name);
  return relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative);
}

export function standaloneConfiguration(config, directory) {
  const root = ownedRoot(directory);
  if (!config || Array.isArray(config) || typeof config !== 'object'
    || JSON.stringify(Object.keys(config).sort()) !== '["images","output"]'
    || config.output !== 'standalone' || !config.images || Array.isArray(config.images)
    || typeof config.images !== 'object' || JSON.stringify(Object.keys(config.images)) !== '["unoptimized"]'
    || config.images.unoptimized !== true) throw new Error('Unreviewed standalone configuration');
  return { output: 'standalone', images: { unoptimized: true }, outputFileTracingRoot: root };
}

export function validateStandaloneBuildInput(directory) {
  const root = ownedRoot(directory);
  const allowed = new Set(['package.json', 'package-lock.json', 'tsconfig.json', 'next.config.ts',
    'postcss.config.js', 'postcss.config.mjs', 'postcss.config.cjs', 'src', 'public', 'node_modules']);
  for (const name of fs.readdirSync(root)) if (!allowed.has(name)) throw new Error('Unexpected build input');
  function walk(folder) {
    for (const name of fs.readdirSync(folder)) {
      const full = path.join(folder, name), stat = fs.lstatSync(full);
      if (stat.isSymbolicLink() || fs.realpathSync(full) !== full) throw new Error('Build input link forbidden');
      if (stat.isDirectory()) walk(full);
      else if (!stat.isFile()) throw new Error('Build input must contain regular files');
    }
  }
  walk(root);
  const nextCli = physical(path.join(root, 'node_modules/next/dist/bin/next'));
  const configPath = physical(path.join(root, 'next.config.ts'));
  for (const name of [nextCli, configPath, path.join(root, 'package.json'), path.join(root, 'tsconfig.json')]) {
    if (!fs.lstatSync(name).isFile()) throw new Error('Required build input missing');
  }
  return { directory: root, nextCli, configPath };
}

export function checkedTracePath(directory, traceFile, entry) {
  const root = ownedRoot(directory);
  if (typeof traceFile !== 'string' || !path.isAbsolute(traceFile) || !inside(root, traceFile)
    || typeof entry !== 'string' || !entry || entry.includes('\\') || path.isAbsolute(entry)) {
    throw new Error('Invalid standalone trace path');
  }
  const trace = physical(traceFile);
  if (!fs.lstatSync(trace).isFile()) throw new Error('Trace manifest must be a file');
  const full = path.resolve(path.dirname(trace), entry);
  if (!inside(root, full)) throw new Error('Standalone trace escapes owned input');
  physical(full);
  if (!fs.lstatSync(full).isFile()) throw new Error('Traced input must be a regular file');
  return path.relative(root, full).split(path.sep).join('/');
}
