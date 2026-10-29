import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const macDir = path.join(import.meta.dirname, '..', '..', 'macOS');
const load = (name) => require(path.join(macDir, name));
function fresh(name) {
  const p = require.resolve(path.join(macDir, name));
  delete require.cache[p];
  return require(p);
}
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'f3-'));

async function fakeDoor(reply) {
  const dir = tmp();
  const sock = path.join(dir, 'd.sock');
  const seen = [];
  const server = net.createServer((c) => {
    c.once('data', (d) => {
      const req = JSON.parse(d.toString());
      seen.push(req);
      c.end(`${JSON.stringify(reply(req))}\n`);
    });
  });
  await new Promise((r) => server.listen(sock, r));
  return { sock, seen, close: () => server.close() };
}

test('door login: real socket round trip returns tokens; refusal and a missing socket return null', async () => {
  const { doorLogin } = load('local-login.js');
  const ok = await fakeDoor(() => ({ access_token: 'a', refresh_token: 'r', expires_in: 900 }));
  assert.deepEqual(await doorLogin(ok.sock), { access_token: 'a', refresh_token: 'r', expires_in: 900 });
  assert.deepEqual(ok.seen, [{ op: 'login' }]);
  ok.close();
  const no = await fakeDoor(() => ({ error: 'not_joined' }));
  assert.equal(await doorLogin(no.sock), null);
  no.close();
  assert.equal(await doorLogin(path.join(tmp(), 'absent.sock')), null);
});

test('door path: sha256 of the state dir, first 8 hex, under ~/.carnivore/fed', () => {
  const { doorPath } = load('local-login.js');
  const tag = require('crypto').createHash('sha256').update('/x').digest('hex').slice(0, 8);
  assert.equal(doorPath('/x', '/h'), `/h/.carnivore/fed/door-${tag}.sock`);
});

test('local login gate: needs joined, the app window, and the loopback origin the window is on', async () => {
  const { registerLocalLogin, mayLoginLocally } = load('local-login.js');
  const base = { joined: true, fromAppWindow: true, senderOrigin: 'http://127.0.0.1:8000', windowOrigin: 'http://127.0.0.1:8000' };
  assert.equal(mayLoginLocally(base), true);
  assert.equal(mayLoginLocally({ ...base, joined: false }), false);
  assert.equal(mayLoginLocally({ ...base, joined: null }), false);
  assert.equal(mayLoginLocally({ ...base, fromAppWindow: false }), false);
  const lan = 'http://192.168.1.5:8000';
  assert.equal(mayLoginLocally({ ...base, senderOrigin: lan, windowOrigin: lan }), false);
  assert.equal(mayLoginLocally({ ...base, senderOrigin: 'http://localhost:8000' }), false);

  let handler;
  let asked = 0;
  registerLocalLogin({
    ipcMain: { handle: (_c, h) => { handler = h; } },
    isJoined: () => true, isAppSender: () => true, windowOrigin: () => base.windowOrigin,
    originOf: (u) => new URL(u).origin, getDoorPath: () => '/s', login: async () => { asked += 1; return { access_token: 'a' }; },
  });
  const eventFrom = (url, top = true) => {
    const frame = { url };
    return { sender: { mainFrame: top ? frame : { url: 'http://127.0.0.1:8000/' } }, senderFrame: frame };
  };
  assert.deepEqual(await handler(eventFrom('http://127.0.0.1:8000/#x')), { access_token: 'a' });
  assert.equal(await handler(eventFrom('http://evil.example/')), null);
  assert.equal(await handler(eventFrom('http://127.0.0.1:8000/embedded', false)), null, 'a same-origin sub-frame is refused');
  assert.equal(await handler({ sender: { mainFrame: {} }, senderFrame: null }), null, 'a null frame is refused');
  assert.equal(asked, 1, 'a refused ask never reaches the door');
});

test('tray ensureToken on a member uses the door login and never spends a TOTP code', async () => {
  const { TrayApiClient } = load('tray-api.js');
  let otpAsked = 0;
  let loginAsked = 0;
  const calls = [];
  const api = new TrayApiClient({
    baseUrl: 'http://127.0.0.1:8000', getOtp: () => { otpAsked += 1; return '123456'; },
    isJoined: () => true,
    localLogin: async () => { loginAsked += 1; return { access_token: 'tok', refresh_token: 'ref', expires_in: 900 }; },
    fetchImpl: async (u) => { calls.push(u); return { ok: false, status: 500, json: async () => ({}) }; },
  });
  assert.deepEqual(await api.ensureToken(), { token: 'tok', error: null });
  assert.equal(otpAsked, 0);
  assert.equal(loginAsked, 1);
  assert.deepEqual(calls, []);
  const refused = new TrayApiClient({ baseUrl: 'http://x', getOtp: () => '1', isJoined: () => true, localLogin: async () => null });
  assert.equal((await refused.ensureToken()).token, null);
  const plain = new TrayApiClient({ baseUrl: 'http://x', getOtp: () => null });
  assert.equal((await plain.ensureToken()).error, 'no TOTP secret available');
});

