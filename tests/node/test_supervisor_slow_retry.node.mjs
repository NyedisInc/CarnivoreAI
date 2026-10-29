import test, { mock } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import Module, { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const macDir = path.join(import.meta.dirname, '..', '..', 'macOS');

function load() {
  const realLoad = Module._load;
  Module._load = function (request, ...rest) { return request === 'electron' ? { app: { getPath: () => '/tmp', getVersion: () => '0.0.0', isPackaged: false } } : realLoad.call(this, request, ...rest); };
  try { return require(path.join(macDir, 'server-manager.js')); } finally { Module._load = realLoad; }
}

function build(held) {
  const SM = load();
  const m = new SM();
  m.starts = 0;
  m.start = async () => {
    if (held.on) throw Object.assign(new Error('port held'), { code: 'PORT_HOLDER_NOT_CARNIVORE' });
    m.starts += 1;
    m.state = 'running';
  };
  return m;
}

test('stranger holds the port: fast restarts spent, slow retry starts our engine once when it is freed', async (t) => {
  t.mock.method(console, 'log', () => {});
  t.mock.method(console, 'error', () => {});
  mock.timers.enable({ apis: ['setTimeout'] });
  t.after(() => mock.timers.reset());
  const held = { on: true };
  const m = build(held);
  m.superviseDown({ expected: false });
  for (const ms of [5000, 15000, 45000]) { mock.timers.tick(ms); await new Promise((r) => setImmediate(r)); }
  assert.equal(m.supervisor.status().gaveUp, true);
  assert.equal(m.slowRetry.pending(), true);
  mock.timers.tick(60000); await new Promise((r) => setImmediate(r));
  assert.equal(m.starts, 0);
  assert.equal(m.slowRetry.pending(), true, 'still held: one timer re-armed');
  held.on = false;
  mock.timers.tick(60000); await new Promise((r) => setImmediate(r));
  assert.equal(m.starts, 1);
  assert.equal(m.slowRetry.pending(), false);
  mock.timers.tick(600000); await new Promise((r) => setImmediate(r));
  assert.equal(m.starts, 1);
});

test('a deliberate stop during the slow retry starts nothing', async (t) => {
  t.mock.method(console, 'log', () => {});
  t.mock.method(console, 'error', () => {});
  mock.timers.enable({ apis: ['setTimeout'] });
  t.after(() => mock.timers.reset());
  const held = { on: true };
  const m = build(held);
  m.superviseDown({ expected: false });
  for (const ms of [5000, 15000, 45000]) { mock.timers.tick(ms); await new Promise((r) => setImmediate(r)); }
  assert.equal(m.slowRetry.pending(), true);
  m.slowRetry.cancel();
  held.on = false;
  mock.timers.tick(300000); await new Promise((r) => setImmediate(r));
  assert.equal(m.starts, 0);
  held.on = true;
  m.superviseDown({ expected: false, startError: Object.assign(new Error('x'), { code: 'PORT_HOLDER_NOT_CARNIVORE' }) });
  assert.equal(m.slowRetry.pending(), true);
  m.stopRequested = true; held.on = false;
  mock.timers.tick(60000); await new Promise((r) => setImmediate(r));
  assert.equal(m.starts, 0);
});
