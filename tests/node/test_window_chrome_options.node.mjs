import test from 'node:test';
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

function balanced(text, open) {
  let depth = 0;
  for (let i = open; i < text.length; i++) {
    if (text[i] === '{') depth += 1;
    else if (text[i] === '}' && --depth === 0) return text.slice(open + 1, i);
  }
  return null;
}

function auditChrome(source) {
  const problems = [];
  const sites = [...source.matchAll(/new\s+BrowserWindow\s*\(\s*([A-Za-z_$][\w$]*|\{)/g)];
  if (sites.length === 0) problems.push('no window constructor found');
  for (const m of sites) {
    const decl = m[1] === '{' ? null : new RegExp(`(?:const|let|var)\\s+${m[1]}\\s*=\\s*\\{`).exec(source);
    const options = m[1] === '{' ? balanced(source, m.index + m[0].length - 1) : decl ? balanced(source, decl.index + decl[0].length - 1) : null;
    if (options === null) { problems.push('options object not found'); continue; }
    const spread = /\.\.\.\s*chromeOptions\s*\(\s*kind\s*\)/.test(options);
    const literal = /\btabbingIdentifier\s*:/.test(options) && /\btitleBarStyle\s*:\s*['"]hiddenInset['"]/.test(options);
    if (!spread && !literal) problems.push('options carry no tabbing id and title bar style');
  }
  if (/visibleOnAllWorkspaces/.test(source)) problems.push('visibleOnAllWorkspaces is set');
  if (/fullscreenable\s*:\s*false/.test(source)) problems.push('fullscreenable is false');
  return problems;
}

function rig(dir) {
  const log = { wins: [], handle: {} };
  class FakeWindow {
    constructor(options) {
      this.options = options;
      this.gone = false;
      this.handlers = {};
      this.fullScreen = false;
      this.webContents = {
        mainFrame: { url: `${ORIGIN}/` }, sent: [], on() {}, reload() {}, send(...a) { this.sent.push(a); },
        isLoading() { return false; }, once() {}, setWindowOpenHandler: (fn) => { this.openHandler = fn; },
        session: { setPermissionRequestHandler() {}, setPermissionCheckHandler() {} },
      };
      log.wins.push(this);
    }
    once() {} on(ev, fn) { this.handlers[ev] = fn; } isDestroyed() { return this.gone; } isMinimized() { return false; }
    show() {} focus() {} restore() {} destroy() { this.gone = true; } getTitle() { return 'carnivore'; } loadURL() {} isFocused() { return false; }
    getNormalBounds() { return { x: 0, y: 0, width: 800, height: 600 }; } isMaximized() { return false; } isFullScreen() { return this.fullScreen; }
  }
  const electron = {
    BrowserWindow: FakeWindow, Notification: class { static isSupported() { return true; } on() {} show() {} }, shell: { openExternal() {} },
    ipcMain: { on() {}, handle: (n, fn) => { log.handle[n] = fn; } },
  };
  const realLoad = Module._load;
  Module._load = function (request, ...rest) { return request === 'electron' ? electron : realLoad.call(this, request, ...rest); };
  try {
    for (const f of ['app-window.js', 'window-host.js', 'window-ipc.js', 'desktop-settings.js', 'window-chrome.js']) {
      try { delete require.cache[require.resolve(path.join(macDir, f))]; } catch (e) { if (e.code !== 'MODULE_NOT_FOUND') throw e; }
    }
    const { createWindowState } = require(path.join(macDir, 'window-state.js'));
    const state = createWindowState({ dir: () => dir, getDisplays: () => [{ workArea: { x: 0, y: 0, width: 1920, height: 1080 } }] });
    const ctl = require(path.join(macDir, 'app-window.js')).createAppWindow({ getUrl: () => ORIGIN, windowState: state });
    require(path.join(macDir, 'window-ipc.js')).registerWindowIpc({ ipcMain: electron.ipcMain, appWindow: ctl });
    return { log, ctl };
  } finally {
    Module._load = realLoad;
  }
}

test('source audit: the one app-window constructor carries the chrome options; the audit goes red on a fixture', () => {
  const source = fs.readFileSync(path.join(macDir, 'window-host.js'), 'utf8');
  assert.equal([...source.matchAll(/new\s+BrowserWindow\s*\(/g)].length, 1, 'population check: exactly one app-window constructor');
  assert.deepEqual(auditChrome(source), []);
  assert.match(auditChrome('const options = { width: 1, webPreferences: { sandbox: true } };\nreturn new BrowserWindow(options);').join(), /no tabbing id/);
  assert.match(auditChrome('new BrowserWindow({ ...chromeOptions(kind), visibleOnAllWorkspaces: true })').join(), /visibleOnAllWorkspaces/);
  assert.match(auditChrome('new BrowserWindow({ ...chromeOptions(kind), fullscreenable: false })').join(), /fullscreenable is false/);
  assert.match(auditChrome('nothing here').join(), /no window constructor/);
  assert.deepEqual(auditChrome('new BrowserWindow({ ...chromeOptions(kind) })'), []);
});

test('every kind of window opens with its own tabbing id and the hidden-inset title bar', () => {
  const r = rig(fs.mkdtempSync(path.join(os.tmpdir(), 'window-chrome-test-')));
  r.ctl.open();
  r.log.wins[0].openHandler({ url: `${ORIGIN}/static/popout.html?widget=stats`, frameName: 'carnivore-stats', features: '', disposition: 'new-window' });
  assert.equal(r.ctl.openSolo('7'), true);
  assert.equal(r.log.wins.length, 3);
  const ids = r.log.wins.map((w) => w.options.tabbingIdentifier);
  assert.deepEqual(ids, ['carnivore-main', 'carnivore-popout', 'carnivore-solo']);
  assert.equal(new Set(ids).size, 3, 'a tab merges only within a kind');
  for (const w of r.log.wins) {
    assert.equal(w.options.titleBarStyle, 'hiddenInset');
    assert.ok(Number.isFinite(w.options.trafficLightPosition.x) && Number.isFinite(w.options.trafficLightPosition.y));
    assert.notEqual(w.options.fullscreenable, false);
    assert.equal('visibleOnAllWorkspaces' in w.options, false);
    assert.equal(w.options.webPreferences.sandbox, true, 'the hardened web preferences are untouched');
    assert.equal(w.options.webPreferences.backgroundThrottling, false, 'a hidden window keeps running (R1-10)');
  }
});

test('window-chrome.js: an unknown kind throws, the state zeroes the inset in full screen, the numbers are finite', () => {
  const chrome = require(path.join(macDir, 'window-chrome.js'));
  assert.throws(() => chrome.chromeOptions('bogus'), /unknown window kind/);
  assert.throws(() => chrome.chromeOptions('__proto__'), /unknown window kind/);
  const normal = chrome.chromeState({ isFullScreen: () => false });
  assert.deepEqual(normal, { titleBar: 'hiddenInset', inset: { top: chrome.INSET.top, left: chrome.INSET.left }, fullScreen: false });
  assert.ok(normal.inset.top > 0 && normal.inset.left > 0);
  assert.deepEqual(chrome.chromeState({ isFullScreen: () => true }), { titleBar: 'hiddenInset', inset: { top: 0, left: 0 }, fullScreen: true });
});

test('the bridge read: a registered window top frame gets numbers, a stranger or a sub-frame gets null; full screen is pushed', async () => {
  const r = rig(fs.mkdtempSync(path.join(os.tmpdir(), 'window-chrome-test-')));
  r.ctl.open();
  const [main] = r.log.wins;
  const handler = r.log.handle['carnivore:window-chrome'];
  assert.equal(typeof handler, 'function');
  const event = (sender, frame) => ({ sender, senderFrame: frame });
  const state = await handler(event(main.webContents, main.webContents.mainFrame));
  assert.equal(state.titleBar, 'hiddenInset');
  assert.equal(state.fullScreen, false);
  assert.ok(state.inset.top > 0);
  const stranger = { mainFrame: { url: `${ORIGIN}/` } };
  assert.equal(await handler(event(stranger, stranger.mainFrame)), null, 'not a registered window');
  assert.equal(await handler(event(main.webContents, { url: `${ORIGIN}/` })), null, 'not the top frame');
  assert.equal(await handler(event(main.webContents, { url: 'http://evil.example/' })), null);
  main.fullScreen = true;
  main.handlers['enter-full-screen']();
  assert.deepEqual(main.webContents.sent.at(-1), ['carnivore:window-chrome', { titleBar: 'hiddenInset', inset: { top: 0, left: 0 }, fullScreen: true }]);
  main.fullScreen = false;
  main.handlers['leave-full-screen']();
  assert.equal(main.webContents.sent.at(-1)[1].inset.top > 0, true);
  assert.equal(main.webContents.sent.at(-1)[1].fullScreen, false);
  assert.match(fs.readFileSync(path.join(macDir, 'app-window-preload.js'), 'utf8'), /'windowChrome'/);
});

test('the Window menu carries the three tab roles', () => {
  const { buildTemplate } = require(path.join(macDir, 'app-menu', 'index.js'));
  const deps = { t: (k) => k, appName: 'Carnivore', isPackaged: false, appWindow: {}, showAbout() {}, quitAndStopEngine() {}, openUrl() {}, waiting: () => null, exportDiagnostics() {} };
  const menu = buildTemplate(deps).find((m) => m.id === 'window');
  const roles = menu.submenu.map((i) => i.role).filter(Boolean);
  assert.equal(menu.role, 'window');
  for (const role of ['toggleTabBar', 'mergeAllWindows', 'moveTabToNewWindow']) assert.ok(roles.includes(role), role);
  assert.equal(roles.length, new Set(roles).size, 'each item once');
});

function runPage({ bridge, origin = ORIGIN }) {
  const props = {};
  const html = { dataset: {}, style: { setProperty: (k, v) => { props[k] = v; }, removeProperty: (k) => { delete props[k]; } } };
  const listeners = {};
  const win = { location: { origin }, addEventListener: (ev, fn) => { listeners[ev] = fn; } };
  if (bridge) win.carnivoreDesktop = bridge;
  win.document = { documentElement: html };
  const context = vm.createContext(win);
  vm.runInContext('this.window = this', context);
  vm.runInContext(fs.readFileSync(path.join(repo, 'client', 'js', 'desktop-chrome.js'), 'utf8'), context);
  return { html, props, listeners, win: vm.runInContext('window', context) };
}

test('desktop-chrome.js: no bridge, no stamp and no inset; with it the stamp is synchronous and a foreign message is ignored', async () => {
  const none = runPage({ bridge: null });
  assert.deepEqual(none.html.dataset, {});
  assert.deepEqual(none.props, {});
  const noCap = runPage({ bridge: { capabilities: ['notify'] } });
  assert.deepEqual(noCap.html.dataset, {});
  let asked = 0;
  const page = runPage({ bridge: { capabilities: ['windowChrome'], windowChrome: () => { asked += 1; return Promise.resolve({ titleBar: 'hiddenInset', inset: { top: 28, left: 78 }, fullScreen: false }); } } });
  assert.equal(page.html.dataset.desktopChrome, '', 'stamped before the async answer');
  assert.equal(asked, 1);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(page.props['--desktop-inset-top'], '28px');
  assert.equal(page.props['--desktop-inset-left'], '78px');
  const full = { titleBar: 'hiddenInset', inset: { top: 0, left: 0 }, fullScreen: true };
  const send = (data, o = ORIGIN, source = page.win) => page.listeners.message({ data: { type: 'carnivore.window-chrome', ...data }, origin: o, source });
  send(full, 'http://evil.example');
  send(full, ORIGIN, {});
  send({ inset: { top: 9999, left: 1 }, fullScreen: false });
  assert.equal(page.props['--desktop-inset-top'], '28px', 'foreign origin, foreign source and an absurd number change nothing');
  send(full);
  assert.equal(page.props['--desktop-inset-top'], '0px');
  assert.equal(page.html.dataset.fullscreen, '');
  send({ ...full, inset: { top: 28, left: 78 }, fullScreen: false });
  assert.equal(page.props['--desktop-inset-top'], '28px');
  assert.equal('fullscreen' in page.html.dataset, false);
});
