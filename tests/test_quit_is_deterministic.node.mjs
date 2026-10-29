// WHY THIS FILE EXISTS

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const macDir = path.join(here, '..', 'macOS');
const mainSrc = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
const managerSrc = fs.readFileSync(path.join(macDir, 'server-manager.js'), 'utf8');

const { createQuitHandler } = require(path.join(macDir, 'quit-sequence.js'));

let passed = 0;
let failed = 0;
const pending = [];

function test(name, fn) {
  pending.push([name, fn]);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function tick() {
  return new Promise((resolve) => setImmediate(resolve));
}

function fakeEvent() {
  const ev = { defers: 0, preventDefault: () => { ev.defers += 1; } };
  return ev;
}


test('runtime: the quit is deferred and NOT issued until the teardown resolves', async () => {
  const order = [];
  let releaseTeardown;
  const handler = createQuitHandler({
    teardown: async () => {
      order.push('teardown:start');
      await new Promise((r) => { releaseTeardown = r; });
      order.push('teardown:end');
    },
    quit: () => order.push('quit'),
  });

  const ev = fakeEvent();
  const inFlight = handler(ev);
  await sleep(20);

  assert.equal(ev.defers, 1, 'the quit was never deferred');
  assert.deepEqual(
    order,
    ['teardown:start'],
    'the app quit while the server teardown was still in flight. This is the ' +
    'race that orphaned pid 5491.'
  );

  releaseTeardown();
  await inFlight;
  await tick();
  assert.deepEqual(order, ['teardown:start', 'teardown:end', 'quit']);
});

test('runtime: the re-issued quit runs on a fresh task, not in the before-quit microtask drain', async () => {
  let quits = 0;
  const handler = createQuitHandler({
    teardown: async () => null,
    quit: () => { quits += 1; },
  });

  await handler(fakeEvent());
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
  assert.equal(
    quits,
    0,
    'the quit was re-issued inside the first quit call, so Electron overwrites ' +
    'its "quitting" flag and the app closes its windows but never exits'
  );
  await tick();
  assert.equal(quits, 1, 'the deferred quit never ran');
});

test('runtime: the re-issued quit passes straight through, it does not defer again', async () => {
  const order = [];
  let teardowns = 0;
  const handler = createQuitHandler({
    teardown: async () => { teardowns += 1; order.push('teardown'); },
    quit: () => order.push('quit'),
  });

  await handler(fakeEvent());
  const second = fakeEvent();
  await handler(second);

  assert.equal(
    second.defers,
    0,
    'the handler deferred its own re-issued quit, so the app can never quit ' +
    'at all - an infinite quit loop, worse than the leak being fixed'
  );
  assert.equal(teardowns, 1, 'the server was torn down twice');
});

test('runtime: a second quit ARRIVING DURING the teardown is deferred but does not re-tear-down', async () => {
  let teardowns = 0;
  let release;
  let quits = 0;
  const handler = createQuitHandler({
    teardown: async () => {
      teardowns += 1;
      await new Promise((r) => { release = r; });
    },
    quit: () => { quits += 1; },
  });

  const first = handler(fakeEvent());
  await sleep(10);
  const mid = fakeEvent();
  await handler(mid);

  assert.equal(
    mid.defers,
    1,
    'a quit that arrived mid-teardown was let through, which quits the app ' +
    'out from under the stop it is waiting for - the original bug, one door over'
  );
  assert.equal(teardowns, 1, 'a second teardown was started concurrently');

  release();
  await first;
  await tick();
  assert.equal(quits, 1, 'the app quit more or fewer than exactly once');
});

test('runtime: a teardown that throws still quits, and reports', async () => {
  let quits = 0;
  const errors = [];
  const handler = createQuitHandler({
    teardown: async () => { throw new Error('stop blew up'); },
    quit: () => { quits += 1; },
    onError: (msg, err) => errors.push(err.message),
  });

  await handler(fakeEvent());
  await tick();
  assert.equal(
    quits,
    1,
    'a failing teardown left the app unable to quit. Cmd-Q must always work.'
  );
  assert.deepEqual(errors, ['stop blew up'], 'the failure was swallowed silently');
});

test('runtime: missing collaborators are refused at construction, not at quit time', () => {
  assert.throws(() => createQuitHandler({ quit: () => {} }), /teardown/);
  assert.throws(() => createQuitHandler({ teardown: async () => {} }), /quit/);
});


test('wiring (SOURCE-LEVEL): main.js registers the tested handler, not an ad-hoc async listener', () => {
  assert.ok(
    /require\('\.\/quit-sequence'\)/.test(mainSrc),
    'main.js does not use quit-sequence.js, so whatever it does on quit is ' +
    'untested'
  );
  const at = mainSrc.lastIndexOf("'before-quit'");
  assert.notEqual(at, -1, 'no before-quit handler is registered at all');
  const registration = mainSrc.slice(at, at + 400);
  assert.ok(
    /createQuitHandler\(/.test(registration),
    'before-quit is still registered with an inline async function. Electron ' +
    'does not await one, so the teardown races the quit.'
  );
});

test('wiring (SOURCE-LEVEL): stop() no longer decides escalation from ChildProcess.killed', () => {
  const at = managerSrc.indexOf('async stop(');
  assert.notEqual(at, -1, 'stop() is gone');
  const body = managerSrc.slice(at, at + 4000);
  const code = body
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');
  assert.ok(
    !/\.killed/.test(code),
    'stop() still reads ChildProcess.killed, which means "a signal was sent", ' +
    'not "the process died" - the guard that made SIGKILL unreachable'
  );
  assert.ok(
    /terminateProcess\(/.test(code),
    'stop() does not call terminateProcess, so nothing confirms the exit'
  );
  assert.ok(
    /isAlive\(/.test(code),
    'stop() sets state without asking the kernel whether the process exited, ' +
    'so the tray can report stopped for a server that is still serving'
  );
});

test('wiring (SOURCE-LEVEL): isProcessRunning asks the kernel rather than a stale flag', () => {
  const at = managerSrc.indexOf('  isProcessRunning() {');
  assert.notEqual(at, -1, 'isProcessRunning is gone');
  const body = managerSrc.slice(at, at + 1400);
  const code = body
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');
  assert.ok(
    !/\.killed/.test(code),
    'isProcessRunning short-circuits on ChildProcess.killed, so it answers ' +
    '"running" about a process it never measured'
  );
  assert.ok(/isAlive\(/.test(code), 'no kernel liveness check');
});

(async () => {
  console.log('quit determinism: does the app wait for the server to actually die');
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
  console.log(`\nquit determinism: ${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
  console.log('ALL PASS');
})();
