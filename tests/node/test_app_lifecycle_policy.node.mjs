import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import Module from 'node:module';
import { fileURLToPath } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const macDir = path.join(root, 'macOS');
const require = Module.createRequire(path.join(macDir, 'x.js'));
const policy = require(path.join(macDir, 'app-lifecycle-policy.js'));
const { handleSecondInstance } = require(path.join(macDir, 'second-instance.js'));
const { createActivateHandler } = require(path.join(macDir, 'dock-activate.js'));
const { createTrayPresence, readMenuBarIcon } = require(path.join(macDir, 'tray-presence.js'));
const { fitToDisplays, createWindowState, FILE: STATE_FILE } = require(path.join(macDir, 'window-state.js'));
const { createQuitNotice, FLAG: NOTICE_FLAG } = require(path.join(macDir, 'quit-notice.js'));

const queue = [];
/** Queue one named case (sync or async); they run in order at the end. */
function t(name, fn) { queue.push([name, fn]); }
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'lifecycle-'));

t('Cmd-Q: the engine survives and the first quit shows the notice', () => {
  assert.deepEqual(policy.quitPlan({ intent: 'app', noticeShown: false, engineSurvivesQuit: true }), { stopEngine: false, showNotice: true });
  assert.deepEqual(policy.quitPlan({ intent: 'app', noticeShown: true, engineSurvivesQuit: true }), { stopEngine: false, showNotice: false });
});
t('Quit and Stop Engine: stops the engine, never shows or uses the notice', () => {
  assert.deepEqual(policy.quitPlan({ intent: 'engine', noticeShown: false, engineSurvivesQuit: true }), { stopEngine: true, showNotice: false });
});
t('the engine survives Cmd-Q (R1-03b): only the engine intent stops it', () => {
  assert.equal(policy.ENGINE_SURVIVES_CMDQ, true);
  assert.equal(policy.quitPlan({ intent: 'app', noticeShown: true, engineSurvivesQuit: policy.ENGINE_SURVIVES_CMDQ }).stopEngine, false);
  assert.equal(policy.quitPlan({ intent: 'engine', noticeShown: true, engineSurvivesQuit: policy.ENGINE_SURVIVES_CMDQ }).stopEngine, true);
});
t('a quit the operating system or the app drives shows no dialog', () => {
  assert.equal(policy.quitPlan({ intent: 'app', noticeShown: false, engineSurvivesQuit: true, systemQuit: true }).showNotice, false);
});

t('window close: the last window closing never quits the app on darwin', () => {
  assert.deepEqual(policy.windowCloseDecision({ platform: 'darwin' }), { quitApp: false });
});

const click = (over) => ({ windowOpen: false, serverRunning: false, statusWindowAvailable: false, trayAvailable: false, ...over });
t('Dock click: the five outcomes', () => {
  assert.equal(policy.dockClickDecision(click({ windowOpen: true, serverRunning: true })), 'raise');
  assert.equal(policy.dockClickDecision(click({ serverRunning: true })), 'open-window');
  assert.equal(policy.dockClickDecision(click({ statusWindowAvailable: true, trayAvailable: true })), 'open-status');
  assert.equal(policy.dockClickDecision(click({ trayAvailable: true })), 'tray-menu');
  assert.equal(policy.dockClickDecision(click({})), 'nothing');
});
t('Dock click: with the menu bar icon off and nothing able to open, the handler does nothing and never pops a bare menu', () => {
  const calls = [];
  const handler = createActivateHandler({
    appWindow: { isOpen: () => false, open: () => { calls.push('open'); return false; } },
    isServerRunning: () => false, getTray: () => null, getTrayMenu: () => { calls.push('menu'); return { m: 1 }; },
  });
  handler();
  assert.deepEqual(calls, [], 'no window to open, no status window, no tray: nothing is touched');
});
t('Dock click: a window that cannot open falls through to the tray menu, popped with an explicit menu', () => {
  const pops = [];
  const handler = createActivateHandler({
    appWindow: { isOpen: () => false, open: () => false }, isServerRunning: () => true,
    getTray: () => ({ popUpContextMenu: (...a) => pops.push(a) }), getTrayMenu: () => ({ m: 1 }),
  });
  handler();
  assert.deepEqual(pops, [[{ m: 1 }]]);
});

