import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import Module from 'node:module';
import { fileURLToPath } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const macDir = path.join(root, 'macOS');
const require = Module.createRequire(path.join(macDir, 'x.js'));
const { waitForStaleBind, hasListener, engineInUse } = require(path.join(macDir, 'engine', 'port-settle.js'));

function fakes({ freeAfter = Infinity, listenerAt = Infinity, healthAt = Infinity }) {
  let clock = 0; let binds = 0; let listens = 0; let healths = 0; let waiting = 0;
  return {
    deps: {
      isBound: async () => { binds += 1; return binds < freeAfter; },
      hasListener: async () => { listens += 1; return listens >= listenerAt; },
      getHealth: async () => { healths += 1; return healths >= healthAt ? { ok: true } : null; },
      onWaiting: () => { waiting += 1; },
      sleep: async (ms) => { clock += ms; }, now: () => clock, budgetMs: 45000, pollMs: 1000,
    },
    stats: () => ({ binds, listens, waiting, clock }),
  };
}

const f1 = fakes({ freeAfter: 4 });
assert.equal(await waitForStaleBind(f1.deps), true, 'bind fails, connect refused: retries then starts');
assert.deepEqual([f1.stats().waiting, f1.stats().clock], [1, 4000]);
console.log('ok - retries once a second then starts');

const f2 = fakes({ listenerAt: 1 });
assert.equal(await waitForStaleBind(f2.deps), false, 'a listener on the first look refuses as today');
assert.equal(f2.stats().waiting, 0);
const f3 = fakes({ listenerAt: 3 });
assert.equal(await waitForStaleBind(f3.deps), false, 'a listener that appears mid-wait refuses');
console.log('ok - a listener refuses');

const f4 = fakes({});
assert.equal(await waitForStaleBind(f4.deps), false, 'the bound running out refuses');
assert.ok(f4.stats().clock >= 45000 && f4.stats().clock <= 46000);
console.log('ok - the bound runs out');

const f5 = fakes({ healthAt: 2 });
assert.equal(await waitForStaleBind(f5.deps), false, 'a health answer mid-wait refuses');
console.log('ok - health appearing refuses');

const server = net.createServer(); await new Promise((r) => server.listen(5019, '127.0.0.1', r));
assert.equal(await hasListener(5019), true);
await new Promise((r) => server.close(r));
assert.equal(await hasListener(5019), false, 'refused connect means no listener');
console.log('ok - hasListener tells a listener from a refusal');

const rig = (bindFreesAfter, listener) => { let n = 0; return { state: 'stopped', engineIsUp: async () => true, getHealth: async () => null, isPortInUse: async () => { n += 1; return n < bindFreesAfter; }, listener }; };
let clock = 0; const fast = { sleep: async (ms) => { clock += ms; }, now: () => clock };
const m1 = rig(4); assert.equal(await engineInUse(m1, 5018, { ...fast, hasListener: async () => false }), false); assert.equal(m1.state, 'starting');
const m2 = rig(4); assert.equal(await engineInUse(m2, 5018, { ...fast, hasListener: async () => true }), true); assert.equal(m2.state, 'stopped');
const m3 = rig(Infinity); assert.equal(await engineInUse(m3, 5018, { ...fast, hasListener: async () => false }), true); assert.equal(m3.state, 'stopped');
const m4 = rig(Infinity); m4.getHealth = async () => ({ ok: 1 }); assert.equal(await engineInUse(m4, 5018, { ...fast, hasListener: async () => false }), true);
console.log('ok - engineInUse: the shared start check');

const manager = fs.readFileSync(path.join(macDir, 'server-manager.js'), 'utf8');
assert.match(manager, /portInUse = await require\('\.\/engine\/port-settle'\)\.engineInUse\(this, port\)/, 'start() runs the wait at the shared check');
console.log('ok - start() wires the wait');

{
  const os = await import('node:os');
  const real = Module._load;
  Module._load = function load(request, ...rest) { return request === 'electron' ? { app: { isPackaged: false, getPath: () => os.tmpdir(), getVersion: () => '0' } } : real.call(this, request, ...rest); };
  let ServerManager;
  try { ServerManager = require(path.join(macDir, 'server-manager.js')); } finally { Module._load = real; }
  const sm = new ServerManager();
  let bodies = 0; let release; const gate = new Promise((r) => { release = r; });
  sm.startOnce = async () => { bodies += 1; await gate; };
  const first = sm.start(); const second = sm.start();
  await second; release(); await first;
  assert.equal(bodies, 1, 'the second click must not run a second start body');
  await sm.start(); assert.equal(bodies, 2, 'a start after the first finished runs again');
  console.log('ok - one start in flight at a time');

  const wait = rig(Infinity); let seen = null; wait.onStartNote = () => { seen = { startWait: wait.startWait, state: wait.state }; };
  await engineInUse(wait, 5018, { ...fast, hasListener: async () => false });
  assert.deepEqual(seen, { startWait: true, state: 'starting' }, 'the flag is up while waiting');
  assert.equal(wait.startWait, false, 'and down after');

  const main = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
  assert.match(main, /isProcessRunning\(\) \|\| serverManager\.startWait/, 'the health poll keeps starting during the wait');
  const { describeSignals } = require(path.join(macDir, 'tray-status.js'));
  assert.equal(describeSignals({ serverState: 'starting', serverNote: 'waiting for port 8000 to free up' }).server, 'waiting for port 8000 to free up');
  assert.equal(describeSignals({ serverState: 'starting' }).server, 'starting');
  const { runningStatus } = require(path.join(macDir, 'tray-menu', 'model', 'header.js'));
  const hd = runningStatus({ server: { state: 'starting', waitNote: 'waiting for port 8000 to free up' }, phone: {}, side: {}, appVersion: '1' }, (k) => k);
  assert.match(hd, /waiting for port 8000 to free up/);
  console.log('ok - the poll keeps starting and the tray shows the words');
}
