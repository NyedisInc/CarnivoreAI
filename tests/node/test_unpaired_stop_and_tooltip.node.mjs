import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import net from 'node:net';
import { spawn } from 'node:child_process';
import Module, { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const macDir = path.join(import.meta.dirname, '..', '..', 'macOS');
const { stopEngine, engineListening } = require(path.join(macDir, 'engine', 'engine-lifecycle.js'));
const { describeSignals } = require(path.join(macDir, 'tray-status.js'));

const portTrust = require(path.join(macDir, 'tray-menu', 'port-trust.js'));
const { execFile } = require('node:child_process');
const FAKE_HEALTH = { status: 'ok', uptime: 5, version: '1.2.3' };

async function reap(...children) {
  await Promise.all(children.map((c) => (c.exitCode !== null || c.signalCode ? null : new Promise((resolve) => { c.once('exit', resolve); c.kill('SIGKILL'); }))));
}

const probeAt = (port) => new Promise((resolve) => {
  const s = net.connect(port, '127.0.0.1', () => { s.destroy(); resolve(true); });
  s.on('error', () => resolve(false));
});

async function listen(port) {
  const child = spawn(process.execPath, ['-e', `require('net').createServer().listen(${port}, '127.0.0.1')`], { stdio: 'ignore' });
  const probe = () => new Promise((resolve) => {
    const s = net.connect(port, '127.0.0.1', () => { s.destroy(); resolve(true); });
    s.on('error', () => resolve(false));
  });
  for (let i = 0; i < 50 && !(await probe()); i += 1) await new Promise((r) => setTimeout(r, 100));
  return { child, probe };
}

function managerFor(port, probe, record, health = FAKE_HEALTH) {
  return {
    ownedProcess: false, engineRecord: record, getPort: () => port, engineIsUp: (p) => probeAt(p || port), getHealth: async () => health,
    readSetupFacts: () => ({ envText: '', configText: '{}', pairedExists: false }), getSetupVerdict: () => ({ status: 'incomplete' }),
  };
}

test('an un-adopted same-user listener is refused and survives the unpaired stop', async () => {
  const { child, probe } = await listen(5041);
  try {
    const r = await stopEngine(managerFor(5041, probe, null), { getApi: () => null });
    assert.equal(r.stopped, false, JSON.stringify(r));
    assert.equal(await probe(), true, 'the stranger must still be listening');
  } finally { await reap(child); }
});

test('a record whose pid is not the listener, whose start time or version differs is refused', async () => {
  const { child, probe } = await listen(5042);
  const second = await listen(5043);
  try {
    const ident = await portTrust.processIdentity(child.pid, { execFile });
    const good = { pid: child.pid, start: ident.start, exe: ident.exe, port: 5042, version: '1.2.3' };
    for (const [label, mgr] of [
      ['other pid', managerFor(5042, probe, { ...good, pid: second.child.pid })],
      ['stale start', managerFor(5042, probe, { ...good, start: 'Mon Jan  1 00:00:00 2001' })],
      ['other version', managerFor(5042, probe, good, { ...FAKE_HEALTH, version: '9.9.9' })],
    ]) {
      const r = await stopEngine(mgr, { getApi: () => null });
      assert.equal(r.stopped, false, `${label}: ${JSON.stringify(r)}`);
    }
    assert.equal(await probe(), true);
    assert.equal(await second.probe(), true);
  } finally { await reap(child, second.child); }
});

test('the listener own setup_status cannot steer the stop onto the kill path, and a signed-in client keeps the route', async () => {
  const { child, probe } = await listen(5044);
  try {
    const ident = await portTrust.processIdentity(child.pid, { execFile });
    const good = { pid: child.pid, start: ident.start, exe: ident.exe, port: 5044, version: '1.2.3' };
    const complete = { ...managerFor(5044, probe, good), readSetupFacts: () => ({ envText: 'TOTP_SECRET=a\nJWT_SECRET=b', configText: '{}', pairedExists: true }), getSetupVerdict: () => ({ status: 'incomplete' }) };
    assert.equal((await stopEngine(complete, { getApi: () => null })).stopped, false);
    const signedIn = managerFor(5044, probe, good);
    const r = await stopEngine(signedIn, { getApi: () => ({ sendAuthed: async () => ({ reachable: false, error: 'x' }) }) });
    assert.equal(r.outcome, 'route-failed');
    assert.equal(await probe(), true);
  } finally { await reap(child); }
});

test('the exact adopted engine on an unfinished setup is stopped with no tray client', async () => {
  const { child, probe } = await listen(5045);
  try {
    const ident = await portTrust.processIdentity(child.pid, { execFile });
    const good = { pid: child.pid, start: ident.start, exe: ident.exe, port: 5045, version: '1.2.3' };
    const r = await stopEngine(managerFor(5045, probe, good), { getApi: () => null });
    assert.equal(r.stopped, true, JSON.stringify(r));
    assert.equal(await probe(), false);
  } finally { await reap(child); }
});

test('a silent listener that fails the health and bind probes is not reported already-down, and is not signalled without proof (decision 36 a)', async () => {
  const { child, probe } = await listen(5046);
  try {
    const ident = await portTrust.processIdentity(child.pid, { execFile });
    const good = { pid: child.pid, start: ident.start, exe: ident.exe, port: 5046, version: '1.2.3' };
    const silent = { ...managerFor(5046, probe, good, null), engineIsUp: async () => false };
    const r = await stopEngine(silent, { getApi: () => null });
    assert.equal(r.stopped, false, JSON.stringify(r));
    assert.notEqual(r.outcome, 'already-down');
    assert.equal(await probeAt(5046), true, 'the engine must still be listening');
    const nobody = await stopEngine({ ...managerFor(5047, probe, null), engineIsUp: async () => false }, { getApi: () => null });
    assert.equal(nobody.outcome, 'already-down', 'nothing listening is the only already-down');
  } finally { await reap(child); }
});

test('a PORT change after adoption still stops the engine on the port it was adopted on (decision 36 b)', async () => {
  const { child, probe } = await listen(5048);
  try {
    const ident = await portTrust.processIdentity(child.pid, { execFile });
    const good = { pid: child.pid, start: ident.start, exe: ident.exe, port: 5048, version: '1.2.3' };
    const moved = { ...managerFor(5048, probe, good), getPort: () => 5049 };
    const r = await stopEngine(moved, { getApi: () => null });
    assert.equal(r.stopped, true, JSON.stringify(r));
    assert.equal(r.outcome, 'stopped');
    assert.equal(await probeAt(5048), false);
  } finally { await reap(child); }
});

test('a failed lsof is null (could not tell), never an empty list that reads as nothing listening (decision 36 c)', async () => {
  const failing = (file, args, opts, cb) => cb(new Error('lsof timed out'), '');
  assert.equal(await portTrust.listeners(5053, { execFile: failing }), null);
  const none = (file, args, opts, cb) => cb(Object.assign(new Error('exit 1'), { code: 1 }), '');
  assert.deepEqual(await portTrust.listeners(5053, { execFile: none }), [], 'lsof exits 1 with no output when nothing listens');
  assert.deepEqual(portTrust.judgePort({ holders: null, myUid: 1, health: null }).reason, 'unknown');
});

test('engineListening answers up when lsof could not tell (null), and the stop does not report already-down', async () => {
  const realListeners = portTrust.listeners;
  const manager = { ...managerFor(5054, null, null), engineIsUp: async () => false };
  try {
    portTrust.listeners = async () => null;
    assert.equal(await engineListening(manager, 5054), true, 'a failed lsof reads as up');
    const r = await stopEngine(manager, { getApi: () => null });
    assert.notEqual(r.outcome, 'already-down');
    portTrust.listeners = async () => [];
    assert.equal(await engineListening(manager, 5054), false, 'an empty list is the only nothing-listens');
  } finally { portTrust.listeners = realListeners; }
});

test('engineIsUp health-probes the port it was asked about, not the configured one (decision 36 d)', async () => {
  const os = await import('node:os');
  const real = Module._load;
  Module._load = function load(request, ...rest) { return request === 'electron' ? { app: { isPackaged: false, getPath: () => os.tmpdir(), getVersion: () => '0' } } : real.call(this, request, ...rest); };
  let ServerManager;
  try { ServerManager = require(path.join(macDir, 'server-manager.js')); } finally { Module._load = real; }
  const seen = [];
  const fake = { getPort: () => 5054, getHealth: async (p) => { seen.push(p); return p === 5055 ? FAKE_HEALTH : null; }, isPortInUse: async () => false };
  assert.equal(await ServerManager.prototype.engineIsUp.call(fake, 5055), true);
  assert.deepEqual(seen, [5055]);
});

test('start() records the adopted engine (pid, start, port, version) so the unpaired stop has a record to match', async () => {
  const { child } = await listen(5050);
  const os = await import('node:os');
  const real = Module._load;
  Module._load = function load(request, ...rest) { return request === 'electron' ? { app: { isPackaged: false, getPath: () => os.tmpdir(), getVersion: () => '0' } } : real.call(this, request, ...rest); };
  let ServerManager;
  try { ServerManager = require(path.join(macDir, 'server-manager.js')); } finally { Module._load = real; }
  try {
    const sm = new ServerManager();
    Object.assign(sm, {
      ensureServerFiles: async () => {}, ensureVenv: async () => {}, ensureCloudflared: async () => {},
      validateEnvFile: () => ({ isValid: true, errors: [] }), getPort: () => 5050, getBundleVersion: () => '1.2.3',
      engineIsUp: async () => true, getHealth: async () => FAKE_HEALTH,
    });
    await sm.startOnce();
    const ident = await portTrust.processIdentity(child.pid, { execFile });
    assert.deepEqual(sm.engineRecord, { pid: child.pid, start: ident.start, exe: ident.exe, port: 5050, version: '1.2.3' });
  } finally { await reap(child); }
});

test('tooltip on an unfinished setup with an unread session list says cannot determine', () => {
  const s = describeSignals({ serverState: 'running', setupStatus: 'incomplete', sessionsReachable: false, sessions: null });
  assert.equal(s.sessions, 'cannot determine');
});

const NETSTAT_HEAD = 'Proto Recv-Q Send-Q  Local Address          Foreign Address        (state)          rxbytes      txbytes  rhiwat  shiwat          process:pid    state  options           gencnt    flags   flags1 usecnt rtncnt fltrs\n';
const netstatRow = (local, proc, pid) => `tcp4       0      0  ${local}  *.*  LISTEN  0  0  131072  131072  ${proc}:${pid}  00100 00000106 00000000000069a7 00000000 00000800  1  0 000000\n`;
const sleepNow = async () => {};
function rigExec({ netstat, ps = '501\n', lsof = '' }) {
  const calls = { netstat: 0, ps: 0, lsof: 0 };
  const answer = (v) => (typeof v === 'function' ? v() : v);
  const execFileFake = (file, args, opts, cb) => {
    const kind = file.split('/').pop();
    calls[kind] += 1;
    const v = answer({ netstat, ps, lsof }[kind]);
    if (v instanceof Error) cb(v, ''); else cb(null, v);
  };
  return { execFileFake, calls };
}

test('netstat listeners: pid, command and uid of every LISTEN row on the port, any user, one entry per pid', async () => {
  const table = NETSTAT_HEAD + netstatRow('127.0.0.1.8000', 'Python', 77) + netstatRow('*.8000', 'Python', 77) + netstatRow('*.8001', 'Other', 9)
    + netstatRow('127.0.0.1.18000', 'Other', 10);
  const { execFileFake, calls } = rigExec({ netstat: table, ps: '0\n' });
  assert.deepEqual(await portTrust.listeners(8000, { execFile: execFileFake }), [{ pid: 77, command: 'Python', uid: 0 }]);
  assert.equal(calls.lsof, 0, 'a netstat read never touches lsof');
  assert.deepEqual(portTrust.parseNetstat(NETSTAT_HEAD + netstatRow('::1.587', 'Brave Browser', 12), 587), [{ pid: 12, command: 'Brave Browser' }]);
});

test('a netstat read that could not run falls back to lsof; a read that RAN and saw nothing is [] and does not', async () => {
  const fall = rigExec({ netstat: new Error('boom'), lsof: 'p5\ncpython3\nu501\n' });
  assert.deepEqual(await portTrust.listeners(8000, { execFile: fall.execFileFake }), [{ pid: 5, command: 'python3', uid: 501 }]);
  const none = rigExec({ netstat: NETSTAT_HEAD });
  assert.deepEqual(await portTrust.listeners(8000, { execFile: none.execFileFake }), []);
  assert.equal(none.calls.lsof, 0);
  const psFails = rigExec({ netstat: NETSTAT_HEAD + netstatRow('*.8000', 'Python', 77), ps: new Error('timed out'), lsof: new Error('timed out') });
  assert.equal(await portTrust.listeners(8000, { execFile: psFails.execFileFake }), null, 'an unreadable uid is could-not-tell, never a listener list or none');
});

test('strict read: one failed read then a good one proceeds; every read failing refuses after exactly N tries and logs it', async () => {
  const logs = [];
  let n = 0;
  const flaky = rigExec({ netstat: () => (++n === 1 ? new Error('timed out') : NETSTAT_HEAD + netstatRow('*.8000', 'Python', 77)), lsof: new Error('timed out') });
  const got = await portTrust.listenersStrict(8000, { execFile: flaky.execFileFake, sleep: sleepNow, log: (m) => logs.push(m) });
  assert.deepEqual(got, [{ pid: 77, command: 'Python', uid: 501 }]);
  assert.equal(portTrust.holderRefusal(got, 501), null);
  const dead = rigExec({ netstat: new Error('timed out'), lsof: new Error('timed out') });
  assert.equal(await portTrust.listenersStrict(8000, { execFile: dead.execFileFake, sleep: sleepNow, log: (m) => logs.push(m) }), null);
  assert.equal(dead.calls.netstat, portTrust.STRICT_ATTEMPTS);
  assert.equal(dead.calls.lsof, portTrust.STRICT_ATTEMPTS);
  assert.match(logs.at(-1), /could not run after 3 tries/);
});

test('strict read: a read that RAN and saw a stranger or nothing is final, never retried into a pass', async () => {
  const stranger = rigExec({ netstat: NETSTAT_HEAD + netstatRow('*.8000', 'Python', 77), ps: '0\n' });
  const seen = await portTrust.listenersStrict(8000, { execFile: stranger.execFileFake, sleep: sleepNow });
  assert.equal(portTrust.holderRefusal(seen, 501).reason, 'not_yours');
  assert.equal(stranger.calls.netstat, 1);
  const none = rigExec({ netstat: NETSTAT_HEAD });
  assert.deepEqual(await portTrust.listenersStrict(8000, { execFile: none.execFileFake, sleep: sleepNow }), []);
  assert.equal(none.calls.netstat, 1);
});

test('the stop gate: one failed holder read is retried and the credential then goes; every read failing refuses and sends nothing; the poll path reads once', async () => {
  const { stopEngineViaRoute } = require(path.join(macDir, 'engine', 'engine-stop.js'));
  const { verifyEngineHolder } = require(path.join(macDir, 'engine', 'engine-lifecycle.js'));
  const good = NETSTAT_HEAD + netstatRow('*.8000', 'Python', 77);
  const gate = (rig) => () => portTrust.listenersStrict(8000, { execFile: rig.execFileFake, sleep: sleepNow, log: () => {} })
    .then((found) => portTrust.holderRefusal(found, 501));
  const run = async (rig) => {
    const sent = [];
    let up = true;
    const api = { sendAuthed: async (route) => { sent.push(route); up = false; return { reachable: true }; } };
    const r = await stopEngineViaRoute({ getApi: () => api, isUp: async () => up, verifyHolder: gate(rig), sleep: sleepNow, log: () => {} });
    return { r, sent };
  };
  let n = 0;
  const flaky = await run(rigExec({ netstat: () => (++n === 1 ? new Error('timed out') : good), lsof: new Error('timed out') }));
  assert.equal(flaky.r.outcome, 'stopped');
  assert.deepEqual(flaky.sent, ['/api/v1/shutdown']);
  const dead = await run(rigExec({ netstat: new Error('timed out'), lsof: new Error('timed out') }));
  assert.equal(dead.r.outcome, 'holder-refused');
  assert.match(dead.r.error, /unreadable/);
  assert.deepEqual(dead.sent, [], 'no credential on a check that never ran');
  const stranger = await run(rigExec({ netstat: good, ps: '0\n' }));
  assert.equal(stranger.r.outcome, 'holder-refused');
  assert.deepEqual(stranger.sent, []);
  const realListeners = portTrust.listeners;
  let reads = 0;
  portTrust.listeners = async () => { reads += 1; return null; };
  try {
    assert.equal((await verifyEngineHolder({ getPort: () => 5099 })).reason, 'unreadable');
    assert.equal(reads, 1);
  } finally { portTrust.listeners = realListeners; }
});