t('login launch: no window unless "open a window at login" is on', () => {
  const argv = ['/x/Carnivore', '--login-launch'];
  assert.deepEqual(policy.launchDecision({ argv, windowAtLogin: false }), { loginLaunch: true, openWindow: false });
  assert.deepEqual(policy.launchDecision({ argv, windowAtLogin: true }), { loginLaunch: true, openWindow: true });
});
t('a Dock, Finder or open launch (no marker) opens the window', () => {
  assert.deepEqual(policy.launchDecision({ argv: ['/x/Carnivore'], windowAtLogin: false }), { loginLaunch: false, openWindow: true });
});
t('hostile argv never counts as a login launch', () => {
  for (const argv of [undefined, null, 'x --login-launch', {}, ['--login-launchx'], ['--login-launch=1'], ['x--login-launch'], [' --login-launch'],
    new Array(300).fill('a').concat('--login-launch')]) {
    assert.equal(policy.launchDecision({ argv, windowAtLogin: false }).loginLaunch, false, String(argv).slice(0, 40));
  }
});
t('a first run that needs the setup screen overrides the login rule', () => {
  assert.equal(policy.launchDecision({ argv: ['x', '--login-launch'], windowAtLogin: false, firstRunNeedsWindow: true }).openWindow, true);
});
t('the LaunchAgent argv main builds carries the marker (dev and packaged)', () => {
  const main = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
  assert.match(main, /app\.getPath\('exe'\), lifecycle\.LOGIN_LAUNCH_ARG\]/);
  assert.match(main, /app\.getAppPath\(\), lifecycle\.LOGIN_LAUNCH_ARG\]/);
  assert.equal(policy.LOGIN_LAUNCH_ARG, '--login-launch');
});

t('second instance: the marker raises nothing, anything else focuses, a carnivore: link is carried (R1-11)', () => {
  assert.deepEqual(handleSecondInstance(['x', '--login-launch']), { focus: false, toggle: false, links: [] });
  assert.deepEqual(policy.secondInstanceDecision(['x', '--login-launch']), { focus: false, toggle: false, links: [] });
  assert.deepEqual(handleSecondInstance(['x']), { focus: true, toggle: false, links: [] });
  assert.deepEqual(handleSecondInstance(['x', 'carnivore://open?x=1', '--login-launchx']), { focus: true, toggle: false, links: ['carnivore://open?x=1'] });
  assert.deepEqual(handleSecondInstance(['x', '--login-launch', 'carnivore://open']), { focus: false, toggle: false, links: ['carnivore://open'] });
  assert.deepEqual(handleSecondInstance(undefined), { focus: true, toggle: false, links: [] });
});

