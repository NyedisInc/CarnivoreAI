import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const { registerPowerCalm } = require(path.join(here, '..', '..', 'macOS', 'power-calm.js'));

const tick = (ms = 30) => new Promise((r) => setTimeout(r, ms));

function rig({ thermal = 'nominal', pmset = 'lowpowermode 0\n' } = {}) {
  const powerMonitor = Object.assign(new EventEmitter(), { thermal, getCurrentThermalState() { return this.thermal; } });
  const app = new EventEmitter();
  const sent = [];
  let owned = true;
  const appWindow = { sendAll: (ch, v) => sent.push([ch, v]), ownsSender: () => owned };
  const state = { out: pmset, calls: [] };
  const execFile = (file, args, opts, cb) => { state.calls.push([file, args]); const out = state.out; setImmediate(() => (out instanceof Error ? cb(out) : cb(null, out, ''))); };
  const handle = registerPowerCalm({ powerMonitor, app, appWindow, execFile, debounceMs: 5, recheckMs: 60000 });
  return { powerMonitor, app, sent, state, handle, own: (v) => { owned = v; } };
}

test('serious thermal state calms once as thermal, nominal clears', async () => {
  const r = rig({ thermal: 'serious' });
  await tick();
  assert.deepEqual(r.sent, [['carnivore:power-calm', { calm: true, reason: 'thermal' }]]);
  r.powerMonitor.thermal = 'nominal';
  r.powerMonitor.emit('thermal-state-change');
  await tick();
  assert.deepEqual(r.sent.at(-1), ['carnivore:power-calm', { calm: false, reason: '' }]);
  assert.equal(r.sent.length, 2);
  r.handle.stop();
});

test('powermode 1 and lowpowermode 1 both mean low-power; pmset runs with fixed argv', async () => {
  for (const line of ['lowpowermode         1', ' powermode 1']) {
    const r = rig({ pmset: `System-wide power settings:\n${line}\n` });
    await tick();
    assert.deepEqual(r.sent, [['carnivore:power-calm', { calm: true, reason: 'low-power' }]]);
    assert.deepEqual(r.state.calls[0], ['/usr/bin/pmset', ['-g']]);
    r.handle.stop();
  }
});

test('unreadable pmset output, a pmset error, plain battery and powermode 2 never calm', async () => {
  for (const pmset of ['garbage', 'powermode 2\n', new Error('boom')]) {
    const r = rig({ pmset });
    r.powerMonitor.emit('on-battery');
    await tick();
    assert.deepEqual(r.sent, [], String(pmset));
    r.handle.stop();
  }
});

test('Low Power Mode turning off clears the calm on the next event', async () => {
  const r = rig({ pmset: 'lowpowermode 1\n' });
  await tick();
  r.state.out = 'lowpowermode 0\n';
  r.powerMonitor.emit('on-ac');
  await tick();
  assert.deepEqual(r.sent.map((s) => s[1].calm), [true, false]);
  r.handle.stop();
});

test('duplicate events and a burst send nothing new and read pmset once', async () => {
  const r = rig({ pmset: 'lowpowermode 1\n' });
  await tick();
  const reads = r.state.calls.length;
  for (const e of ['on-battery', 'resume', 'unlock-screen', 'on-ac']) r.powerMonitor.emit(e);
  await tick();
  assert.equal(r.sent.length, 1);
  assert.equal(r.state.calls.length, reads + 1);
  r.handle.stop();
});

test('a late window gets the current state at did-finish-load, only when calm and owned', async () => {
  const r = rig({ pmset: 'lowpowermode 1\n' });
  await tick();
  const mk = () => Object.assign(new EventEmitter(), { got: [], send(ch, v) { this.got.push([ch, v]); }, isDestroyed: () => false });
  const wc = mk(); r.app.emit('web-contents-created', {}, wc); wc.emit('did-finish-load');
  assert.deepEqual(wc.got, [['carnivore:power-calm', { calm: true, reason: 'low-power' }]]);
  const foreign = mk(); r.own(false); r.app.emit('web-contents-created', {}, foreign); foreign.emit('did-finish-load');
  assert.deepEqual(foreign.got, []);
  r.handle.stop();
});
