/** LOCAL demo artifact, never a production backup or permission to publish. */
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';

const appFiles = [
  '__init__', 'ai_host', 'audit_context', 'audit_events', 'audit_middleware', 'audit_store',
  'baselines', 'candidate_review_contracts', 'candidate_review', 'config', 'db',
  'feedback_contract', 'feedback_import', 'feedback_store', 'feedback_utils',
  'game_responses', 'game_service', 'game_store', 'host_cache', 'host_context',
  'host_evidence', 'host_rules', 'legacy_import', 'main', 'metrics_contracts', 'metrics',
  'migrations', 'post_publication_schema', 'post_publication_contracts', 'post_publication_store',
  'post_publication_source', 'post_publication_regression', 'post_publication_metrics', 'model_admission', 'model_gateway', 'paths', 'prompts',
  'question_normalization', 'rag', 'rate_limit', 'rate_policy', 'request_contract',
  'request_guards', 'request_lifecycle', 'rule_contract', 'rule_publication', 'runtime',
  'schemas', 'scoring', 'task_context', 'testing', 'trace_logger',
];
const agentFiles = [
  '__init__', 'admin_contracts', 'agent_prompt', 'contracts', 'decision_contracts',
  'preview', 'regression', 'repair_agent', 'source_identity', 'store', 'tool_contracts',
  'tools', 'validation', 'worker',
];
const routerFiles = ['__init__', 'admin_candidates', 'admin_regressions', 'agent_runs', 'audit', 'feedback', 'metrics'];
const evalFiles = ['__init__', 'legacy', 'catalog', 'contracts', 'manifest', 'grouping', 'inventory', 'proofs'];
export const backendReleaseFiles = Object.freeze([
  ...appFiles.map(name => `backend/app/${name}.py`),
  ...agentFiles.map(name => `backend/app/agents/${name}.py`),
  ...routerFiles.map(name => `backend/app/routers/${name}.py`),
  ...evalFiles.map(name => `backend/eval/${name}.py`),
  'backend/pyproject.toml', 'backend/uv.lock', 'backend/requirements.txt',
].sort());

const seedName = 'backend/app/soups.py';
const seed = Buffer.from('from .schemas import Soup\n\nSEED_SOUPS = [Soup(\n'
  + '    id="demo-synthetic", title="合成本地示例", surface="这只是部署演示",\n'
  + '    bottom="这是自行编写的合成示例，不代表真实题库", source="synthetic_demo",\n'
  + ').model_dump(mode="json")]\n');
const artifactFiles = [...backendReleaseFiles, seedName].sort();
const manifestName = 'release-manifest.json';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const encoded = value => JSON.stringify(value, null, 2) + '\n';

// Inspect each existing ancestor before reading/writing; an NTFS junction is
// a link too. This offline maintenance tool requires an exclusively owned
// tree, not an adversarial concurrently-mutating filesystem.
function safePath(input) {
  if (typeof input !== 'string' || !path.isAbsolute(input)) throw new Error('Absolute path required');
  const absolute = path.resolve(input);
  const anchor = path.parse(absolute).root;
  let current = anchor;
  for (const part of path.relative(anchor, absolute).split(path.sep).filter(Boolean)) {
    current = path.join(current, part);
    let stat;
    try { stat = fs.lstatSync(current); }
    catch (error) {
      if (error.code === 'ENOENT') break;
      throw error;
    }
    if (stat.isSymbolicLink() || fs.realpathSync(current) !== current) {
      throw new Error('Release paths may not redirect');
    }
  }
  return absolute;
}

function readFile(input) {
  const checked = safePath(input);
  if (!fs.lstatSync(checked).isFile()) throw new Error('Release input must be a regular file');
  return fs.readFileSync(checked);
}

function metadata(files) {
  return { schemaVersion: 1, localOnly: true, productionReady: false,
    dataKind: 'synthetic_demo', files };
}

export function buildBackendRelease(projectRoot, target) {
  const root = safePath(projectRoot);
  if (!fs.lstatSync(root).isDirectory()) throw new Error('Project directory required');
  const cache = safePath(path.join(root, '.cache'));
  const output = safePath(target);
  if (path.dirname(output) !== cache || fs.existsSync(output)) {
    throw new Error('Release needs a new direct child of project .cache');
  }
  // No glob, directory traversal or read of the original seed/private inputs.
  const sources = new Map(backendReleaseFiles.map(name => [name, readFile(path.join(root, name))]));
  const files = Object.fromEntries(artifactFiles.map(name => [name,
    sha(name === seedName ? seed : sources.get(name))]));
  fs.mkdirSync(cache, { recursive: true });
  safePath(cache);
  fs.mkdirSync(output);
  for (const name of artifactFiles) {
    const destination = path.join(output, name);
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.writeFileSync(destination, name === seedName ? seed : sources.get(name), { flag: 'wx' });
    if (sha(readFile(destination)) !== files[name]) throw new Error('Copied bytes differ');
  }
  for (const [name, bytes] of sources) {
    if (sha(readFile(path.join(root, name))) !== sha(bytes)) throw new Error('Release source changed');
  }
  const result = metadata(files);
  fs.writeFileSync(path.join(output, manifestName), encoded(result), { flag: 'wx' });
  return verifyBackendRelease(output);
}

export function verifyBackendRelease(target) {
  const root = safePath(target);
  if (!fs.lstatSync(root).isDirectory()) throw new Error('Artifact directory required');
  const bytes = readFile(path.join(root, manifestName)).toString('utf8');
  const body = JSON.parse(bytes);
  if (!body || typeof body !== 'object' || Array.isArray(body)
    || !body.files || typeof body.files !== 'object' || Array.isArray(body.files)) {
    throw new Error('Invalid release manifest');
  }
  const names = Object.keys(body.files).sort();
  if (JSON.stringify(names) !== JSON.stringify(artifactFiles)) throw new Error('Unexpected release scope');
  const files = Object.fromEntries(names.map(name => [name, body.files[name]]));
  // The builder's canonical encoding is the contract: duplicate keys, extra
  // metadata and noncanonical JSON cannot silently become a valid receipt.
  const expected = metadata(files);
  if (bytes !== encoded(expected)) throw new Error('Invalid release metadata or encoding');
  const allowedFiles = new Set([...artifactFiles, manifestName]);
  const allowedDirectories = new Set();
  for (const name of artifactFiles) {
    let directory = path.posix.dirname(name);
    while (directory !== '.') {
      allowedDirectories.add(directory);
      directory = path.posix.dirname(directory);
    }
  }
  const observed = new Set();
  function walk(directory, relative = '') {
    for (const name of fs.readdirSync(directory)) {
      const entry = relative ? `${relative}/${name}` : name;
      const full = safePath(path.join(directory, name));
      const stat = fs.lstatSync(full);
      if (stat.isDirectory()) {
        if (!allowedDirectories.has(entry)) throw new Error('Unexpected release directory');
        walk(full, entry);
      } else if (stat.isFile() && allowedFiles.has(entry)) observed.add(entry);
      else throw new Error('Unexpected release file');
    }
  }
  walk(root);
  if (observed.size !== allowedFiles.size) throw new Error('Incomplete release');
  for (const name of artifactFiles) {
    if (typeof files[name] !== 'string' || !/^[0-9a-f]{64}$/.test(files[name])
      || sha(readFile(path.join(root, name))) !== files[name]) throw new Error('Release digest differs');
  }
  if (files[seedName] !== sha(seed)) throw new Error('Non-synthetic demo seed');
  return expected;
}