t('menu bar icon: create, destroy or keep', () => {
  assert.equal(policy.trayPresenceDecision({ wanted: true, hasTray: false }), 'create');
  assert.equal(policy.trayPresenceDecision({ wanted: false, hasTray: true }), 'destroy');
  assert.equal(policy.trayPresenceDecision({ wanted: true, hasTray: true }), 'keep');
  assert.equal(policy.trayPresenceDecision({ wanted: false, hasTray: false }), 'keep');
});
t('menu bar icon: absent or damaged reads as shown, only the boolean false hides it', () => {
  for (const wanted of [undefined, null, 'false', 0, 'no', {}, []]) {
    assert.equal(policy.trayPresenceDecision({ wanted, hasTray: false }), 'create', String(wanted));
    assert.equal(policy.trayPresenceDecision({ wanted, hasTray: true }), 'keep', String(wanted));
  }
});
t('menu bar icon: the stored choice is read from config.json, absent file and bad JSON read as shown', () => {
  const dir = tmp();
  const cfg = (values) => { const p = path.join(dir, 'config.json'); fs.writeFileSync(p, JSON.stringify({ ui_preferences: { revision: 1, values } })); return p; };
  assert.equal(readMenuBarIcon(cfg({ desktop_menu_bar_icon: false })), false);
  assert.equal(readMenuBarIcon(cfg({ desktop_menu_bar_icon: true })), true);
  assert.equal(readMenuBarIcon(cfg({})), true);
  assert.equal(readMenuBarIcon(path.join(dir, 'missing.json')), true);
  fs.writeFileSync(path.join(dir, 'bad.json'), '{not json');
  assert.equal(readMenuBarIcon(path.join(dir, 'bad.json')), true);
  assert.equal(readMenuBarIcon(null), true);
});
t('tray presence: the facade is stable while the real tray comes and goes, handlers and tooltip survive', () => {
  const made = [];
  class FakeTray {
    constructor() { this.calls = []; this.destroyed = false; made.push(this); }
    setToolTip(x) { this.calls.push(['tip', x]); }
    setImage() { this.calls.push(['image']); }
    setIgnoreDoubleClickEvents(x) { this.calls.push(['ignore', x]); }
    on(e) { this.calls.push(['on', e]); }
    popUpContextMenu() { this.calls.push(['pop']); }
    destroy() { this.destroyed = true; }
  }
  const nativeImage = { createEmpty: () => ({}), createFromPath: () => ({ isEmpty: () => false, setTemplateImage() {} }) };
  const themes = [];
  const presence = createTrayPresence({ Tray: FakeTray, nativeImage, nativeTheme: { on: (e, fn) => themes.push(fn) }, iconPath: '/x/icon.png' });
  presence.facade.setIgnoreDoubleClickEvents(true);
  presence.facade.on('click', () => {});
  presence.facade.setToolTip('Carnivore: syncing');
  presence.facade.popUpContextMenu({});
  assert.equal(made.length, 0, 'no tray yet: every facade call is a no-op');
  assert.equal(presence.tray(), null);
  assert.equal(presence.apply(true), 'create');
  assert.deepEqual(made[0].calls.filter((c) => c[0] !== 'image'), [['tip', 'Carnivore: syncing'], ['ignore', true], ['on', 'click']]);
  assert.equal(presence.apply(true), 'keep');
  assert.equal(presence.tray(), made[0]);
  assert.equal(presence.apply(false), 'destroy');
  assert.equal(made[0].destroyed, true);
  assert.equal(presence.tray(), null);
  presence.facade.setToolTip('after destroy');
  assert.equal(made[0].calls.some((c) => c[1] === 'after destroy'), false);
  assert.equal(presence.apply(undefined), 'create', 'back on after a restart or a pushed change');
  assert.deepEqual(made[1].calls.filter((c) => c[0] === 'tip'), [['tip', 'after destroy']]);
  assert.ok(made[1].calls.some((c) => c[0] === 'on' && c[1] === 'click'), 'the click handler is re-attached');
  themes[0]();
  assert.ok(made[1].calls.filter((c) => c[0] === 'image').length >= 2);
});

