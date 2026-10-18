import { spawnSync } from 'node:child_process';

const timedOut = Symbol('timeout');

async function within(promise, milliseconds) {
  let timer;
  try {
    return await Promise.race([promise, new Promise(resolve => {
      timer = setTimeout(() => resolve(timedOut), milliseconds);
    })]);
  } finally { clearTimeout(timer); }
}

function killOwnedTree(child) {
  if (!Number.isSafeInteger(child.pid) || child.pid <= 0 || child.pid === process.pid
      || child.exitCode !== null || child.signalCode !== null) {
    throw new Error('Refusing to terminate a process without an active owned PID');
  }
  if (process.platform === 'win32') {
    // Direct executable + fixed args, never a string-built shell command.
    const result = spawnSync('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], {
      windowsHide: true, timeout: 3_000, encoding: 'utf8',
    });
    if (result.error || result.status !== 0) throw new Error('Owned process tree termination failed');
  } else {
    // The fixture is launched in its own process group, not the user's shell.
    process.kill(-child.pid, 'SIGKILL');
  }
}

export async function stopFixture(child, finished, {
  graceMs = 5_000, forceMs = 5_000, killTree = killOwnedTree,
  hasExited = () => child.exitCode !== null || child.signalCode !== null,
} = {}) {
  child.stdin.end();
  let result = await within(finished, graceMs);
  if (result !== timedOut) return result;
  // 'exit' can precede 'close' while descendants still hold stdout.
  if (hasExited()) throw new Error('Fixture launcher already exited; refusing stale PID termination');
  killTree(child);
  result = await within(finished, forceMs);
  if (result === timedOut) throw new Error('Owned fixture did not exit after forced cleanup');
  // A forced stop is a harness failure, never a successful green test run.
  throw new Error('Fixture required forced cleanup instead of a normal shutdown');
}
