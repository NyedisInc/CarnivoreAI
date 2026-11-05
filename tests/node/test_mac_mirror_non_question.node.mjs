import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import Module, { createRequire } from 'node:module';

import { makeEnv, toast, settle } from '../lib_toast_dom_stub.mjs';

const require = createRequire(import.meta.url);
const macDir = path.join(import.meta.dirname, '..', '..', 'macOS');
const { shouldMirror } = require(path.join(macDir, 'banners', 'mirror.js'));

function shell() {
  const posted = [];
  const ipc = {};
  const wcs = { send() {}, on() {}, reload() {}, setWindowOpenHandler() {}, session: { setPermissionRequestHandler() {}, setPermissionCheckHandler() {} }, mainFrame: { url: 'http://127.0.0.1:8000/' } };
  class FakeWindow {
    constructor() { this.webContents = wcs; }
    once() {} on() {} isDestroyed() { return false; } isMinimized() { return false; } show() {} focus() {} restore() {} destroy() {} loadURL() {}
  }
  class FakeNotification {
    constructor(opts) { posted.push(opts); }
    static isSupported() { return true; }
    static remove() {}
    on() {}
    show() {}
  }
  const electron = { BrowserWindow: FakeWindow, Notification: FakeNotification, shell: { openExternal() {} },
    app: { dock: { bounce() {} } }, ipcMain: { on: (n, fn) => { ipc[n] = fn; } } };
  const realLoad = Module._load;
  Module._load = function (request, ...rest) { return request === 'electron' ? electron : realLoad.call(this, request, ...rest); };
  try {
    const p = require.resolve(path.join(macDir, 'app-window.js'));
    delete require.cache[p];
    delete require.cache[require.resolve(path.join(macDir, 'window-host.js'))];
    const asksOnly = false;
    require(p).createAppWindow({ getUrl: () => 'http://127.0.0.1:8000', shouldMirror: async (ask) => shouldMirror({ asksOnly, askSessionId: ask }) }).open();
    return { posted, notify: (...args) => ipc['carnivore:notify']({ sender: wcs, senderFrame: wcs.mainFrame }, ...args) };
  } finally {
    Module._load = realLoad;
  }
}

const CARDS = [
  ['Stop', 'session.finished', 'sessions'],
  ['Notification', 'agent.message', 'messages'],
  ['Notification', 'plugin.notice', 'messages'],
  ['Notification', 'session.terminal_notice', 'sessions'],
  ['AppAlert', 'alert.self_check', 'health'],
  ['AutoSlept', 'session.auto_slept', 'sessions'],
];

test('a non-question card shown while the window is behind becomes one Mac banner with its id and groups', async () => {
  const { mgr, sandbox } = makeEnv();
  const calls = [];
  sandbox.document.hasFocus = () => false;
  sandbox.window.carnivoreDesktop = { notify: (...args) => calls.push(args) };
  const groups = Object.fromEntries(CARDS.map(([, type, group]) => [type, group]));
  sandbox.window.NotifyScreen = { shows: () => true, groupOf: (type) => groups[type] || '' };
  const sent = CARDS.map(([kind, type]) => Object.assign(toast(kind, `${type} title`, 'b', 'ses_1', 'carnivore_api'), { notify_type: type }));
  for (const card of sent) mgr.add(card);
  await settle();

  assert.equal(calls.length, CARDS.length, 'the page hands every non-question card to the bridge');
  for (const [i, [, type, group]] of CARDS.entries()) {
    const [title, , ask, meta] = calls[i];
    assert.equal(title, `${type} title`);
    assert.equal(ask, '', `${type} is not a question, so it names no ask`);
    assert.equal(meta.group, group);
    assert.equal(meta.id, sent[i].id);
  }

  const mac = shell();
  for (const args of calls) await mac.notify(...args);
  assert.equal(mac.posted.length, CARDS.length, 'the shell posts one banner per card');
  for (const [i, opts] of mac.posted.entries()) {
    assert.equal(opts.id, sent[i].id);
    assert.equal(opts.groupId, 'ses_1', 'grouped by session');
    assert.equal(opts.sound, undefined, 'a non-question card plays the default sound');
  }
});

test('a card shown while the window is in front is not mirrored', async () => {
  const { mgr, sandbox } = makeEnv();
  const calls = [];
  sandbox.document.hasFocus = () => true;
  sandbox.window.carnivoreDesktop = { notify: (...args) => calls.push(args) };
  mgr.add(Object.assign(toast('Stop', 'done', 'b', 'ses_1'), { notify_type: 'session.finished' }));
  await settle();
  assert.equal(calls.length, 0);
});
