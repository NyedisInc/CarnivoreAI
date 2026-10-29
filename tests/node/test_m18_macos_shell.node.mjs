import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import Module, { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const macDir = path.join(import.meta.dirname, '..', '..', 'macOS');

function scratch() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'm18-'));
}

test('u019-13: the generated .env is never wider than 0600, even under umask 022', () => {
  const { generateEnvFile } = require(path.join(macDir, 'bootstrap.js'));
  const dir = scratch();
  const example = path.join(dir, '.env.example');
  fs.writeFileSync(example, 'TOTP_SECRET=\nJWT_SECRET=\nDEFAULT_WORKING_DIR=\nLOG_DIRECTORY=\n');
  const out = path.join(dir, '.env');
  const old = process.umask(0o022);
  try {
    generateEnvFile({ envExamplePath: example, envOutPath: out, defaultWorkingDir: '/x', logDirectory: '/y' });
  } finally {
    process.umask(old);
  }
  assert.equal(fs.statSync(out).mode & 0o777, 0o600);
  assert.equal(fs.existsSync(out + '.tmp'), false);
});

test('u019-10: a failing log write or rotation is contained, not thrown into the caller', () => {
  const { RotatingLogWriter, appendWithRotation } = require(path.join(macDir, 'log-rotation.js'));
  const dir = scratch();
  const file = path.join(dir, 'server.log');
  const w = new RotatingLogWriter(file, { maxBytes: 10, backupCount: 2 });
  w.write('0123456789');
  fs.mkdirSync(path.join(dir, 'server.log.1', 'keep'), { recursive: true });
  assert.doesNotThrow(() => w.write('more bytes'));
  w._fd = 987654;
  assert.doesNotThrow(() => w.write('x'));
  assert.doesNotThrow(() => appendWithRotation(path.join(dir, 'missing-dir', 'a.log'), 'text'));
});

test('u019-11: runGuardedPoll reschedules even when the poll body throws', async () => {
  const { runGuardedPoll } = require(path.join(macDir, 'poll-guard.js'));
  let rescheduled = 0;
  const logged = [];
  await runGuardedPoll(async () => { throw new Error('boom'); }, () => { rescheduled += 1; }, (m) => logged.push(m));
  assert.equal(rescheduled, 1);
  assert.equal(logged.length, 1);
  await runGuardedPoll(async () => {}, () => { rescheduled += 1; }, () => {});
  assert.equal(rescheduled, 2);
});

/** Load ServerManager with electron stubbed. */
function loadSM() {
  const realLoad = Module._load;
  Module._load = function (request, ...rest) {
    return request === 'electron' ? { app: { getPath: () => '/tmp', getVersion: () => '0.0.0', isPackaged: false } } : realLoad.call(this, request, ...rest);
  };
  try { return require(path.join(macDir, 'server-manager.js')); } finally { Module._load = realLoad; }
}

test('u019-02: a superseded child exit does not clobber the newer child state', async () => {
  const { EventEmitter } = require('node:events');
  const SM = loadSM();
  const m = new SM();
  m.logFile = path.join(scratch(), 'server.log');
  const oldChild = new EventEmitter(); oldChild.pid = 1;
  const newChild = new EventEmitter(); newChild.pid = 2;
  m.attachChildHandlers(oldChild);
  m.process = newChild; m.processPid = 2; m.ownedProcess = true; m.state = 'starting';
  oldChild.emit('exit', 1, null);
  assert.equal(m.process, newChild);
  assert.equal(m.processPid, 2);
  assert.equal(m.state, 'starting');
  oldChild.emit('error', new Error('late'));
  assert.equal(m.process, newChild);
});

test('u019-09: restart() stops and reports when stop() could not confirm the exit', async () => {
  const SM = loadSM();
  const m = new SM();
  m.ownedProcess = true;
  let started = 0;
  m.stop = async () => ({ stopped: false, outcome: 'timeout', pid: 5 });
  m.start = async () => { started += 1; };
  const r = await m.restart();
  assert.equal(started, 0);
  assert.equal(r.restarted, false);
});

test('u019-03: setBindHost writes through the server settings route when an api client is given', async () => {
  const SM = loadSM();
  const m = new SM();
  m.getBindHost = () => '127.0.0.1';
  m._saveSettings = () => {};
  m.restart = async () => ({ restarted: true });
  const cfg = path.join(scratch(), 'config.json');
  fs.writeFileSync(cfg, '{}');
  m.getConfigPath = () => cfg;
  const calls = [];
  const api = { sendAuthed: async (route, body, method) => { calls.push({ route, body, method }); return { reachable: true, status: 200, data: {}, error: null }; } };
  await m.setBindHost('0.0.0.0', { api });
  assert.deepEqual(calls, [{ route: '/api/v1/config/settings', body: { server_prefs: { bind_host: '0.0.0.0' } }, method: 'PATCH' }]);
  assert.equal(fs.readFileSync(cfg, 'utf8'), '{}');
  const down = { sendAuthed: async () => ({ reachable: false, data: null, error: 'down' }) };
  await m.setBindHost('0.0.0.0', { api: down });
  assert.equal(JSON.parse(fs.readFileSync(cfg, 'utf8')).server_prefs.bind_host, '0.0.0.0');
});

test('u021-06: a resync superseded by close-and-reopen cannot load its stale snapshot', async () => {
  const { ListingStore } = require(path.join(macDir, 'tray-menu', 'listing-store.js'));
  const pending = [];
  const store = new ListingStore(() => new Promise((res) => pending.push(res)), { setTimeout: () => 0, clearTimeout: () => {} });
  const snap = (marker) => ({ stream: 's', seq: 1, collections: { list: { rows: [{ session: { id: marker } }] } } });
  store.hello();
  store.closed();
  store.hello();
  assert.equal(pending.length, 2);
  pending[0](snap('stale'));
  await new Promise((r) => setImmediate(r));
  assert.equal(store.isLive(), false, 'the superseded read must not take the store live');
  assert.equal(store.rows('list'), null);
  pending[1](snap('new'));
  await new Promise((r) => setImmediate(r));
  const rows = store.rows('list') || [];
  assert.deepEqual(rows.map((r) => r.session.id), ['new']);
});
