// grouped by session
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import Module, { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const macDir = path.join(import.meta.dirname, '..', '..', 'macOS');

function setup() {
  const seen = { options: [], removed: [], bounces: 0 };
  const ipc = {};
  const wcs = { send() {}, on() {}, reload() {}, setWindowOpenHandler() {}, session: { setPermissionRequestHandler() {}, setPermissionCheckHandler() {} }, mainFrame: { url: 'http://127.0.0.1:8000/' } };
  class FakeWindow {
    constructor() { this.webContents = wcs; }
    once() {} on() {} isDestroyed() { return false; } isMinimized() { return false; } show() {} focus() {} restore() {} destroy() {} loadURL() {}
  }
  class FakeNotification {
    constructor(opts) { seen.options.push(opts); }
    static isSupported() { return true; }
    static remove(id) { seen.removed.push(id); }
    on() {}
    show() {}
  }
  const electron = { BrowserWindow: FakeWindow, Notification: FakeNotification, shell: { openExternal() {} },
    app: { dock: { bounce: () => { seen.bounces += 1; } } }, ipcMain: { on: (n, fn) => { ipc[n] = fn; } } };
  const realLoad = Module._load;
  Module._load = function (request, ...rest) { return request === 'electron' ? electron : realLoad.call(this, request, ...rest); };
  try {
    const p = require.resolve(path.join(macDir, 'app-window.js'));
    delete require.cache[p];
    delete require.cache[require.resolve(path.join(macDir, 'window-host.js'))];
    require(p).createAppWindow({ getUrl: () => 'http://127.0.0.1:8000', shouldMirror: async () => true }).open();
    return { seen, ipc, ev: { sender: wcs, senderFrame: wcs.mainFrame } };
  } finally {
    Module._load = realLoad;
  }
}

test('a needs-you card is a real banner: id, session group, subtitle, the distinct sound, one Dock bounce; others play the default', async () => {
  const rig = setup();
  await rig.ipc['carnivore:notify'](rig.ev, 'needs you', 'b', 'ses_1', { id: 'toast_1', group: 'needs_you', subtitle: 'api', session_id: 'ses_1', tmux_name: 'carnivore_api' });
  await rig.ipc['carnivore:notify'](rig.ev, 'done', 'b', '', { id: 'toast_2', group: 'sessions', subtitle: 'api', session_id: 'ses_1' });
  await rig.ipc['carnivore:notify'](rig.ev, 'quiet', 'b', '', { id: 'toast_3', group: 'needs_you', session_id: 'ses_2', silent: true });
  await rig.ipc['carnivore:notify'](rig.ev, 'bad', 'b', '', { id: 'x y', session_id: '../../etc', subtitle: 7 });
  const [ask, done, quiet, bad] = rig.seen.options;
  assert.deepEqual(ask, { title: 'needs you', body: 'b', id: 'toast_1', groupId: 'ses_1', subtitle: 'api', sound: 'Glass' });
  assert.equal(done.sound, undefined, 'the rest play the default sound');
  assert.equal(done.groupId, 'ses_1');
  assert.equal(quiet.silent, true);
  assert.equal(quiet.sound, undefined, 'a suppressed banner is silent, no sound named');
  assert.deepEqual(bad, { title: 'bad', body: 'b' }, 'bad fields are dropped');
  assert.equal(rig.seen.bounces, 2, 'each needs-you card bounces the Dock once');
});

test('unnotify removes the banner by card id, and only from the main frame', () => {
  const rig = setup();
  rig.ipc['carnivore:unnotify'](rig.ev, 'toast_1');
  rig.ipc['carnivore:unnotify']({ sender: rig.ev.sender, senderFrame: { url: 'http://127.0.0.1:8000/' } }, 'toast_2');
  rig.ipc['carnivore:unnotify'](rig.ev, 'not an id');
  assert.deepEqual(rig.seen.removed, ['toast_1']);
});

test('the probe: unknown until the first banner is in the history, then allowed; missing past the waiting window is blocked', async () => {
  const perm = require(path.join(macDir, 'notification-permission.js'));
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'perm-'));
  let history = [];
  const Notification = class { constructor() {} show() {} static isSupported() { return true; } static async getHistory() { return history; } };
  assert.equal(await perm.probe({ dir, Notification }), 'not_asked', 'never reads the history before the ask');
  assert.equal(perm.request({ dir, Notification, t: (k) => k }), 'unknown');
  assert.equal(await perm.probe({ dir, Notification }), 'unknown', 'missing inside the waiting window: macOS may still be asking');
  const later = Date.now() + perm.WAITING_WINDOW_MS + 1000;
  assert.equal(await perm.probe({ dir, Notification, now: later }), 'blocked');
  history = [{ id: perm.PROBE_ID }];
  assert.equal(await perm.probe({ dir, Notification }), 'allowed');
  history = [];
  assert.equal(await perm.probe({ dir, Notification, now: later }), 'allowed', 'a cleared banner never downgrades allowed');
  fs.rmSync(dir, { recursive: true, force: true });
});