test('rebind decide: a member still listening beyond loopback restarts once; loopback stops; paired path unchanged', () => {
  const { decide } = fresh('rebind-after-pair.js');
  const now = 1e6;
  const wide = { setup_status: 'complete', joined: true, bind: { effective_host: '0.0.0.0', restart_required: false } };
  assert.equal(decide(wide, { attempted: false, now }), 'restart');
  assert.equal(decide(wide, { attempted: true, attemptAt: now - 70000, now }), 'stop');
  assert.equal(decide(wide, { attempted: true, attemptAt: now - 1000, now }), 'wait');
  const tight = { setup_status: 'complete', joined: true, bind: { effective_host: '127.0.0.1', restart_required: false } };
  assert.equal(decide(tight, { attempted: false, now }), 'stop');
  assert.equal(decide({ ...wide, joined: false }, { attempted: false, now }), 'stop');
  assert.equal(decide({ setup_status: 'complete', bind: { restart_required: true } }, { attempted: false, now }), 'restart');
});

test('shouldAutoOpen: a member never auto-opens', () => {
  const { shouldAutoOpen } = fresh('rebind-after-pair.js');
  const verdict = { status: 'incomplete', checks: [{ key: 'totp_paired', passed: false }] };
  assert.equal(shouldAutoOpen(verdict, true, 5, 5, false), true);
  assert.equal(shouldAutoOpen(verdict, true, 5, 5, true), false);
});

function rig(initial) {
  let report = initial;
  const log = [];
  return {
    set: (r) => { report = r; },
    log,
    deps: {
      serverManager: { getBindReport: () => report, getHealth: async () => null, restart: async () => ({}) },
      appWindow: { isOpen: () => true, open: () => log.push('open'), reload: () => log.push('reload') },
      offerTakeOwnership: async () => {}, reportStartFailure: async () => {}, dialog: {},
      onJoinedChange: (j) => log.push(`joined:${j}`),
    },
  };
}

test('observeHealth: baseline is silent; joined false->true reloads; true->false reopens; rebind_requested arms', () => {
  const mod = fresh('rebind-after-pair.js');
  const r = rig({ setup_status: 'complete', joined: false, bind: { restart_required: false }, rebind_requested: false });
  assert.deepEqual(mod.observeHealth(r.deps), { joinedNow: false, becameJoined: false, left: false });
  assert.deepEqual(r.log.filter((x) => x !== 'joined:false'), []);
  r.set({ setup_status: 'complete', joined: true, bind: { restart_required: false }, rebind_requested: false });
  assert.equal(mod.observeHealth(r.deps).becameJoined, true);
  assert.ok(r.log.includes('reload'));
  r.set({ setup_status: 'complete', joined: false, bind: { restart_required: false }, rebind_requested: false });
  assert.equal(mod.observeHealth(r.deps).left, true);
  assert.ok(r.log.includes('open'));
});

test('observeHealth: setup -> complete while the window is open reloads it', () => {
  const mod = fresh('rebind-after-pair.js');
  const r = rig({ setup_status: 'incomplete', joined: false, bind: null, rebind_requested: false });
  mod.observeHealth(r.deps);
  r.set({ setup_status: 'complete', joined: false, bind: null, rebind_requested: false });
  mod.observeHealth(r.deps);
  assert.ok(r.log.includes('reload'));
});

test('launch at login: a join turns it on once; a later off sticks; leaving clears so a re-join turns it on again', () => {
  const { applyMemberLaunch } = load('member-launch.js');
  const dir = tmp();
  let enabled = false;
  const installer = { isEnabled: () => enabled, enable: () => { enabled = true; } };
  const run = (joined) => applyMemberLaunch({ joined, dir, installer, launchArgs: () => ['/x'] });
  assert.equal(run(null), 'none');
  assert.equal(run(true), 'enabled');
  assert.equal(enabled, true);
  enabled = false;
  assert.equal(run(true), 'kept');
  assert.equal(enabled, false, 'the user choice is not undone');
  assert.equal(run(false), 'cleared');
  assert.equal(enabled, false, 'leaving leaves the setting as the user set it');
  assert.equal(run(true), 'enabled');
  assert.equal(enabled, true);
});

