import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const root = path.join(import.meta.dirname, '..', '..');
const macDir = path.join(root, 'macOS');
const require = createRequire(import.meta.url);
const { createWindowGuard } = require(path.join(macDir, 'window-guard.js'));

function launch(verdicts, healthy) {
  const seen = { loads: 0, cancelled: 0, reloads: 0, checks: 0 };
  let before;
  const session = { webRequest: { onBeforeRequest: (fn) => { before = fn; }, onErrorOccurred: () => {} } };
  const guard = createWindowGuard({
    getPort: () => 8000,
    verifyHolder: async () => { seen.checks += 1; return verdicts.length > 1 ? verdicts.shift() : verdicts[0]; },
    onRefused: () => {}, onCleared: () => {}, reloadWindows: () => { seen.reloads += 1; },
    probe: async () => healthy(),
  });
  guard.attach(session, 'http://127.0.0.1:8000');
  const load = () => { seen.loads += 1; before({ url: 'http://127.0.0.1:8000/' }, (r) => { if (r.cancel) seen.cancelled += 1; }); };
  return { guard, seen, load };
}

test('first launch: the engine answered, so the first window load runs at once and is never cancelled', async () => {
  const t = launch([null], () => ({ uptime: 3 }));
  await t.guard.onHealth(false);
  assert.equal(t.guard.isBlocked(), true);
  t.guard.whenClear(t.load);
  await new Promise((r) => setImmediate(r));
  assert.deepEqual({ loads: t.seen.loads, cancelled: t.seen.cancelled, reloads: t.seen.reloads }, { loads: 1, cancelled: 0, reloads: 0 });
  assert.equal(t.seen.checks, 1, 'the same holder check ran once');
});

test('first launch: a stranger on the port gets no window load, ours arriving later releases it', async () => {
  let up = { uptime: 1 };
  const t = launch([{ reason: 'not_yours', holder: { pid: 9, uid: 0 } }, null], () => up);
  await t.guard.onHealth(false);
  t.guard.whenClear(t.load);
  await new Promise((r) => setImmediate(r));
  assert.equal(t.seen.loads, 0, 'refused holder: the load never runs');
  assert.equal(t.guard.isBlocked(), true);
  await t.guard.onHealth(true, up);
  assert.deepEqual({ loads: t.seen.loads, cancelled: t.seen.cancelled }, { loads: 1, cancelled: 0 });
});

const { openWindowAfterStart } = require(path.join(macDir, 'tray-menu', 'actions', 'open-after-start.js'));

function ctxFor({ open = false, healthyAfter = 2, blocked = null }) {
  let polls = 0; const ctx = { opened: 0 };
  ctx.serverManager = { startBlockedReason: blocked, getHealth: async () => { polls += 1; return polls >= healthyAfter ? { ok: 1 } : null; } };
  ctx.appWindow = { isOpen: () => open || ctx.opened > 0, open: () => { ctx.opened += 1; } };
  return ctx;
}
const nap = { sleep: async () => {} };

test('tray Start Server: opens the window once when none is open and the engine answers', async () => {
  const ctx = ctxFor({});
  assert.equal(await openWindowAfterStart(ctx, nap), true);
  assert.equal(await openWindowAfterStart(ctx, nap), false, 'a second call finds the window open');
  assert.equal(ctx.opened, 1);
});

test('tray Start Server: no new window with one open, after a refusal, or when the engine never answers', async () => {
  const open = ctxFor({ open: true }); await openWindowAfterStart(open, nap); assert.equal(open.opened, 0);
  const refused = ctxFor({ blocked: 'holder-not_yours' }); await openWindowAfterStart(refused, nap); assert.equal(refused.opened, 0);
  const dead = ctxFor({ healthyAfter: Infinity }); await openWindowAfterStart(dead, { ...nap, timeoutMs: 5000, pollMs: 500 }); assert.equal(dead.opened, 0);
});

test('tray Start Server: the window opens only after the rebind settle (the one restart) finishes (#2523)', async () => {
  const ctx = ctxFor({}); const order = [];
  ctx.rebindDeps = () => ({}); ctx.rebindAfterPair = { settleBeforeFirstWindow: async () => { order.push('settle'); } };
  const open = ctx.appWindow.open; ctx.appWindow.open = () => { order.push('open'); open(); };
  assert.equal(await openWindowAfterStart(ctx, nap), true);
  assert.deepEqual(order, ['settle', 'open']);
  const refused = ctxFor({}); refused.rebindDeps = () => ({});
  refused.rebindAfterPair = { settleBeforeFirstWindow: async () => { refused.serverManager.startBlockedReason = 'holder-foreign'; } };
  assert.equal(await openWindowAfterStart(refused, nap), false, 'a restart refused during the settle opens no window');
});

test('tray Start Server click calls it, and no other start path does', async () => {
  const fs = await import('node:fs');
  const click = fs.readFileSync(path.join(macDir, 'tray-menu', 'actions', 'server.js'), 'utf8');
  assert.match(click, /'server\.start': async \(\) => \{[\s\S]*openWindowAfterStart\(ctx\)/);
  for (const f of ['server-manager.js', 'main.js', 'supervisor-policy.js']) {
    assert.doesNotMatch(fs.readFileSync(path.join(macDir, f), 'utf8'), /open-after-start|openWindowAfterStart/, f);
  }
});

test('stale-bind wait words print the port as plain digits', async () => {
  const { engineInUse } = require(path.join(macDir, 'engine', 'port-settle.js'));
  const { loadTranslator } = require(path.join(macDir, 'tray-menu', 'strings.js'));
  const t = await loadTranslator(path.join(root, 'client'));
  let words = null; let n = 0;
  const manager = { state: 'stopped', engineIsUp: async () => true, getHealth: async () => null, isPortInUse: async () => { n += 1; return n < 3; },
    onStartNote: (note) => { words = t(note.key, note.params); } };
  let clock = 0;
  await engineInUse(manager, 8000, { sleep: async (ms) => { clock += ms; }, now: () => clock, hasListener: async () => false });
  assert.equal(words, 'waiting for port 8000 to free up');
});

test('window host wiring: the main window first load waits on the guard and runs once when it clears', async () => {
  const Module = (await import('node:module')).default;
  const loaded = [];
  class FakeWindow {
    constructor() { this.webContents = { on() {}, send() {}, setWindowOpenHandler() {}, session: { setPermissionRequestHandler() {}, setPermissionCheckHandler() {} } }; }
    once() {} on() {} isDestroyed() { return false; } isMinimized() { return false; } show() {} focus() {} restore() {}
    loadURL(u) { loaded.push(u); }
  }
  const electron = { BrowserWindow: FakeWindow, shell: { openExternal() {} } };
  const realLoad = Module._load;
  Module._load = function (request, ...rest) { return request === 'electron' ? electron : realLoad.call(this, request, ...rest); };
  let hostMod;
  try {
    const p = require.resolve(path.join(macDir, 'window-host.js'));
    delete require.cache[p];
    hostMod = require(p);
  } finally { Module._load = realLoad; }
  let release = null;
  const guard = { attach() {}, whenClear: (fn) => { release = fn; } };
  const host = hostMod.createWindowHost({ getUrl: () => 'http://127.0.0.1:8000', guard });
  assert.equal(host.open(), true);
  assert.deepEqual(loaded, [], 'a blocked guard: the window has not navigated');
  release();
  assert.deepEqual(loaded, ['http://127.0.0.1:8000']);
});
