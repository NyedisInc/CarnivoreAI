// WHY THIS FILE EXISTS
//     }

import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const macDir = path.join(here, '..', 'macOS');

const { terminateProcess, isAlive } = require(path.join(macDir, 'process-teardown.js'));

let passed = 0;
let failed = 0;
const pending = [];

function test(name, fn) {
  pending.push([name, fn]);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function spawnChild(body) {
  const child = spawn(process.execPath, ['-e', body], {
    stdio: ['ignore', 'pipe', 'ignore'],
  });
  let ready = false;
  child.stdout.on('data', (buf) => {
    if (String(buf).includes('ready')) ready = true;
  });
  for (let i = 0; i < 250 && !ready; i += 1) {
    await sleep(20);
  }
  assert.ok(ready, 'the helper child never announced itself ready');
  assert.ok(isAlive(child.pid), 'the helper child never came up');
  return child;
}

const OBEDIENT = "console.log('ready'); setInterval(() => {}, 1000);";

const STUBBORN =
  "process.on('SIGTERM', () => {}); console.log('ready'); " +
  'setInterval(() => {}, 1000);';

test('a process that ignores SIGTERM is still dead when the routine returns', async () => {
  const child = await spawnChild(STUBBORN);
  const result = await terminateProcess(child.pid, { graceMs: 600, pollMs: 50 });

  assert.equal(
    isAlive(child.pid),
    false,
    'the pid is STILL ALIVE after terminateProcess returned. This is the ' +
    'orphan that gets adopted by the next version of the app.'
  );
  assert.equal(result.terminated, true);
  assert.equal(
    result.outcome,
    'sigkill',
    'a SIGTERM-ignoring process must be reported as having needed SIGKILL, ' +
    'so the escalation is visible rather than assumed'
  );
  assert.equal(result.escalated, true);
});

test('a well-behaved process dies on SIGTERM and is never escalated against', async () => {
  const child = await spawnChild(OBEDIENT);
  const result = await terminateProcess(child.pid, { graceMs: 3000, pollMs: 50 });

  assert.equal(isAlive(child.pid), false, 'the obedient child survived');
  assert.equal(result.terminated, true);
  assert.equal(result.outcome, 'sigterm');
  assert.equal(
    result.escalated,
    false,
    'SIGKILL was used on a process that would have exited on SIGTERM, which ' +
    'denies the server its chance to flush connections'
  );
});

test('a pid that is already gone reports already-gone, not a fake kill', async () => {
  const child = await spawnChild(OBEDIENT);
  const pid = child.pid;
  process.kill(pid, 'SIGKILL');
  for (let i = 0; i < 100 && isAlive(pid); i += 1) {
    await sleep(20);
  }
  assert.equal(isAlive(pid), false, 'could not pre-kill the helper child');

  const result = await terminateProcess(pid, { graceMs: 500, pollMs: 50 });
  assert.equal(result.terminated, true);
  assert.equal(
    result.outcome,
    'already-gone',
    'a pid that was already dead must say so; reporting "sigterm" would ' +
    'claim a kill that never happened'
  );
  assert.equal(result.escalated, false);
});

test('a pid that cannot be determined is a third outcome, never a success', async () => {
  const result = await terminateProcess(1, { graceMs: 200, pollMs: 50 });
  assert.equal(
    result.terminated,
    false,
    'a process we are not permitted to signal was reported as terminated'
  );
  assert.equal(result.outcome, 'not-permitted');
  assert.equal(isAlive(1), true, 'launchd should still be running');
});

test('a null or nonsense pid is refused rather than signalled', async () => {
  for (const bad of [null, undefined, 0, -1, NaN, 'x']) {
    const result = await terminateProcess(bad, { graceMs: 100, pollMs: 50 });
    assert.equal(result.terminated, false, `pid ${String(bad)} was accepted`);
    assert.equal(result.outcome, 'no-pid');
  }
  assert.equal((await terminateProcess(-1, {})).outcome, 'no-pid');
});

test('isAlive answers from the kernel and distinguishes gone from unknowable', async () => {
  assert.equal(isAlive(process.pid), true, 'this very process reads as dead');
  assert.equal(isAlive(1), true, 'launchd reads as dead because EPERM was ' +
    'mistaken for ESRCH');
});

(async () => {
  console.log('process-teardown: killing things and asking the kernel whether they died');
  for (const [name, fn] of pending) {
    try {
      await fn();
      console.log(`  ok   ${name}`);
      passed += 1;
    } catch (err) {
      console.log(`  FAIL ${name}`);
      console.log(`       ${err.message}`);
      failed += 1;
    }
  }
  console.log(`\nprocess-teardown: ${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
  console.log('ALL PASS');
})();
