import test from 'node:test';
import assert from 'node:assert/strict';
import { PassThrough } from 'node:stream';
import { EventEmitter } from 'node:events';
import { superviseFrontend } from '../ui-frontend-process.mjs';

function fixture() {
  const child = new EventEmitter();
  child.stdout = new PassThrough(); child.stdin = new PassThrough();
  child.exitCode = null; child.signalCode = null;
  let finish;
  const finished = new Promise(resolve => { finish = resolve; });
  const kills = [];
  child.kill = signal => {
    kills.push(signal); child.signalCode = signal;
    finish({ code: null, signal }); return true;
  };
  const input = new PassThrough(); const lines = [];
  return { child, finished, input, lines, kills, finish,
    run: () => superviseFrontend({ child, finished, input, emit: line => lines.push(line), instanceId: 'owned-nonce', readyMs: 100, graceMs: 100 }) };
}

test('owned Next readiness announces nonce and EOF normally closes that child', async () => {
  const f = fixture(); const run = f.run();
  f.child.stdout.write('  ✓ Ready in 70ms\n');
  assert.deepEqual(f.lines, ['TS08_FRONTEND_READY:owned-nonce']);
  f.input.end(); await run;
  assert.deepEqual(f.kills, ['SIGTERM']);
});
test('an unexpected child exit is failure and must not terminate a reused PID', async () => {
  const f = fixture(); const run = f.run();
  f.child.exitCode = 1; f.finish({ code: 1, signal: null });
  await assert.rejects(run, /unexpected|before readiness/);
  f.input.end(); assert.deepEqual(f.kills, []);
});
test('incomplete or foreign readiness text never announces ownership', async () => {
  const f = fixture(); const run = f.run();
  f.child.stdout.write('somebody else Ready\n  ✓ Ready in');
  assert.deepEqual(f.lines, []);
  f.child.stdout.write(' 80ms\n');
  assert.deepEqual(f.lines, ['TS08_FRONTEND_READY:owned-nonce']);
  f.input.end(); await run;
});
test('EOF before readiness safely closes only the owned child and fails startup', async () => {
  const f = fixture(); const run = f.run();
  f.input.end(); await assert.rejects(run, /before readiness/);
  assert.deepEqual(f.kills, ['SIGTERM']);
  assert.deepEqual(f.lines, []);
});
test('an unsuccessful exit after intentional shutdown still fails the wrapper', async () => {
  const f = fixture();
  f.child.kill = () => { f.child.exitCode = 2; f.finish({ code: 2, signal: null }); return true; };
  const run = f.run(); f.child.stdout.write('✓ Ready in 1ms\n'); f.input.end();
  await assert.rejects(run, /shutdown/);
});