t('SOURCE-LEVEL: the Dock is always there and the tray is not built in main', () => {
  const main = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
  const pkg = JSON.parse(fs.readFileSync(path.join(macDir, 'package.json'), 'utf8'));
  assert.equal(/hideFromDock|dock\.hide|createDockLease/.test(main), false);
  assert.match(main, /app\.setActivationPolicy\('regular'\)/);
  assert.equal(main.includes('new Tray('), false, 'the Tray is built in tray-presence.js');
  assert.ok(fs.readFileSync(path.join(macDir, 'tray-presence.js'), 'utf8').includes('new Tray('));
  assert.equal('LSUIElement' in pkg.build.mac.extendInfo, false);
  assert.equal(fs.existsSync(path.join(macDir, 'dock-lease.js')), false);
});
t('SOURCE-LEVEL: the before-quit teardown consults quitPlan, and the new quit row and menu item carry no accelerator', () => {
  const main = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
  assert.match(main, /lifecycle\.quitPlan\(/);
  assert.match(main, /createQuitHandler\(/);
  const footer = fs.readFileSync(path.join(macDir, 'tray-menu', 'model', 'footer.js'), 'utf8');
  assert.match(footer, /act\('quit_stop'[^\n]*\{ sublabel: t\('menubar\.quit_stop_hint'\) \}\)/);
});

const FALLBACK = { width: 1280, height: 860 };
const main1 = { workArea: { x: 0, y: 25, width: 1440, height: 875 } };
const second = { workArea: { x: 1440, y: 0, width: 1920, height: 1080 } };
t('window state: a rectangle on a connected display survives, including one fully on the second display', () => {
  assert.deepEqual(fitToDisplays({ x: 100, y: 100, width: 900, height: 600 }, [main1, second], FALLBACK), { x: 100, y: 100, width: 900, height: 600 });
  assert.deepEqual(fitToDisplays({ x: 1600, y: 50, width: 800, height: 700 }, [main1, second], FALLBACK), { x: 1600, y: 50, width: 800, height: 700 });
});
t('window state: after the second monitor is unplugged the saved place is dropped for the default size', () => {
  assert.deepEqual(fitToDisplays({ x: 1600, y: 50, width: 800, height: 700 }, [main1], FALLBACK), FALLBACK);
});
t('window state: an oversize window is clamped to its display and kept on it', () => {
  assert.deepEqual(fitToDisplays({ x: -300, y: 0, width: 3000, height: 2000 }, [main1], FALLBACK), { x: 0, y: 25, width: 1440, height: 875 });
});
t('window state: junk saved values fall back', () => {
  for (const saved of [null, undefined, {}, { x: 'a', y: 0, width: 800, height: 600 }, { x: 0, y: 0, width: 50, height: 50 }, { x: NaN, y: 0, width: 800, height: 600 }]) {
    assert.deepEqual(fitToDisplays(saved, [main1], FALLBACK), FALLBACK);
  }
});
t('window state: saved debounced on move and resize, flushed on close, mode 0600, other keys kept; a corrupt file is ignored', () => {
  const dir = tmp();
  const timers = []; const fakeClock = { setTimeout: (fn) => { timers.push(fn); return timers.length; }, clearTimeout: () => {} };
  const ws = createWindowState({ dir: () => dir, key: 'main', getDisplays: () => [main1], timers: fakeClock });
  fs.writeFileSync(path.join(dir, STATE_FILE), JSON.stringify({ version: 1, windows: { other: { x: 1, y: 2, width: 300, height: 300 } } }));
  const handlers = {};
  const win = {
    on: (e, fn) => { handlers[e] = fn; }, isDestroyed: () => false, isMaximized: () => true, isFullScreen: () => false,
    getNormalBounds: () => ({ x: 120, y: 130, width: 1000, height: 700 }),
  };
  ws.track(win);
  handlers.resize(); handlers.move();
  assert.equal(ws.load(), null, 'nothing is written until the quiet time passes');
  timers.at(-1)();
  assert.deepEqual(ws.load(), { x: 120, y: 130, width: 1000, height: 700, maximized: true, fullScreen: false });
  assert.equal(fs.statSync(path.join(dir, STATE_FILE)).mode & 0o777, 0o600);
  assert.ok(JSON.parse(fs.readFileSync(path.join(dir, STATE_FILE), 'utf8')).windows.other, 'another window key is kept');
  assert.deepEqual(ws.bounds(FALLBACK), { x: 120, y: 130, width: 1000, height: 700 });
  fs.writeFileSync(path.join(dir, STATE_FILE), '{corrupt');
  assert.equal(ws.load(), null);
  assert.deepEqual(ws.bounds(FALLBACK), FALLBACK);
  handlers.close();
  assert.equal(ws.load().width, 1000, 'close flushes and a corrupt file is replaced');
});

t('quit notice: the once-flag is written (0600) BEFORE the dialog opens, and the body is the survives-quit wording', async () => {
  const dir = tmp();
  const seen = [];
  const dialog = { showMessageBox: async (o) => { seen.push({ o, flagThere: fs.existsSync(path.join(dir, NOTICE_FLAG)) }); } };
  const catalog = { 'desktop.quit_notice.title': 'T', 'desktop.quit_notice.body': 'B', 'desktop.quit_notice.ok': 'ok' };
  const make = () => createQuitNotice({ dir: () => dir, dialog, loadTranslator: async () => (k) => catalog[k] });
  const notice = make();
  assert.equal(notice.alreadyShown(), false);
  await notice.show();
  assert.equal(seen[0].flagThere, true);
  assert.equal(seen[0].o.detail, 'B');
  assert.deepEqual(seen[0].o.buttons, ['ok']);
  assert.equal(fs.statSync(path.join(dir, NOTICE_FLAG)).mode & 0o777, 0o600);
  assert.equal(make().alreadyShown(), true);
});

t('a launch whose engine start was refused opens no window, whatever else says open', () => {
  assert.equal(policy.launchDecision({ argv: ['x'], windowAtLogin: false, startBlocked: true }).openWindow, false);
  assert.equal(policy.launchDecision({ argv: ['x', '--login-launch'], windowAtLogin: true, startBlocked: true }).openWindow, false);
  assert.equal(policy.launchDecision({ argv: ['x'], windowAtLogin: false }).openWindow, true);
});

for (const [name, fn] of queue) {
  await fn();
  console.log(`ok - ${name}`);
}
console.log(`${queue.length} passed`);
