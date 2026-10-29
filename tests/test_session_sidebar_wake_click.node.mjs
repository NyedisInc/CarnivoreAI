import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (name) => fs.readFileSync(path.join(__dirname, '..', 'client', 'js', name), 'utf8');
const WAKE = read('session-sidebar-wake-click.js');
const RESTART_CLICK = read('session-sidebar-restart-click.js');
const CLICKS = read('session-sidebar-clicks.js');
const SLEEP = read('session-row-menu-sleep.js');

function el(name, asleep) {
  return { dataset: asleep ? { name, asleep: '1' } : { name, sessionId: 'ses_1' } };
}

function load({ wake, pick = null, liveAfterWake = true } = {}) {
  const calls = { wake: [], picker: [], open: [], focus: [], getSession: 0, adopt: 0, say: [] };
  let gen = 0;
  const ctrl = {
    _rows: [{ name: 'carnivore_a', asleep: true, session_uuid: 'u-a', label: 'a' }],
    _lastSig: 'x',
    _closeAfterSwitch() {},
    async _fetchAndRender() {
      if (liveAfterWake && calls.wake.length) {
        ctrl._rows = [{ name: 'carnivore_a', asleep: false, session_uuid: 'u-a', session_id: 'ses_1' }];
        dom = [el('carnivore_a', false)];
      }
    },
  };
  let dom = [el('carnivore_a', true)];
  const window = {
    SessionSidebar: ctrl,
    NavigationGeneration: {
      begin() { gen += 1; return gen; },
      isCurrent(t) { return t === gen; },
      keep(t) { return t === gen; },
      current() { return gen; },
    },
    WakeFocus: { afterWake(uuid, nav) { calls.focus.push([uuid, typeof nav]); } },
    SessionRowMenuActions: { say(_c, text) { calls.say.push(text); } },
    SessionRestartPicker: {
      async open(...args) { calls.picker.push(args); return pick; },
      lastError() { return ''; },
    },
    API: {
      async wakeSession(uuid, agentType) { calls.wake.push([uuid, agentType]); return wake(uuid, agentType); },
      async getSession() { calls.getSession += 1; return null; },
      async adoptSession() { calls.adopt += 1; return {}; },
    },
    addEventListener() {},
    dispatchEvent() {},
  };
  const document = { querySelectorAll: () => dom };
  const globalThis_ = {
    CloudeI18n: { t: (k) => k },
  };
  const ctx = { alert(msg) { throw new Error('unexpected alert: ' + msg); }, window, document, console: { log() {}, warn() {}, error() {}, debug() {} }, globalThis: globalThis_, CustomEvent: class {} };
  vm.createContext(ctx);
  for (const src of [SLEEP, WAKE, RESTART_CLICK, CLICKS]) vm.runInContext(src, ctx);
  window.SessionSidebarWakeClick = window.SessionSidebarWakeClick || globalThis_.SessionSidebarWakeClick;
  const open = async (c, rowEl) => { calls.open.push(rowEl.dataset.name); };
  return { ctx, window, ctrl, calls, open, bump: () => { gen += 1; }, rowEl: () => dom[0] };
}

let passed = 0;
let failed = 0;
async function test(name, fn) {
  try { await fn(); passed += 1; } catch (err) { failed += 1; console.error(`FAIL ${name}\n`, err); }
}

const STARTED = () => ({ status: 'started' });

await test('a drawer row click on an asleep row calls nothing (it arms its own wake button in the shell)', async () => {
  const t = load({ wake: STARTED });
  await t.window.SessionSidebarClicks.activateRow(t.ctrl, t.rowEl());
  assert.equal(t.calls.wake.length, 0);
  assert.equal(t.calls.getSession, 0);
  assert.equal(t.calls.adopt, 0);
});

await test('a click wakes by session_uuid, then WakeFocus brings the live row forward', async () => {
  const t = load({ wake: STARTED });
  const attempted = await t.window.SessionSidebarWakeClick.onAsleepClick(t.ctrl, t.rowEl(), t.open);
  assert.equal(attempted, true);
  assert.deepEqual(t.calls.wake, [['u-a', undefined]]);
  assert.deepEqual(t.calls.focus, [['u-a', 'number']]);
  assert.deepEqual(t.calls.open, []);
  assert.equal(t.calls.picker.length, 0);
});

await test('wrapper_needed opens the wrapper picker and wakes with the pick', async () => {
  const t = load({
    pick: { agentType: 'claude-wrapped' },
    wake: (_u, agentType) => (agentType ? { status: 'started' }
      : { status: 'refused', code: 'wrapper_needed', wrapper_options: ['claude-wrapped'] }),
  });
  await t.window.SessionSidebarWakeClick.onAsleepClick(t.ctrl, t.rowEl(), t.open);
  assert.equal(t.calls.picker.length, 1);
  assert.equal(t.calls.picker[0][3], 'u-a');
  assert.deepEqual(t.calls.wake, [['u-a', undefined], ['u-a', 'claude-wrapped']]);
  assert.deepEqual(t.calls.focus, [['u-a', 'number']]);
});

await test('a cancelled wrapper picker wakes nothing and opens nothing', async () => {
  const t = load({ pick: null, wake: () => ({ status: 'refused', code: 'wrapper_needed' }) });
  await t.window.SessionSidebarWakeClick.onAsleepClick(t.ctrl, t.rowEl(), t.open);
  assert.equal(t.calls.wake.length, 1);
  assert.equal(t.calls.open.length, 0);
});

await test('a refused wake opens nothing and says why', async () => {
  const t = load({ wake: () => ({ status: 'refused', detail: 'no transcript' }) });
  await t.window.SessionSidebarWakeClick.onAsleepClick(t.ctrl, t.rowEl(), t.open);
  assert.equal(t.calls.open.length, 0);
  assert.equal(t.calls.say.length, 1);
});

await test('a navigation during the wake is not overridden', async () => {
  let t;
  t = load({ wake: () => { t.bump(); return { status: 'started' }; } });
  await t.window.SessionSidebarWakeClick.onAsleepClick(t.ctrl, t.rowEl(), t.open);
  assert.equal(t.calls.wake.length, 1);
  assert.equal(t.calls.open.length, 0);
});

await test('a double click wakes once', async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  const t = load({ wake: async () => { await gate; return { status: 'started' }; } });
  const first = t.window.SessionSidebarWakeClick.onAsleepClick(t.ctrl, t.rowEl(), t.open);
  const second = t.window.SessionSidebarWakeClick.onAsleepClick(t.ctrl, t.rowEl(), t.open);
  release();
  await Promise.all([first, second]);
  assert.equal(t.calls.wake.length, 1);
});

console.log(`${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
