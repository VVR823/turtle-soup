/** Physical, project-owned inputs for LOCAL standalone builds; no install. */
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { createSterileFrontend } from './frontend-build-policy.mjs';

const sha = bytes => createHash('sha256').update(bytes).digest('hex');
function checkedPath(input) {
  if (typeof input !== 'string' || !path.isAbsolute(input)) throw new Error('Absolute input root required');
  const absolute = path.resolve(input), anchor = path.parse(absolute).root;
  let current = anchor;
  for (const part of path.relative(anchor, absolute).split(path.sep).filter(Boolean)) {
    current = path.join(current, part);
    try {
      const stat = fs.lstatSync(current);
      if (stat.isSymbolicLink() || fs.realpathSync(current) !== current) {
        throw new Error('Standalone input may not redirect');
      }
    } catch (error) {
      if (error.code === 'ENOENT') break;
      throw error;
    }
  }
  return absolute;
}

function inventory(root) {
  checkedPath(root);
  if (!fs.lstatSync(root).isDirectory()) throw new Error('Installed dependency directory required');
  const files = [];
  function walk(directory) {
    for (const name of fs.readdirSync(directory).sort()) {
      const full = checkedPath(path.join(directory, name)), stat = fs.lstatSync(full);
      if (stat.isDirectory()) walk(full);
      else if (stat.isFile()) {
        const bytes = fs.readFileSync(full);
        files.push({ name: path.relative(root, full).split(path.sep).join('/'),
          bytes: bytes.length, sha256: sha(bytes) });
      } else throw new Error('Dependency input must contain regular files only');
    }
  }
  walk(root);
  return files.sort((left, right) => left.name < right.name ? -1 : left.name > right.name ? 1 : 0);
}

export function prepareStandaloneFrontend(projectRoot) {
  const root = checkedPath(projectRoot);
  if (!fs.lstatSync(root).isDirectory()) throw new Error('Project directory required');
  const cache = checkedPath(path.join(root, '.cache'));
  const installed = checkedPath(path.join(root, 'node_modules'));
  const before = inventory(installed);
  const directory = createSterileFrontend(root, cache);
  const modules = path.join(directory, 'node_modules');
  if (path.dirname(directory) !== cache || fs.realpathSync(directory) !== directory
    || !fs.lstatSync(modules).isSymbolicLink() || fs.realpathSync(modules) !== installed) {
    throw new Error('Unexpected sterile dependency link');
  }
  // Unlink precisely the link just created in this new owned fixture. Never
  // delete the installed directory or recurse through a junction.
  fs.unlinkSync(modules);
  fs.mkdirSync(modules);
  for (const file of before) {
    const source = checkedPath(path.join(installed, file.name));
    const destination = path.join(modules, file.name);
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.copyFileSync(source, destination, fs.constants.COPYFILE_EXCL);
    if (sha(fs.readFileSync(destination)) !== file.sha256) throw new Error('Copied dependency differs');
  }
  if (JSON.stringify(inventory(installed)) !== JSON.stringify(before)) {
    throw new Error('Installed dependency source changed');
  }
  if (JSON.stringify(inventory(modules)) !== JSON.stringify(before)) {
    throw new Error('Materialized dependency tree differs');
  }
  return { directory, dependencies: { files: before.length,
    bytes: before.reduce((total, file) => total + file.bytes, 0),
    digest: sha(JSON.stringify(before.map(file => [file.name, file.sha256]))) } };
}
