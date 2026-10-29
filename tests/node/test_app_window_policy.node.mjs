import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import Module, { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const policy = require('../../macOS/app-window-policy.js');

const ORIGIN = 'http://127.0.0.1:8000';

test('partition is persistent, stable per origin and distinct across origins', () => {
  const a = policy.partitionForOrigin(ORIGIN);
  assert.match(a, /^persist:carnivore-[0-9a-f]{12}$/);
  assert.equal(a, policy.partitionForOrigin(ORIGIN));
  assert.notEqual(a, policy.partitionForOrigin('http://127.0.0.1:8001'));
  assert.notEqual(a, policy.partitionForOrigin('http://192.168.1.5:8000'));
});

test('partition refuses anything that is not a bare http(s) origin', () => {
  for (const bad of ['', 'file:///tmp/x', 'http://127.0.0.1:8000/path', null, 'javascript:1']) {
    assert.throws(() => policy.partitionForOrigin(bad), bad);
  }
});

test('same origin stays in the window, other http(s) goes to the browser, the rest is denied', () => {
  assert.equal(policy.decideNavigation(`${ORIGIN}/#settings`, ORIGIN), 'allow');
  assert.equal(policy.decideNavigation(`${ORIGIN}/setup?x=1`, ORIGIN), 'allow');
  assert.equal(policy.decideNavigation('https://example.com/', ORIGIN), 'external');
  assert.equal(policy.decideNavigation('http://127.0.0.1:8001/', ORIGIN), 'external');
  assert.equal(policy.decideNavigation('http://localhost:8000/', ORIGIN), 'external');
  assert.equal(policy.decideNavigation('http://127.0.0.1:8000@evil.com/', ORIGIN), 'external');
  for (const bad of ['file:///etc/passwd', 'javascript:alert(1)', 'data:text/html,x', 'carnivore://x', 'not a url', '', null, undefined]) {
    assert.equal(policy.decideNavigation(bad, ORIGIN), 'deny', String(bad));
  }
});

test('only notifications and clipboard write, only for the server origin', () => {
  assert.equal(policy.isPermissionAllowed('notifications', `${ORIGIN}/`, ORIGIN), true);
  assert.equal(policy.isPermissionAllowed('clipboard-sanitized-write', ORIGIN, ORIGIN), true);
  assert.equal(policy.isPermissionAllowed('media', `${ORIGIN}/`, ORIGIN), false);
  assert.equal(policy.isPermissionAllowed('geolocation', `${ORIGIN}/`, ORIGIN), false);
  assert.equal(policy.isPermissionAllowed('notifications', 'https://example.com/', ORIGIN), false);
});

const NATIVE_QUERIES = ['', '?widget=stats', '?board=7&edit=1&layout=1', '?agent=ag_1', '?tab=flow', '?browser=b1', '?view=wallboard'];
const DISPOSITIONS = ['foreground-tab', 'background-tab', 'new-window'];

test('in the app every same-origin pop-out page and solo terminal address opens a native window, whatever the disposition (R1-12)', () => {
  for (const q of NATIVE_QUERIES) {
    for (const d of DISPOSITIONS) {
      assert.equal(policy.decideWindowOpen(`${ORIGIN}/static/popout.html${q}`, ORIGIN, d), 'native', `${q} ${d}`);
    }
  }
  for (const d of DISPOSITIONS) assert.equal(policy.decideWindowOpen(`${ORIGIN}/?solo=7`, ORIGIN, d), 'native', d);
  assert.equal(policy.decideWindowOpen(`${ORIGIN}/?solo=${'9'.repeat(15)}`, ORIGIN, 'new-window'), 'native');
});

test('everything else of the app origin is refused, other http(s) goes to the browser, odd schemes are denied (R1-12)', () => {
  for (const bad of ['/?solo=abc', '/?solo=7&x=1', '/?solo=', `/?solo=${'9'.repeat(16)}`, '/?solo=7#x', '/', '/setup', '/static/other.html', '/static/popout.html/x', '/api/v1/artifacts/1/view']) {
    assert.equal(policy.decideWindowOpen(`${ORIGIN}${bad}`, ORIGIN, 'new-window'), 'deny', bad);
  }
  assert.equal(policy.decideWindowOpen('http://user:pw@127.0.0.1:8000/static/popout.html', ORIGIN, 'new-window'), 'deny');
  assert.equal(policy.decideWindowOpen(`${ORIGIN}/static/popout.html?x=${'a'.repeat(2100)}`, ORIGIN, 'new-window'), 'deny');
  assert.equal(policy.decideWindowOpen('https://example.com/static/popout.html', ORIGIN, 'new-window'), 'external');
  assert.equal(policy.decideWindowOpen('http://127.0.0.1:8000@evil.com/static/popout.html', ORIGIN, 'foreground-tab'), 'external');
  assert.equal(policy.decideWindowOpen('http://127.0.0.1:8001/?solo=7', ORIGIN, 'new-window'), 'external');
  for (const bad of ['about:blank', 'javascript:1', 'file:///etc/passwd', 'data:text/html,x', 'carnivore://x', '', null]) {
    assert.equal(policy.decideWindowOpen(bad, ORIGIN, 'foreground-tab'), 'deny', String(bad));
  }
});

test('popoutWindowKey: the page name is the key, a fresh name is a second window, a solo address keys by row (R1-12)', () => {
  const url = `${ORIGIN}/static/popout.html?tab=flow`;
  assert.equal(policy.popoutWindowKey(url, 'carnivore-stats'), 'popout:carnivore-stats');
  assert.equal(policy.popoutWindowKey(url, 'carnivore-stats'), policy.popoutWindowKey(url, 'carnivore-stats'));
  assert.notEqual(policy.popoutWindowKey(url, 'carnivore-stats'), policy.popoutWindowKey(url, 'carnivore-stats-k3x9'));
  assert.match(policy.popoutWindowKey(url, ''), /^popout:[0-9a-f]{12}$/);
  assert.notEqual(policy.popoutWindowKey(url, ''), policy.popoutWindowKey(`${ORIGIN}/static/popout.html?tab=huddle`, ''));
  assert.equal(policy.popoutWindowKey(`${ORIGIN}/?solo=7`, 'whatever'), 'solo:row:7');
  assert.deepEqual(policy.nativeTarget(`${ORIGIN}/?solo=7`, ORIGIN), { kind: 'solo', path: '/?solo=7' });
  assert.deepEqual(policy.nativeTarget(`${ORIGIN}/static/popout.html?tab=flow`, ORIGIN), { kind: 'popout', path: '/static/popout.html?tab=flow' });
  assert.equal(policy.nativeTarget(`${ORIGIN}/static/popout.html`, 'http://127.0.0.1:8001'), null);
});

test('boundsFromFeatures reads only the finite size and place the page asked for (R1-12)', () => {
  assert.deepEqual(policy.boundsFromFeatures('popup=yes,width=900,height=700,left=40,top=-60'), { width: 900, height: 700, x: 40, y: -60 });
  assert.deepEqual(policy.boundsFromFeatures('popup=yes,width=abc,left=99999999'), {});
  assert.deepEqual(policy.boundsFromFeatures(undefined), {});
});

const macDir = path.join(import.meta.dirname, '..', '..', 'macOS');

function rig(dir, url = ORIGIN) {
  const log = { wins: [], handle: {}, notes: [] };
  class FakeWindow {
    constructor(options) {
      this.options = options;
      this.gone = false;
      this.shown = 0;
      this.handlers = {};
      this.loaded = [];
      this.webContents = {
        mainFrame: { url: `${ORIGIN}/` }, sent: [], on() {}, reload() {}, send(...a) { this.sent.push(a); },
        loading: false, isLoading() { return this.loading; }, once(ev, fn) { this.finish = fn; },
        setWindowOpenHandler: (fn) => { this.openHandler = fn; },
        session: { setPermissionRequestHandler() {}, setPermissionCheckHandler() {} },
      };
      log.wins.push(this);
    }
    closeIt() { this.gone = true; this.handlers.closed?.(); }
    once() {} on(ev, fn) { this.handlers[ev] = fn; } isDestroyed() { return this.gone; } isMinimized() { return false; }
    show() { this.shown += 1; } focus() {} restore() {} destroy() { this.gone = true; } getTitle() { return 'carnivore'; }
    loadURL(u) { this.loaded.push(u); } isFocused() { return false; }
    getNormalBounds() { return { x: 0, y: 0, width: 800, height: 600 }; } isMaximized() { return false; } isFullScreen() { return false; }
  }
  class FakeNotification {
    static isSupported() { return true; }
    constructor() { log.notes.push(this); }
    on() {} show() {}
  }
  const ipc = {};
  const electron = {
    BrowserWindow: FakeWindow, Notification: FakeNotification, shell: { openExternal() {} },
    ipcMain: { on: (n, fn) => { ipc[n] = fn; }, handle: (n, fn) => { log.handle[n] = fn; } },
  };
  const realLoad = Module._load;
  Module._load = function (request, ...rest) {
    return request === 'electron' ? electron : realLoad.call(this, request, ...rest);
  };
  const clock = { t: 0, step: 1000 };
  try {
    for (const f of ['app-window.js', 'window-host.js', 'window-ipc.js', 'desktop-settings.js']) delete require.cache[require.resolve(path.join(macDir, f))];
    const { createWindowState } = require(path.join(macDir, 'window-state.js'));
    const state = createWindowState({ dir: () => dir, getDisplays: () => [{ workArea: { x: 0, y: 0, width: 1920, height: 1080 } }] });
    const ctl = require(path.join(macDir, 'app-window.js')).createAppWindow({ getUrl: () => url, windowState: state });
    require(path.join(macDir, 'window-ipc.js')).registerWindowIpc({ ipcMain: electron.ipcMain, appWindow: ctl, now: () => (clock.t += clock.step) });
    return { log, ctl, ipc, state, clock };
  } finally {
    Module._load = realLoad;
  }
}

const tmpDir = () => fs.mkdtempSync(path.join(os.tmpdir(), 'window-host-test-'));
const pageOpens = (win, url, frameName = '', features = '', disposition = 'new-window') => win.openHandler({ url, frameName, features, disposition });

test('host: a pop-out is a fresh native window, a second open of the same name focuses it, the handler always denies (R1-12)', () => {
  const r = rig(tmpDir());
  r.ctl.open();
  const [main] = r.log.wins;
  const popUrl = `${ORIGIN}/static/popout.html?widget=stats`;
  assert.deepEqual(pageOpens(main, popUrl, 'carnivore-stats', 'popup=yes,width=900,height=700,left=40,top=60'), { action: 'deny' });
  assert.equal(r.log.wins.length, 2, 'a BrowserWindow was constructed, not a child');
  const pop = r.log.wins[1];
  assert.deepEqual([pop.options.x, pop.options.y, pop.options.width, pop.options.height], [40, 60, 900, 700]);
  assert.deepEqual(pop.loaded, [popUrl]);
  pageOpens(main, popUrl, 'carnivore-stats');
  assert.equal(r.log.wins.length, 2, 'same name: no second window');
  assert.equal(pop.shown, 1, 'and the existing one was raised');
  pageOpens(main, popUrl, 'carnivore-stats-k3x9');
  assert.equal(r.log.wins.length, 3, 'a fresh nonce name is a second window');
  assert.deepEqual(pageOpens(pop, 'https://example.com/', '', '', 'foreground-tab'), { action: 'deny' });
  assert.deepEqual(pageOpens(pop, `${ORIGIN}/setup`), { action: 'deny' });
  assert.equal(r.log.wins.length, 3, 'a non-native address opens nothing');
  assert.deepEqual(r.ctl.list().map((w) => w.key).sort(), ['main', 'popout:carnivore-stats', 'popout:carnivore-stats-k3x9']);
});

test('host: every kind of window gets the same hardened options, partition and preload (R1-12)', () => {
  const r = rig(tmpDir());
  r.ctl.open();
  pageOpens(r.log.wins[0], `${ORIGIN}/static/popout.html`, 'a');
  assert.equal(r.ctl.openSolo('7'), true);
  assert.equal(r.log.wins.length, 3);
  const prefs = r.log.wins.map((w) => w.options.webPreferences);
  for (const p of prefs) {
    assert.equal(p.contextIsolation, true);
    assert.equal(p.sandbox, true);
    assert.equal(p.nodeIntegration, false);
    assert.equal(p.partition, policy.partitionForOrigin(ORIGIN));
    assert.match(p.preload, /app-window-preload\.js$/);
  }
  assert.equal(new Set(prefs.map((p) => JSON.stringify(p))).size, 1, 'one options object for every kind');
  assert.deepEqual(r.log.wins[2].loaded, [`${ORIGIN}/?solo=7`]);
  assert.equal(r.ctl.openSolo('7'), true);
  assert.equal(r.log.wins.length, 3, 'a row that has a window is focused, not opened twice');
  assert.equal(r.ctl.focusSolo('7'), true);
  assert.equal(r.ctl.focusSolo('8'), false);
  for (const bad of ['abc', '', '7;', '9'.repeat(16), 7, null]) assert.equal(r.ctl.openSolo(bad), false, String(bad));
});

test('host: ownsSender is true for any registered window, false for a stranger or a closed one; notify is main only (R1-12)', () => {
  const r = rig(tmpDir());
  r.ctl.open();
  const [main] = r.log.wins;
  pageOpens(main, `${ORIGIN}/static/popout.html`, 'a');
  const pop = r.log.wins[1];
  assert.equal(r.ctl.ownsSender(main.webContents), true);
  assert.equal(r.ctl.ownsSender(pop.webContents), true);
  assert.equal(r.ctl.ownsSender({}), false);
  assert.equal(r.ctl.ownsSender(null), false);
  const ask = (w) => r.ipc['carnivore:notify']({ sender: w.webContents, senderFrame: w.webContents.mainFrame }, 't', 'b', 'ses_1');
  ask(pop);
  assert.equal(r.log.notes.length, 0, 'a pop-out posts no OS notification');
  ask(main);
  assert.equal(r.log.notes.length, 1, 'population check: main still does');
  pop.closeIt();
  assert.equal(r.ctl.ownsSender(pop.webContents), false);
  assert.deepEqual(r.ctl.list().map((w) => w.key), ['main'], 'closing a window drops its key');
  main.closeIt();
  assert.equal(r.ctl.origin(), null);
});

test('host: restore reopens only windows the policy accepts; an old file with no list reopens none (R1-12)', () => {
  const dir = tmpDir();
  const file = path.join(dir, 'window-state.json');
  const good = [{ key: 'popout:carnivore-stats', kind: 'popout', path: '/static/popout.html?widget=stats' }, { key: 'solo:row:7', kind: 'solo', path: '/?solo=7' }];
  const bad = ['http://evil.com/static/popout.html', 'javascript:1', '/static/other.html', `/?solo=${'9'.repeat(16)}`, '//evil.com/static/popout.html', '@evil.com/x', '/?solo=7&x=1', 5, null]
    .map((p, i) => ({ key: `popout:bad${i}`, kind: 'popout', path: p }));
  fs.writeFileSync(file, JSON.stringify({ version: 1, windows: {}, open: [bad[0], good[0], ...bad.slice(1), good[1]] }));
  const r = rig(dir);
  assert.equal(r.ctl.restore(), 2);
  assert.deepEqual(r.ctl.list().map((w) => w.key).sort(), ['popout:carnivore-stats', 'solo:row:7']);
  assert.equal(r.ctl.restore(), 0, 'once per launch');
  const old = tmpDir();
  fs.writeFileSync(path.join(old, 'window-state.json'), JSON.stringify({ version: 1, windows: { main: { x: 0, y: 0, width: 900, height: 700 } } }));
  const r2 = rig(old);
  assert.equal(r2.ctl.restore(), 0);
  assert.equal(r2.log.wins.length, 0);
});

test('host: what was open at a quit comes back, a window the person closed does not (R1-12)', () => {
  const dir = tmpDir();
  const a = rig(dir);
  a.ctl.open();
  pageOpens(a.log.wins[0], `${ORIGIN}/static/popout.html?tab=flow`, 'carnivore-flow');
  pageOpens(a.log.wins[0], `${ORIGIN}/static/popout.html?tab=huddle`, 'carnivore-huddle');
  a.ctl.openSolo('7');
  a.log.wins[2].closeIt();
  a.ctl.setQuitting(true);
  for (const w of a.log.wins) if (!w.gone) w.closeIt();
  const b = rig(dir);
  b.ctl.open();
  assert.equal(b.ctl.restore(), 2);
  assert.deepEqual(b.ctl.list().map((w) => w.key).sort(), ['main', 'popout:carnivore-flow', 'solo:row:7']);
  assert.equal(JSON.parse(fs.readFileSync(path.join(dir, 'window-state.json'), 'utf8')).open.length, 2);
});

test('window IPC: digits only, top frame of a registered window only, and showInMain tells the main page (R1-12)', async () => {
  const r = rig(tmpDir());
  r.ctl.open();
  const [main] = r.log.wins;
  pageOpens(main, `${ORIGIN}/static/popout.html`, 'a');
  const pop = r.log.wins[1];
  const ev = (w, frame = w.webContents.mainFrame) => ({ sender: w.webContents, senderFrame: frame });
  assert.deepEqual(Object.keys(r.log.handle).sort(), ['carnivore:focus-session-window', 'carnivore:open-session-window', 'carnivore:raise-window', 'carnivore:show-in-main', 'carnivore:tear-off', 'carnivore:window-chrome']);
  assert.equal(await r.log.handle['carnivore:open-session-window'](ev(pop), '7'), true, 'a pop-out may ask too');
  assert.equal(r.log.wins.length, 3);
  assert.equal(await r.log.handle['carnivore:focus-session-window'](ev(main), '7'), true);
  for (const bad of ['abc', '7/../x', '', '9'.repeat(16), 7, null, undefined]) {
    assert.equal(await r.log.handle['carnivore:open-session-window'](ev(main), bad), false, String(bad));
  }
  assert.equal(await r.log.handle['carnivore:open-session-window']({ sender: {}, senderFrame: null }, '8'), false, 'a stranger');
  assert.equal(await r.log.handle['carnivore:open-session-window'](ev(main, { url: `${ORIGIN}/embedded` }), '8'), false, 'a sub-frame');
  assert.equal(r.log.wins.length, 3);
  assert.equal(await r.log.handle['carnivore:show-in-main'](ev(r.log.wins[2]), '7'), true);
  assert.deepEqual(main.webContents.sent.at(-1), ['carnivore:show-row', '7']);
});

test('tear-off opens the solo window or the widget pop-out at the cursor, and refuses a forged sender and every bad argument (R2-09)', async () => {
  const r = rig(tmpDir());
  r.ctl.open();
  const [main] = r.log.wins;
  const ev = (w, frame = w.webContents.mainFrame) => ({ sender: w.webContents, senderFrame: frame });
  const tear = r.log.handle['carnivore:tear-off'];
  assert.equal(await tear(ev(main), 'terminal', '7', 500, 300), true);
  const solo = r.log.wins[1];
  assert.deepEqual(solo.loaded, [`${ORIGIN}/?solo=7`]);
  assert.deepEqual([solo.options.x, solo.options.y, solo.options.width, solo.options.height], [420, 282, 960, 640], 'the cursor is on the title strip');
  assert.equal(await tear(ev(main), 'terminal', '7', 900, 900), true, 'the same row again');
  assert.equal(r.log.wins.length, 2, 'focuses the open window, never a second one');
  assert.equal(await tear(ev(main), 'widget', 'core.tasks', 40, 60), true);
  assert.deepEqual(r.log.wins[2].loaded, [`${ORIGIN}/static/popout.html?widget=core.tasks`]);
  assert.deepEqual(r.ctl.list().map((w) => w.key).sort(), ['main', 'popout:carnivore-widget-core.tasks', 'solo:row:7']);
  const before = r.log.wins.length;
  const bad = [
    ['terminal', 'abc', 1, 1], ['terminal', '7/../x', 1, 1], ['terminal', '', 1, 1], ['terminal', '9'.repeat(16), 1, 1], ['terminal', 7, 1, 1],
    ['widget', 'core.tasks?x=1', 1, 1], ['widget', 'core.tasks&widget=x', 1, 1], ['widget', '../static/x', 1, 1], ['widget', 'ses_1', 1, 1],
    ['page', '7', 1, 1], [null, '7', 1, 1], ['terminal', '8', 1.5, 1], ['terminal', '8', '1', 1], ['terminal', '8', 1, NaN], ['terminal', '8', 20001, 1], ['terminal', '8'],
  ];
  for (const args of bad) assert.equal(await tear(ev(main), ...args), false, JSON.stringify(args));
  assert.equal(await tear({ sender: {}, senderFrame: null }, 'terminal', '8', 1, 1), false, 'a stranger');
  assert.equal(await tear(ev(main, { url: `${ORIGIN}/embedded` }), 'terminal', '8', 1, 1), false, 'a sub-frame');
  assert.equal(r.log.wins.length, before, 'nothing opened');
});

test('raise-window raises the calling window only, and refuses a stranger and a sub-frame (R1-13)', async () => {
  const r = rig(tmpDir());
  r.ctl.open();
  const [main] = r.log.wins;
  pageOpens(main, `${ORIGIN}/static/popout.html`, 'a');
  const pop = r.log.wins[1];
  const ev = (w, frame = w.webContents.mainFrame) => ({ sender: w.webContents, senderFrame: frame });
  const raise = r.log.handle['carnivore:raise-window'];
  const [mainBefore, popBefore] = [main.shown, pop.shown];
  assert.equal(await raise(ev(pop)), true);
  assert.equal(pop.shown, popBefore + 1, 'the caller was shown');
  assert.equal(main.shown, mainBefore, 'no other window was touched');
  assert.equal(await raise(ev(main), 'ignored extra argument'), true);
  assert.equal(main.shown, mainBefore + 1);
  assert.equal(pop.shown, popBefore + 1);
  assert.equal(await raise({ sender: {}, senderFrame: null }), false, 'a stranger');
  assert.equal(await raise(ev(main, { url: `${ORIGIN}/embedded` })), false, 'a sub-frame');
  assert.equal(main.shown, mainBefore + 1);
});

test('raise, focus and tear-off are bound to one request per 500 ms per window (R2-BR N7)', async () => {
  const r = rig(tmpDir());
  r.clock.step = 0;
  r.ctl.open();
  const [main] = r.log.wins;
  const ev = (w) => ({ sender: w.webContents, senderFrame: w.webContents.mainFrame });
  const raise = r.log.handle['carnivore:raise-window'];
  const before = main.shown;
  assert.equal(await raise(ev(main)), true);
  assert.equal(await raise(ev(main)), false, 'a loop inside the window is dropped');
  assert.equal(main.shown, before + 1, 'only one raise reached the window');
  r.clock.t += 600;
  assert.equal(await raise(ev(main)), true, 'allowed again after the window');
});

test('open-session and show-in-main raises are bound to one request per 500 ms per window (R2-BR-NOTES D1)', async () => {
  const r = rig(tmpDir());
  r.clock.step = 0;
  r.ctl.open();
  const [main] = r.log.wins;
  const ev = { sender: main.webContents, senderFrame: main.webContents.mainFrame };
  for (const ch of ['carnivore:open-session-window', 'carnivore:show-in-main']) {
    r.clock.t += 600;
    const first = await r.log.handle[ch](ev, '7');
    assert.equal(first, true, `${ch}: the first request goes through`);
    assert.equal(await r.log.handle[ch](ev, '7'), false, `${ch}: a second inside 500 ms is dropped`);
  }
});

test('showInMain on a main window still loading sends once the page has loaded, never before (R1-12 half B)', async () => {
  const r = rig(tmpDir());
  r.ctl.open();
  const [main] = r.log.wins;
  main.webContents.loading = true;
  assert.equal(r.ctl.showInMain('7'), true);
  assert.deepEqual(main.webContents.sent, [], 'nothing is sent into a page that has not loaded');
  main.webContents.loading = false;
  main.webContents.finish();
  assert.deepEqual(main.webContents.sent.at(-1), ['carnivore:show-row', '7']);
});
