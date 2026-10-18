/** Next does not honor stdin EOF: this wrapper owns its shutdown instead. */
import { stopFixture } from './fixture-process.mjs';

export async function superviseFrontend({ child, finished, input, emit, instanceId,
  readyMs = 30_000, graceMs = 5_000 }) {
  let ready = false; let text = ''; let timer; let stop;
  const eof = new Promise(resolve => { stop = resolve; });
  const onEnd = () => stop();
  const onData = buffer => {
    text += buffer.toString().replaceAll('\r', '');
    const lines = text.split('\n'); text = lines.pop();
    if (!ready && lines.some(line => /^\s*(?:✓\s*)?Ready in \d+(?:\.\d+)?m?s\s*$/.test(line))) {
      ready = true; clearTimeout(timer); emit(`TS08_FRONTEND_READY:${instanceId}`);
    }
  };
  child.stdout.on('data', onData); input.once('end', onEnd); input.resume();
  const startupTimeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error('Owned frontend timed out before readiness')), readyMs);
  });
  try {
    const outcome = await Promise.race([
      finished.then(() => { throw new Error(ready ? 'Owned frontend exited unexpectedly' : 'Owned frontend exited before readiness'); }),
      eof.then(() => 'eof'), startupTimeout,
    ]);
    if (outcome === 'eof') {
      if (child.exitCode === null && child.signalCode === null) child.kill('SIGTERM');
      const result = await stopFixture(child, finished, { graceMs });
      if (result.code !== 0 && result.signal !== 'SIGTERM') throw new Error('Owned frontend shutdown failed');
      if (!ready) throw new Error('Parent closed before readiness');
    }
  } finally {
    clearTimeout(timer); input.off('end', onEnd); child.stdout.off('data', onData);
    if (child.exitCode === null && child.signalCode === null) {
      child.kill('SIGTERM'); await stopFixture(child, finished, { graceMs });
    }
  }
}
