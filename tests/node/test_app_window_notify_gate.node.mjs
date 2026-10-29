import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import Module, { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const macDir = path.join(import.meta.dirname, '..', '..', 'macOS');

function setup(shouldMirror) {
  const calls = { supported: 0, shown: 0 };
  const ipc = {};
  const wcs = { send() {}, on() {}, reload() {}, setWindowOpenHandler() {}, session: { setPermissionRequestHandler() {}, setPermissionCheckHandler() {} }, mainFrame: { url: 'http://127.0.0.1:8000/' } };
  class FakeWindow {
    constructor() { this.webContents = wcs; }
    once() {} on() {} isDestroyed() { return false; } isMinimized() { return false; } show() {} focus() {} restore() {} destroy() {} loadURL() {}
  }
  class FakeNotification {
    static isSupported() { calls.supported += 1; return true; }
    on() {}
    show() { calls.shown += 1; }
  }
  const electron = { BrowserWindow: FakeWindow, Notification: FakeNotification, shell: { openExternal() {} }, ipcMain: { on: (n, fn) => { ipc[n] = fn; } } };
  const realLoad = Module._load;
  Module._load = function (request, ...rest) { return request === 'electron' ? electron : realLoad.call(this, request, ...rest); };
  try {
    const p = require.resolve(path.join(macDir, 'app-window.js'));
    delete require.cache[p];
    delete require.cache[require.resolve(path.join(macDir, 'window-host.js'))];
    const ctl = require(p).createAppWindow({ getUrl: () => 'http://127.0.0.1:8000', shouldMirror });
    ctl.open();
    return { calls, ipc, wcs };
  } finally {
    Module._load = realLoad;
  }
}

async function ask(rig) {
  await rig.ipc['carnivore:notify']({ sender: rig.wcs, senderFrame: rig.wcs.mainFrame }, 't', 'b', '');
}

test('banners off: a page toast never calls Notification.isSupported and shows nothing', async () => {
  const rig = setup(async () => false);
  await ask(rig);
  assert.equal(rig.calls.supported, 0);
  assert.equal(rig.calls.shown, 0);
});

test('banners on: a page toast is checked for support, then shown', async () => {
  const rig = setup(async () => true);
  await ask(rig);
  assert.equal(rig.calls.supported, 1);
  assert.equal(rig.calls.shown, 1);
});
