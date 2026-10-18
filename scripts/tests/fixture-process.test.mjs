import assert from 'node:assert/strict';
import test from 'node:test';
import { stopFixture } from '../fixture-process.mjs';

function fixture() {
  let ends = 0;
  return { child: { exitCode: null, signalCode: null, stdin: { end() { ends++; } } }, count: () => ends };
}

test('normal EOF shutdown needs no process termination', async () => {
  const { child, count } = fixture();
  assert.deepEqual(await stopFixture(child, Promise.resolve({ code: 0 }), {
    killTree() { assert.fail('normal shutdown must not kill anything'); },
  }), { code: 0 });
  assert.equal(count(), 1);
});

test('failed fixture exit is returned for the runner to reject', async () => {
  const { child } = fixture();
  assert.equal((await stopFixture(child, Promise.resolve({ code: 1 }))).code, 1);
});

test('stuck fixture triggers only the owned child and fails the harness', async () => {
  const { child } = fixture();
  let complete;
  const finished = new Promise(resolve => { complete = resolve; });
  await assert.rejects(stopFixture(child, finished, {
    graceMs: 5, forceMs: 5,
    killTree(target) { assert.equal(target, child); complete({ code: 1 }); },
  }), /required forced cleanup/);
});

test('cleanup that still never exits has a bounded failure', async () => {
  const { child } = fixture();
  await assert.rejects(stopFixture(child, new Promise(() => {}), {
    graceMs: 5, forceMs: 5, killTree() {},
  }), /did not exit/);
});

test('signal exit never authorizes termination of the old PID', async () => {
  const { child } = fixture();
  child.signalCode = 'SIGTERM';
  await assert.rejects(stopFixture(child, new Promise(() => {}), {
    graceMs: 5, killTree() { assert.fail('stale PID must not be terminated'); },
  }), /already exited/);
});

test('observed exit blocks termination before close even with null codes', async () => {
  const { child } = fixture();
  await assert.rejects(stopFixture(child, new Promise(() => {}), {
    graceMs: 5, hasExited: () => true,
    killTree() { assert.fail('exited launcher must not be terminated'); },
  }), /already exited/);
});
