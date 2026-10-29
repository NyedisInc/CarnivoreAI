import test, { mock } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import Module, { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const repo = path.join(import.meta.dirname, '..', '..');
const macDir = path.join(repo, 'macOS');
const ORIGIN = 'http://127.0.0.1:8000';

function rig() {
  const log = { wins: [] };
  class FakeWindow {
    constructor(options) {
      this.options = options; this.gone = false; this.handlers = {}; this.focused = false;
      this.webContents = {
        mainFrame: { url: `${ORIGIN}/` }, sent: [], handlers: {}, throttlingCalls: 0,
        setBackgroundThrottling() { this.throttlingCalls += 1; }, on(ev, fn) { this.handlers[ev] = fn; }, reload() {}, send(...a) { this.sent.push(a); },
        isLoading() { return false; }, once() {}, setWindowOpenHandler() {}, session: { setPermissionRequestHandler() {}, setPermissionCheckHandler() {} },
      };
      log.wins.push(this);
    }
    once() {} on(ev, fn) { this.handlers[ev] = fn; } isDestroyed() { return this.gone; } isMinimized() { return false; } isVisible() { return true; }
    show() {} focus() {} restore() {} destroy() { this.gone = true; } getTitle() { return 'carnivore'; } loadURL() {} isFocused() { return this.focused; }
    getNormalBounds() { return { x: 0, y: 0, width: 800, height: 600 }; } isMaximized() { return false; } isFullScreen() { return false; }
  }
  const electron = {
    BrowserWindow: FakeWindow, Notification: class { static isSupported() { return true; } on() {} show() {} }, shell: { openExternal() {} },
    ipcMain: { on() {}, handle() {} },
  };
  const realLoad = Module._load;
  Module._load = function (request, ...rest) { return request === 'electron' ? electron : realLoad.call(this, request, ...rest); };
  try {
    for (const f of ['app-window.js', 'window-host.js', 'window-ipc.js', 'desktop-settings.js', 'window-chrome.js']) {
      try { delete require.cache[require.resolve(path.join(macDir, f))]; } catch (e) { if (e.code !== 'MODULE_NOT_FOUND') throw e; }
    }
    const { createWindowState } = require(path.join(macDir, 'window-state.js'));
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'window-calm-test-'));
    const state = createWindowState({ dir: () => dir, getDisplays: () => [{ workArea: { x: 0, y: 0, width: 1920, height: 1080 } }] });
    const ctl = require(path.join(macDir, 'app-window.js')).createAppWindow({ getUrl: () => ORIGIN, windowState: state });
    const { BLUR_DELAY_MS } = require(path.join(macDir, 'window-host.js'));
    return { log, ctl, BLUR_DELAY_MS };
  } finally {
    Module._load = realLoad;
  }
}

const blurredSends = (w) => w.webContents.sent.filter((s) => s[0] === 'carnivore:window-blurred').map((s) => s[1]);

test('blur is pushed once, only after BLUR_DELAY_MS', () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    const r = rig(); r.ctl.open();
    const [w] = r.log.wins;
    assert.equal(r.BLUR_DELAY_MS, 1000);
    w.handlers.blur();
    mock.timers.tick(999);
    assert.deepEqual(blurredSends(w), []);
    mock.timers.tick(1);
    assert.deepEqual(blurredSends(w), [true]);
    w.handlers.blur(); mock.timers.tick(2000);
    assert.deepEqual(blurredSends(w), [true], 'deduped against the last value sent');
  } finally { mock.timers.reset(); }
});

test('blur then focus inside the delay sends nothing; focus after a sent blur sends false at once', () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    const r = rig(); r.ctl.open();
    const [w] = r.log.wins;
    w.handlers.blur(); mock.timers.tick(500); w.handlers.focus(); mock.timers.tick(5000);
    assert.deepEqual(blurredSends(w), [], 'never blurred, so focus has nothing to undo');
    w.handlers.blur(); mock.timers.tick(1000);
    w.handlers.focus();
    assert.deepEqual(blurredSends(w), [true, false], 'false goes out in the same turn, no timer');
  } finally { mock.timers.reset(); }
});