test('.env is set to 0600 on every launch and a missing file is left alone', () => {
  const { secureEnvFile } = load('bootstrap.js');
  const f = path.join(tmp(), '.env');
  assert.equal(secureEnvFile(f), false);
  fs.writeFileSync(f, 'A=1\n', { mode: 0o644 });
  fs.chmodSync(f, 0o644);
  assert.equal(secureEnvFile(f), true);
  assert.equal(fs.statSync(f).mode & 0o777, 0o600);
  assert.equal(secureEnvFile(f), true);
});

test('setup row reads joined on a member; tray TOTP rows are hidden on one', async () => {
  const { load: loadMenu, t, snap } = await import('./tray_menu_fixtures.mjs');
  const { setupLabel } = loadMenu('model/server.js');
  assert.equal(setupLabel({ joined: true, mainLabel: 'Studio' }, t), "Joined Studio's Pack");
  assert.equal(setupLabel({ joined: true, mainLabel: null }, t), 'Joined a Pack');
  assert.equal(setupLabel({ joined: false, setup: 'complete' }, t), 'Setup and Config...');
  const { phoneMenu } = loadMenu('model/phone.js');
  const ids = (joined) => phoneMenu(snap({ joined }), { t }).submenu.map((i) => i.id);
  assert.ok(!ids(true).includes('phone.copy_otp') && !ids(true).includes('phone.totp_qr'));
  assert.ok(ids(false).includes('phone.copy_otp') && ids(false).includes('phone.totp_qr'));
});

test('Info.plist carries the Local Network keys and the pack Bonjour service', () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(macDir, 'package.json'), 'utf8'));
  const info = pkg.build.mac.extendInfo;
  assert.ok(info.NSLocalNetworkUsageDescription.length > 10);
  assert.deepEqual(info.NSBonjourServices, ['_carnivore._tcp']);
});

test('P1: a member whose configured host stays wide (restart_required true) on loopback never restarts or gets the modal', () => {
  const { decide } = fresh('rebind-after-pair.js');
  const now = 1e6;
  const tight = { setup_status: 'complete', joined: true, bind: { effective_host: '127.0.0.1', restart_required: true } };
  assert.equal(decide(tight, { attempted: false, now }), 'stop');
  assert.equal(decide(tight, { attempted: true, attemptAt: now - 70000, now }), 'stop');
  const paired = { setup_status: 'complete', joined: false, bind: { effective_host: '127.0.0.1', restart_required: true } };
  assert.equal(decide(paired, { attempted: true, attemptAt: now - 70000, now }), 'stuck');
});

test('P10: the door path follows the file name the server reported, and only a well formed one', () => {
  const { doorPath } = load('local-login.js');
  assert.equal(doorPath('/x', '/h', 'door-0123abcd.sock'), '/h/.carnivore/fed/door-0123abcd.sock');
  for (const bad of ['../../etc/door-0123abcd.sock', 'door-xyz.sock', '', null, undefined]) {
    assert.equal(doorPath('/x', '/h', bad), doorPath('/x', '/h'));
  }
});

test('P7: rehome reopens a window whose origin is no longer the published one, and reload uses it', () => {
  const Module = require('module');
  const orig = Module._load;
  const opened = [];
  class FakeWin {
    constructor() { this.webContents = { on() {}, reload: () => opened.push('reload'), session: { setPermissionRequestHandler() {}, setPermissionCheckHandler() {} }, setWindowOpenHandler() {} }; }
    once() {} on() {} loadURL(u) { opened.push(u); } destroy() { opened.push('destroy'); } isDestroyed() { return false; }
    show() {} focus() {} isMinimized() { return false; }
  }
  Module._load = function (req, ...rest) {
    if (req === 'electron') return { BrowserWindow: FakeWin, ipcMain: { on() {} }, shell: {}, Notification: { isSupported: () => false } };
    return orig.call(this, req, ...rest);
  };
  try {
    const { createAppWindow } = fresh('app-window.js');
    let url = 'http://192.168.1.5:8000';
    const w = createAppWindow({ getUrl: () => url });
    w.open();
    opened.length = 0;
    assert.equal(w.rehome(), false);
    url = 'http://127.0.0.1:8000';
    w.reload();
    assert.deepEqual(opened, ['destroy', 'http://127.0.0.1:8000']);
  } finally {
    Module._load = orig;
  }
});
