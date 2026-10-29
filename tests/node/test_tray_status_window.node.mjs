import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { load, macDir, repo, env, snap, byId } from './tray_menu_fixtures.mjs';

const require = createRequire(import.meta.url);
const { createActivateHandler } = require(path.join(macDir, 'dock-activate.js'));
const { createStatusWindow, PARTITION, FACTS_CHANNEL, ACTION_CHANNEL } = require(path.join(macDir, 'status-window.js'));
const { statusFacts, actionForClick, BUTTON_IDS } = load('status-facts.js');
const { buildMenuModel } = load('model/index.js');
const { allHandlers } = load('actions/index.js');

const down = (over = {}) => snap({ server: { state: 'stopped' }, offline: { alive: 3, tmuxRunning: true, error: null }, offlineTuiAvailable: true, ...over });

function harness({ appOpen = false, running = false, statusOpens = true, withStatus = true } = {}) {
  const calls = [];
  const handler = createActivateHandler({
    appWindow: { isOpen: () => appOpen, open: () => { calls.push('app.open'); return true; } },
    isServerRunning: () => running,
    getTray: () => ({ popUpContextMenu: () => calls.push('tray.pop') }),
    getTrayMenu: () => ({ m: 1 }),
    statusWindow: withStatus ? { open: () => { calls.push('status.open'); return statusOpens; }, close: () => calls.push('status.close') } : undefined,
  });
  return { handler, calls };
}

test('dock activate: server down opens the status window, not the tray menu', () => {
  const h = harness(); h.handler();
  assert.deepEqual(h.calls, ['status.open']);
});

test('dock activate: server up closes the status window and opens the app window', () => {
  const h = harness({ running: true }); h.handler();
  assert.deepEqual(h.calls, ['status.close', 'app.open']);
});

test('dock activate: an open app window is focused first; the status window cannot open falls back to the tray menu', () => {
  const a = harness({ appOpen: true }); a.handler();
  assert.deepEqual(a.calls, ['app.open']);
  const b = harness({ statusOpens: false }); b.handler();
  assert.deepEqual(b.calls, ['status.open', 'tray.pop']);
  const c = harness({ withStatus: false }); c.handler();
  assert.deepEqual(c.calls, ['tray.pop']);
});

test('facts are the tray header: status line, why row and the four buttons from the model', () => {
  const s = down();
  const items = buildMenuModel(s, env);
  const facts = statusFacts(s, items, env.t);
  assert.equal(facts.status, byId(items, 'header').sublabel);
  assert.ok(facts.status.includes('server stopped') && facts.status.includes('3 agents alive in tmux'));
  assert.equal(facts.why.text, byId(items, 'server.why').label);
  assert.deepEqual(facts.buttons.map((b) => b.id), [...BUTTON_IDS]);
  assert.deepEqual(facts.buttons.map((b) => b.label), ['Start Server', 'Terminal (Offline)...', 'Open Server Log in Console', 'Copy Diagnostics']);
  assert.equal(statusFacts(snap(), buildMenuModel(snap(), env), env.t), null, 'nothing to show while the server is up');
});

test('a disabled model item stays disabled in the window, with its reason', () => {
  const s = down({ offlineTuiAvailable: false });
  const facts = statusFacts(s, buildMenuModel(s, env), env.t);
  const offline = facts.buttons.find((b) => b.id === 'terminal.offline');
  assert.equal(offline.enabled, false);
  assert.ok(offline.reason);
});

test('window clicks resolve to the model item action the tray itself dispatches, and every kind has a handler', () => {
  const items = buildMenuModel(down(), env);
  const table = allHandlers({ serverManager: {}, dialog: {} });
  for (const id of BUTTON_IDS) {
    const action = actionForClick(items, id);
    assert.deepEqual(action, byId(items, id).action);
    assert.equal(typeof table[action.kind], 'function', `${action.kind} has a tray handler`);
  }
  assert.equal(actionForClick(items, 'quit'), null, 'only the window ids run');
  assert.equal(actionForClick(items, { id: 'server.start' }), null);
  assert.equal(actionForClick(buildMenuModel(down({ offlineTuiAvailable: false }), env), 'terminal.offline'), null, 'disabled does not run');
});

function fakeElectron() {
  const handlers = new Map();
  const ipcMain = { handle: (c, f) => handlers.set(`h:${c}`, f), on: (c, f) => handlers.set(`o:${c}`, f) };
  const wins = [];
  class BrowserWindow {
    constructor(opts) {
      this.opts = opts; this.visible = false; this.destroyed = false; this.sent = []; this.ev = {}; this.once_ = {};
      this.webContents = { on() {}, setWindowOpenHandler() {}, session: { setPermissionRequestHandler() {}, protocol: { handle() {}, isProtocolHandled: () => false } }, insertCSS: async () => {}, send: (...a) => this.sent.push(a) };
      wins.push(this);
    }
    on(e, f) { this.ev[e] = f; }
    once(e, f) { this.once_[e] = f; }
    loadURL(u) { this.url = u; }
    show() { this.visible = true; this.ev.show && this.ev.show(); }
    hide() { this.visible = false; this.ev.hide && this.ev.hide(); }
    focus() {} restore() {} isMinimized() { return false; }
    isVisible() { return this.visible; }
    isDestroyed() { return this.destroyed; }
    destroy() { this.destroyed = true; }
  }
  return { ipcMain, handlers, wins, BrowserWindow };
}

