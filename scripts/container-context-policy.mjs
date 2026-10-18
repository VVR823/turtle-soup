/** Offline container INPUT only. No engine, image, runtime or production proof. */
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { verifyBackendRelease } from './backend-release-policy.mjs';
import { verifyStandaloneRelease } from './standalone-release-policy.mjs';

const project = fs.realpathSync(fileURLToPath(new URL('../', import.meta.url)));
const cache = path.join(project, '.cache');
const manifest = 'context-manifest.json';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const encode = value => JSON.stringify(value, null, 2) + '\n';
function physical(input) {
  if (typeof input !== 'string' || !path.isAbsolute(input)) throw new Error('Absolute context path required');
  const absolute = path.resolve(input), anchor = path.parse(absolute).root;
  let current = anchor;
  for (const part of path.relative(anchor, absolute).split(path.sep).filter(Boolean)) {
    current = path.join(current, part);
    try {
      if (fs.lstatSync(current).isSymbolicLink() || fs.realpathSync(current) !== current) {
        throw new Error('Context path may not redirect');
      }
    } catch (error) {
      if (error.code === 'ENOENT') break;
      throw error;
    }
  }
  return absolute;
}
function provenance(kind, artifact) {
  const root = physical(artifact);
  let release;
  if (kind === 'backend') release = verifyBackendRelease(root);
  else if (kind === 'frontend') release = verifyStandaloneRelease(root);
  else throw new Error('Unknown container input kind');
  const receipt = fs.readFileSync(physical(path.join(root, 'release-manifest.json')));
  const files = Object.fromEntries([...Object.keys(release.files), 'release-manifest.json'].sort()
    .map(name => [`release/${name}`, name === 'release-manifest.json' ? sha(receipt) : release.files[name]]));
  return { schemaVersion: 1, localOnly: true, productionReady: false,
    containerBuildVerified: false, kind, sourceManifestDigest: sha(receipt), files };
}
function targetPath(artifact, target) {
  const root = physical(artifact), output = physical(target);
  physical(cache);
  if (path.dirname(output) !== cache || root === output
    || root.startsWith(output + path.sep) || output.startsWith(root + path.sep)) {
    throw new Error('Context needs a separate direct cache child');
  }
  return output;
}

export function buildContainerContext(kind, artifact, target) {
  const output = targetPath(artifact, target);
  if (fs.existsSync(output)) throw new Error('Context output must be new');
  const expected = provenance(kind, artifact);
  fs.mkdirSync(output);
  for (const [name, digest] of Object.entries(expected.files)) {
    const source = physical(path.join(artifact, name.slice('release/'.length)));
    const destination = path.join(output, name);
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.copyFileSync(source, destination, fs.constants.COPYFILE_EXCL);
    if (sha(fs.readFileSync(physical(destination))) !== digest) throw new Error('Copied context bytes differ');
  }
  if (encode(provenance(kind, artifact)) !== encode(expected)) throw new Error('Context source changed');
  fs.writeFileSync(path.join(output, manifest), encode(expected), { flag: 'wx' });
  return verifyContainerContext(kind, artifact, output);
}

export function verifyContainerContext(kind, artifact, target) {
  const root = targetPath(artifact, target);
  const expected = provenance(kind, artifact);
  if (!fs.lstatSync(root).isDirectory()) throw new Error('Context directory required');
  if (fs.readFileSync(physical(path.join(root, manifest)), 'utf8') !== encode(expected)) {
    throw new Error('Context provenance or encoding differs');
  }
  const directories = new Set();
  for (const name of Object.keys(expected.files)) {
    let parent = path.posix.dirname(name);
    while (parent !== '.') { directories.add(parent); parent = path.posix.dirname(parent); }
  }
  const seen = new Set();
  function walk(directory, prefix = '') {
    for (const name of fs.readdirSync(directory)) {
      const relative = prefix ? `${prefix}/${name}` : name;
      const entry = physical(path.join(directory, name)), stat = fs.lstatSync(entry);
      if (stat.isDirectory()) {
        if (!directories.has(relative)) throw new Error('Unexpected context directory');
        walk(entry, relative);
      } else if (stat.isFile() && relative === manifest) seen.add(relative);
      else if (stat.isFile() && Object.hasOwn(expected.files, relative)
        && sha(fs.readFileSync(entry)) === expected.files[relative]) seen.add(relative);
      else throw new Error('Unexpected context file or digest');
    }
  }
  walk(root);
  if (seen.size !== Object.keys(expected.files).length + 1) throw new Error('Incomplete context');
  if (encode(provenance(kind, artifact)) !== encode(expected)) throw new Error('Context source changed during verification');
  return expected;
}
