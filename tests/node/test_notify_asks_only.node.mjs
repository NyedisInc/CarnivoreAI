import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const repo = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const mac = path.join(repo, 'macOS');
const { shouldMirror } = require(path.join(mac, 'banners', 'mirror.js'));
const { createBanners } = require(path.join(mac, 'banners', 'index.js'));
const focus = require(path.join(mac, 'banners', 'focus.js'));
const { registerDesktopSettings } = require(path.join(mac, 'desktop-settings.js'));

const TOASTS = [
  { kind: 'PermissionRequest', ask: 'ses_1', mirrored: true },
  { kind: 'Notification', ask: '', mirrored: false },
  { kind: 'Stop (finished unread)', ask: '', mirrored: false },
];

test('asks-only on: only the toast that names a session is mirrored; off or unreadable: every toast is', () => {
  for (const toast of TOASTS) {
    assert.equal(shouldMirror({ asksOnly: true, askSessionId: toast.ask }), toast.mirrored, toast.kind);
    for (const off of [false, null, undefined, 'true', 1]) assert.equal(shouldMirror({ asksOnly: off, askSessionId: toast.ask }), true, `${toast.kind} with ${String(off)}`);
  }
});

function controller(prefs) {
  const api = { getAuthed: async () => (prefs ? { reachable: true, status: 200, data: { values: prefs }, error: null } : { reachable: false, status: 0, data: null, error: 'down' }) };
  const N = Object.assign(function Fake() {}, { isSupported: () => true });
  return createBanners({ platform: 'darwin', getApi: () => api, Notification: N, readPermission: () => 'unknown', t: (k) => k, isWindowFocused: () => false, openApproval: () => {} });
}

test('mirrorAllowed mirrors only while approval banners are on; asks-only then filters, and an unreadable setting mirrors nothing', async () => {
  const on = controller({ desktop_banners: true, desktop_notify_asks_only: true });
  assert.equal(await on.mirrorAllowed(''), false);
  assert.equal(await on.mirrorAllowed('ses_1'), true);
  assert.equal(await controller({ desktop_banners: true }).mirrorAllowed(''), true);
  for (const prefs of [{}, { desktop_banners: false, desktop_notify_asks_only: false }, null]) {
    assert.equal(await controller(prefs).mirrorAllowed(''), false);
    assert.equal(await controller(prefs).mirrorAllowed('ses_1'), false);
  }
});

test('the Focus pane opens first and the Notifications pane is the fallback; both refused rejects', async () => {
  const opened = [];
  const ok = { openExternal: async (url) => { opened.push(url); } };
  assert.equal(await focus.openFocusSettings(ok), 'focus');
  assert.deepEqual(opened, ['x-apple.systempreferences:com.apple.Focus-Settings.extension']);

  const urls = [];
  const refuseFirst = { openExternal: async (url) => { urls.push(url); if (urls.length === 1) throw new Error('no handler'); } };
  assert.equal(await focus.openFocusSettings(refuseFirst), 'notifications');
  assert.deepEqual(urls, ['x-apple.systempreferences:com.apple.Focus-Settings.extension', 'x-apple.systempreferences:com.apple.Notifications-Settings.extension']);

  await assert.rejects(focus.openFocusSettings({ openExternal: async () => { throw new Error('refused'); } }), /refused/);
});

test('the open-focus-settings channel is gated like the others, ignores any argument and never takes a URL from the page', async () => {
  const handlers = {};
  const opened = [];
  const origin = 'http://127.0.0.1:5001';
  registerDesktopSettings({
    ipcMain: { handle: (channel, fn) => { handlers[channel] = fn; } }, appWindow: { ownsSender: () => true, origin: () => origin },
    app: { isPackaged: false, getAppPath: () => mac }, Notification: { isSupported: () => false }, shell: { openExternal: async (url) => { opened.push(url); } },
    getInstaller: () => null, launchArgs: () => [], dataDir: () => fs.mkdtempSync(path.join(process.env.TMPDIR || '/tmp', 'focus-test-')),
    getServerManager: () => null,
  });
  assert.equal(typeof handlers['carnivore:open-focus-settings'], 'function');
  const frame = { url: `${origin}/` };
  const event = { senderFrame: frame, sender: { mainFrame: frame } };
  assert.equal(await handlers['carnivore:open-focus-settings'](event, 'https://evil.example/'), 'focus');
  assert.deepEqual(opened, [focus.FOCUS_URL]);
  const foreign = { senderFrame: { url: 'https://evil.example/' }, sender: { mainFrame: { url: 'https://evil.example/' } } };
  foreign.senderFrame = foreign.sender.mainFrame;
  assert.equal(await handlers['carnivore:open-focus-settings'](foreign), null);
  assert.equal(opened.length, 1);
  assert.match(fs.readFileSync(path.join(mac, 'app-window-preload.js'), 'utf8'), /openFocusSettings\(\) \{\s*return ipcRenderer\.invoke\('carnivore:open-focus-settings'\);/);
});

test('the permission hint window: waiting only shortly after the request was made, never before it', async () => {
  const perm = (await import('node:module')).createRequire(import.meta.url)(fileURLToPath(new URL('../../macOS/notification-permission.js', import.meta.url)));
  const at = (mtimeMs) => ({ existsSync: () => mtimeMs !== null, statSync: () => ({ mtimeMs }) });
  const now = 1_000_000_000;
  assert.equal(perm.isWaiting({ dir: '/d', fsImpl: at(null), now }), false);
  assert.equal(perm.isWaiting({ dir: '/d', fsImpl: at(now - 60_000), now }), true);
  assert.equal(perm.isWaiting({ dir: '/d', fsImpl: at(now - perm.WAITING_WINDOW_MS - 1), now }), false);
});
