import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import Module, { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const macDir = path.join(import.meta.dirname, '..', '..', 'macOS');

function setup() {
  const log = { loaded: [], sent: [], notes: [], wc: null, wins: [] };
  const ipc = {};
  const server = { url: 'http://127.0.0.1:8000' };
  class FakeWindow {
    constructor() {
      this.webContents = {
        send: (...a) => log.sent.push(a), on() {}, reload() {}, setWindowOpenHandler() {},
        session: { setPermissionRequestHandler() {}, setPermissionCheckHandler() {} },
      };
      this.webContents.mainFrame = { url: 'http://127.0.0.1:8000/' };
      log.wc = this.webContents;
      this.gone = false;
      this.handlers = {};
      log.wins.push(this);
    }
    closeIt() { this.gone = true; this.handlers.closed?.(); }
    once() {} on(ev, fn) { this.handlers[ev] = fn; } isDestroyed() { return this.gone; } isMinimized() { return false; }
    show() {} focus() {} restore() {} destroy() {}
    loadURL(u) { log.loaded.push(u); }
  }
  class FakeNotification {
    static isSupported() { return true; }
    constructor() { this.handlers = {}; log.notes.push(this); }
    on(ev, fn) { this.handlers[ev] = fn; }
    show() {}
  }
  const electron = { BrowserWindow: FakeWindow, Notification: FakeNotification, shell: { openExternal() {} }, ipcMain: { on: (n, fn) => { ipc[n] = fn; } } };
  const realLoad = Module._load;
  Module._load = function (request, ...rest) {
    return request === 'electron' ? electron : realLoad.call(this, request, ...rest);
  };
  try {
    const p = require.resolve(path.join(macDir, 'app-window.js'));
    delete require.cache[p];
    delete require.cache[require.resolve(path.join(macDir, 'window-host.js'))];
    const ctl = require(p).createAppWindow({ getUrl: () => server.url });
    ctl.open();
    return { log, ipc, ctl, server };
  } finally {
    Module._load = realLoad;
  }
}

function notify(rig, ask) {
  rig.ipc['carnivore:notify']({ sender: rig.log.wc, senderFrame: rig.log.wc.mainFrame }, 'needs you', 'run it?', ask);
  return rig.log.notes[rig.log.notes.length - 1];
}

test('a question notification click tells the open window by IPC and reloads nothing', () => {
  const rig = setup();
  rig.log.loaded.length = 0;
  notify(rig, 'ses_abc').handlers.click();
  assert.deepEqual(rig.log.sent, [['carnivore:open-approval', 'ses_abc']]);
  assert.deepEqual(rig.log.loaded, []);
});

test('an id outside the allowed pattern is a plain notification: no IPC', () => {
  const rig = setup();
  notify(rig, 'ses/../x').handlers.click();
  assert.deepEqual(rig.log.sent, []);
});

test('a notify from a sender that is not our window makes no notification', () => {
  const rig = setup();
  rig.ipc['carnivore:notify']({ sender: {}, senderFrame: { url: 'http://127.0.0.1:8000/' } }, 't', 'b', 'ses_abc');
  assert.equal(rig.log.notes.length, 0);
});

test('a notify from a sub-frame of our own window, or with no frame, makes no notification (main-frame check)', () => {
  const rig = setup();
  const sub = { url: 'http://127.0.0.1:8000/embedded' };
  rig.ipc['carnivore:notify']({ sender: rig.log.wc, senderFrame: sub }, 't', 'b', 'ses_abc');
  rig.ipc['carnivore:notify']({ sender: rig.log.wc, senderFrame: null }, 't', 'b', 'ses_abc');
  assert.equal(rig.log.notes.length, 0);
  notify(rig, 'ses_abc');
  assert.equal(rig.log.notes.length, 1, 'population check: the top frame still gets through');
});

test('a question notification click with the window gone recreates it on ?approvals=<id> and sends no IPC', () => {
  const rig = setup();
  const note = notify(rig, 'ses_abc');
  rig.log.wins[0].closeIt();
  rig.log.loaded.length = 0;
  rig.log.sent.length = 0;
  note.handlers.click();
  assert.equal(rig.log.wins.length, 2);
  assert.deepEqual(rig.log.loaded, ['http://127.0.0.1:8000/?approvals=ses_abc']);
  assert.deepEqual(rig.log.sent, []);
});

test('a click after the server origin moved recreates the window on ?approvals=<id> (G1)', () => {
  const rig = setup();
  const note = notify(rig, 'ses_abc');
  rig.server.url = 'http://127.0.0.1:8001';
  rig.log.loaded.length = 0;
  rig.log.sent.length = 0;
  note.handlers.click();
  assert.equal(rig.log.wins.length, 2);
  assert.deepEqual(rig.log.loaded, ['http://127.0.0.1:8001/?approvals=ses_abc']);
  assert.deepEqual(rig.log.sent, []);
});

function loadPreload() {
  const rec = { exposed: null, sends: [], on: {}, posts: [] };
  const electron = {
    contextBridge: { exposeInMainWorld: (name, api) => { rec.exposed = { name, api }; } },
    ipcRenderer: { send: (...a) => rec.sends.push(a), invoke() {}, on: (ch, fn) => { rec.on[ch] = fn; } },
  };
  const realLoad = Module._load;
  Module._load = function (request, ...rest) {
    return request === 'electron' ? electron : realLoad.call(this, request, ...rest);
  };
  globalThis.window = { location: { origin: 'http://127.0.0.1:8000' }, postMessage: (...a) => rec.posts.push(a) };
  try {
    const p = require.resolve(path.join(macDir, 'app-window-preload.js'));
    delete require.cache[p];
    require(p);
  } finally {
    Module._load = realLoad;
    delete globalThis.window;
  }
  return rec;
}

test('the preload hands carnivore:open-approval to the page as a same-window message', () => {
  const rec = loadPreload();
  globalThis.window = { location: { origin: 'http://127.0.0.1:8000' }, postMessage: (...a) => rec.posts.push(a) };
  try {
    rec.on['carnivore:open-approval']({}, 'ses_abc');
    rec.on['carnivore:open-approval']({}, '');
    rec.on['carnivore:open-approval']({}, { not: 'a string' });
  } finally {
    delete globalThis.window;
  }
  assert.deepEqual(rec.posts, [[{ type: 'carnivore.open-approval', session_id: 'ses_abc' }, 'http://127.0.0.1:8000']]);
});

test('the preload bridge sends the ask id with the notification over IPC', () => {
  const rec = loadPreload();
  rec.exposed.api.notify('needs you', 'run it?', 'ses_abc');
  assert.equal(rec.exposed.name, 'carnivoreDesktop');
  assert.deepEqual(rec.sends, [['carnivore:notify', 'needs you', 'run it?', 'ses_abc']]);
});
