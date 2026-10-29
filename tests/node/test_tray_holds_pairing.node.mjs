import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const macDir = path.join(import.meta.dirname, '..', '..', 'macOS');
const { createTrayData } = require(path.join(macDir, 'tray-menu', 'data.js'));
const { TrayApiClient } = require(path.join(macDir, 'tray-api.js'));
const rebind = require(path.join(macDir, 'rebind-after-pair.js'));
const flush = async () => { for (let i = 0; i < 8; i += 1) await new Promise((r) => setImmediate(r)); };

function rig(setupStatus) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push(`${(init && init.method) || 'GET'} ${new URL(url).pathname}`);
    return { ok: true, status: 200, json: async () => ({ access_token: 't', expires_in: 900, rows: [] }) };
  };
  class Api extends TrayApiClient { constructor(o) { super({ ...o, fetchImpl }); } }
  const sm = { getState: () => 'running', getPort: () => 8000, getLocalApiUrl: () => 'http://127.0.0.1:8000', baseDir: '/s',
    getCurrentOtp: () => '123456', getSetupVerdict: () => ({ status: setupStatus }) };
  const timers = { setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {} };
  class WS { constructor() { calls.push('WS'); } close() {} }
  const data = createTrayData({ serverManager: sm, member: { isJoined: () => false, tokens: null }, TrayApiClient: Api, onChange: () => {},
    portDeps: () => ({ myUid: 501, myPid: 1, execFile: (f, a, o, cb) => cb(null, 'p42\ncpython3\nu501\n') }),
    offlineDeps: () => ({}), resolveTmux: async () => null, WebSocketImpl: WS, timers });
  return { data, calls };
}

test('setup not complete: several health polls send no verify, mint no token, open no socket', async () => {
  const r = rig('incomplete');
  for (let i = 0; i < 4; i += 1) { await r.data.onHealth({ status: 'running', uptime: i, version: '1.16.4' }); await flush(); }
  assert.deepEqual(r.calls, [], 'no request of any kind from the tray');
  assert.equal(r.data.api(), null, 'no client: every row that needs a token reads as unavailable');
});

test('setup complete: the tray verifies as before', async () => {
  const r = rig('complete');
  await r.data.onHealth({ status: 'running', uptime: 1, version: '1.16.4' }); await flush();
  assert.ok(r.calls.includes('POST /api/v1/auth/verify'));
});

test('setup not complete: the first window settle returns at once, no wait for a restart', async () => {
  const sm = { ownedProcess: true, serviceOwnsEngine: () => false, getHealth: async () => ({}),
    getBindReport: () => ({ setup_status: 'incomplete', bind: { restart_required: true }, joined: false }) };
  const t0 = Date.now();
  const waited = await rebind.settleBeforeFirstWindow({ serverManager: sm, appWindow: { isOpen: () => false } });
  assert.equal(waited, false);
  assert.ok(Date.now() - t0 < 500, `settle took ${Date.now() - t0} ms`);
});