test('status window: one instance, locked down, closing hides, button clicks run through runAction', () => {
  const fe = fakeElectron();
  let facts = { windowTitle: 'Carnivore', status: 'server stopped' };
  const ran = [];
  const w = createStatusWindow({ BrowserWindow: fe.BrowserWindow, ipcMain: fe.ipcMain,
    getFacts: () => facts, runAction: (id) => ran.push(id), tokensCss: () => ':root{}' });
  assert.equal(w.open(), true);
  assert.equal(fe.wins.length, 1);
  const win = fe.wins[0];
  assert.deepEqual([win.opts.webPreferences.contextIsolation, win.opts.webPreferences.nodeIntegration, win.opts.webPreferences.sandbox], [true, false, true]);
  assert.equal(win.opts.webPreferences.partition, PARTITION);
  assert.ok(!PARTITION.startsWith('persist:') && PARTITION.length > 0, 'its own in-memory session');
  assert.equal(win.opts.backgroundColor, load('oc-token-values.js').TOKEN_HEX['--oc-ground-chrome']);
  assert.ok(win.opts.webPreferences.preload.endsWith('status-window-preload.js'));
  assert.equal(win.url, 'carnivore-page://status/status.html', 'served by its own session, not file:// inside app.asar (#2477)');
  win.once_['ready-to-show']();
  assert.equal(w.isOpen(), true);
  const top = { url: 'file:///status.html' };
  win.webContents.mainFrame = top;
  const ownEvent = { sender: win.webContents, senderFrame: top };
  fe.handlers.get(`o:${ACTION_CHANNEL}`)(ownEvent, 'server.start');
  fe.handlers.get(`o:${ACTION_CHANNEL}`)({ sender: {} }, 'server.stop');
  assert.deepEqual(ran, ['server.start'], 'a foreign sender is ignored');
  assert.equal(fe.handlers.get(`h:${FACTS_CHANNEL}`)(ownEvent), facts);
  assert.equal(fe.handlers.get(`h:${FACTS_CHANNEL}`)({ sender: {} }), null);
  const sub = { sender: win.webContents, senderFrame: { url: 'file:///status.html#sub' } };
  fe.handlers.get(`o:${ACTION_CHANNEL}`)(sub, 'server.stop');
  assert.deepEqual(ran, ['server.start'], 'a sub-frame of our own window is ignored (main-frame check)');
  assert.equal(fe.handlers.get(`h:${FACTS_CHANNEL}`)(sub), null);
  assert.equal(fe.handlers.get(`h:${FACTS_CHANNEL}`)({ sender: win.webContents, senderFrame: null }), null);
  let prevented = false;
  win.ev.close({ preventDefault: () => { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(w.isOpen(), false, 'close hides');
  assert.equal(w.open(), true);
  assert.equal(fe.wins.length, 1, 'still one instance');
  w.update();
  assert.equal(win.sent.at(-1)[0], FACTS_CHANNEL);
  facts = null;
  w.update();
  assert.equal(w.isOpen(), false, 'the server came back: the window goes away');
  assert.equal(w.open(), false, 'nothing to show while up');
  w.destroy();
  assert.equal(win.destroyed, true);
});

test('the page: local file, strict CSP, no inline script, no remote anything, tokens only', () => {
  const dir = path.join(macDir, 'status-window');
  const html = fs.readFileSync(path.join(dir, 'status.html'), 'utf8');
  assert.ok(html.includes("default-src 'self'"));
  assert.equal(/<script(?![^>]*\bsrc=)/.test(html), false, 'no inline script');
  assert.equal(/https?:\/\//.test(html + fs.readFileSync(path.join(dir, 'status.js'), 'utf8')), false);
  const css = fs.readFileSync(path.join(dir, 'status.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.equal(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/.test(css), false, 'no literal colors');
  for (const m of css.matchAll(/var\((--oc-[a-z-]+)/g)) {
    assert.ok(load('oc-token-values.js').TOKEN_HEX[m[1]], `${m[1]} is injected by tokensCss`);
  }
});

test('catalog: the window strings exist and carry no dash characters or emoji', async () => {
  const keys = ['menubar.status_window.window_title', 'menubar.status_window.title', 'menubar.status_window.why_hint'];
  for (const k of keys) {
    const v = env.t(k);
    assert.notEqual(v, k, `${k} missing`);
    assert.equal(/[\u2013\u2014]|\p{Extended_Pictographic}/u.test(v), false);
  }
});

test('the page: the confirming button is chosen by id, and focus follows the shared border rule', () => {
  const dir = path.join(macDir, 'status-window');
  const js = fs.readFileSync(path.join(dir, 'status.js'), 'utf8');
  assert.ok(js.includes("'server.start'") && !js.includes('CONFIRM_INDEX'));
  const css = fs.readFileSync(path.join(dir, 'status.css'), 'utf8');
  assert.ok(/\.sw-why\s*\{[^}]*border:\s*1px solid transparent/.test(css), 'reserved 1px border');
  assert.ok(/focus-visible[\s\S]*?border-color:\s*color-mix\(/.test(css));
  assert.equal(/focus-visible[^}]*(box-shadow|--oc-cyan)/.test(css), false);
});