test('did-finish-load pushes the current state once; blur never touches throttling or window-hidden', () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    const r = rig(); r.ctl.open();
    const [w] = r.log.wins;
    w.focused = true; w.webContents.handlers['did-finish-load']();
    assert.deepEqual(blurredSends(w), [false]);
    w.focused = false; w.webContents.handlers['did-finish-load']();
    assert.deepEqual(blurredSends(w), [false, true]);
    w.handlers.blur(); mock.timers.tick(1000); w.handlers.focus();
    assert.equal(w.webContents.throttlingCalls, 0);
    assert.equal(w.webContents.sent.some((s) => s[0] === 'carnivore:window-hidden'), false);
    w.handlers.blur(); w.handlers.closed(); mock.timers.tick(5000);
    assert.deepEqual(blurredSends(w), [false, true, false], 'closed cleared the pending timer: no further send');
  } finally { mock.timers.reset(); }
});

function page() {
  const listeners = {}; const attrs = {}; const events = []; const types = [];
  const win = {
    carnivoreDesktop: {}, location: { origin: ORIGIN },
    addEventListener(t, fn) { listeners[t] = fn; },
  };
  win.window = win;
  const document = {
    documentElement: { getAttribute: (k) => (k in attrs ? attrs[k] : null), setAttribute: (k, v) => { attrs[k] = v; }, removeAttribute: (k) => { delete attrs[k]; } },
    dispatchEvent(e) { types.push(e.type); if (e.type === 'carnivore:calm') events.push(e.detail); },
  };
  const ctx = vm.createContext({ window: win, document, CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init.detail; } } });
  vm.runInContext(fs.readFileSync(path.join(repo, 'client/js/desktop-window-calm.js'), 'utf8'), ctx);
  const post = (data, over = {}) => listeners.message({ source: win, origin: ORIGIN, data, ...over });
  return { win, attrs, events, types, post };
}

test('page script: data-calm reasons, one carnivore:calm per presence flip, no visibilitychange', () => {
  const p = page();
  p.post({ type: 'carnivore.window-blurred', blurred: true });
  p.post({ type: 'carnivore.power-calm', calm: true, reason: 'low-power' });
  assert.equal(p.attrs['data-calm'], 'blur low-power');
  assert.equal(p.win.CarnivoreWindowBlurred, true);
  assert.equal(p.win.CarnivorePowerCalm, true);
  assert.equal(p.win.CarnivorePowerReason, 'low-power');
  assert.equal(p.events.length, 1, 'only the first flip fires');
  assert.equal(JSON.stringify(p.events[0]), JSON.stringify({ calm: true, reasons: ['blur'] }));
  p.post({ type: 'carnivore.window-blurred', blurred: false });
  assert.equal(p.attrs['data-calm'], 'low-power');
  p.post({ type: 'carnivore.power-calm', calm: false, reason: '' });
  assert.equal('data-calm' in p.attrs, false);
  assert.equal(JSON.stringify(p.events.at(-1)), JSON.stringify({ calm: false, reasons: [] }));
  assert.equal(p.events.length, 2);
  assert.equal(p.types.includes('visibilitychange'), false);
  assert.equal('CarnivoreWindowHidden' in p.win, false);
});

test('page script: wrong source, origin or shape is ignored', () => {
  const p = page();
  p.post({ type: 'carnivore.window-blurred', blurred: true }, { source: {} });
  p.post({ type: 'carnivore.window-blurred', blurred: true }, { origin: 'http://evil.example' });
  p.post({ type: 'carnivore.window-blurred', blurred: 'yes' });
  p.post({ type: 'carnivore.power-calm', calm: true, reason: 'Not Valid!' });
  p.post({ type: 'carnivore.power-calm', calm: 1, reason: 'thermal' });
  p.post(null);
  assert.equal('data-calm' in p.attrs, false);
  assert.equal(p.events.length, 0);
  assert.equal(p.types.length, 0);
});

test('preload re-posts only validated shapes', () => {
  const src = fs.readFileSync(path.join(macDir, 'app-window-preload.js'), 'utf8');
  assert.match(src, /ipcRenderer\.on\('carnivore:window-blurred'[\s\S]*typeof blurred === 'boolean'/);
  assert.match(src, /ipcRenderer\.on\('carnivore:power-calm'[\s\S]*\/\^\[a-z-\]\{0,12\}\$\/\.test\(state\.reason\)/);
});
