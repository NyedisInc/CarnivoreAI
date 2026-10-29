import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const macDir = path.join(import.meta.dirname, '..', '..', 'macOS');
const { createWindowGuard } = require(path.join(macDir, 'window-guard.js'));

function setup(verdicts) {
  const seen = { refused: [], cleared: 0, reloads: 0, checks: 0 };
  let before = null;
  let errored = null;
  const session = { webRequest: { onBeforeRequest: (fn) => { before = fn; }, onErrorOccurred: (fn) => { errored = fn; } } };
  const guard = createWindowGuard({
    getPort: () => 8000,
    verifyHolder: async () => { seen.checks += 1; return verdicts.length > 1 ? verdicts.shift() : verdicts[0]; },
    onRefused: (r) => seen.refused.push(r), onCleared: () => { seen.cleared += 1; }, reloadWindows: () => { seen.reloads += 1; },
  });
  guard.attach(session, 'http://127.0.0.1:8000');
  const cancelled = (url) => { let out; before({ url }, (r) => { out = r.cancel; }); return out; };
  return { guard, seen, cancelled, fail: (url, error) => errored({ url, error }) };
}

test('a foreign holder after an outage gets no request, and our engine returning lifts the block', async () => {
  const t = setup([{ reason: 'not_yours', holder: { pid: 9, uid: 0 } }, { reason: 'unknown', holder: null }, null]);
  assert.equal(t.cancelled('http://127.0.0.1:8000/api/v1/auth/refresh'), false, 'healthy engine: requests pass');
  await t.guard.onHealth(false);
  assert.equal(t.cancelled('http://127.0.0.1:8000/api/v1/auth/refresh'), true);
  assert.equal(t.cancelled('ws://127.0.0.1:8000/ws/events'), true);
  assert.equal(t.cancelled('http://localhost:8000/'), true);
  assert.equal(t.cancelled('https://example.com/'), false, 'other sites are not the engine');
  await t.guard.onHealth(true, { uptime: 1 });
  assert.equal(t.seen.refused.length, 1);
  assert.equal(t.cancelled('http://127.0.0.1:8000/api/v1/auth/refresh'), true, 'still blocked after the answer');
  await t.guard.onHealth(true, { uptime: 3 });
  assert.equal(t.seen.refused.length, 1, 'the refusal is told once per episode');
  assert.equal(t.seen.reloads, 0);
  await t.guard.onHealth(true, { uptime: 5 });
  assert.equal(t.cancelled('http://127.0.0.1:8000/api/v1/auth/refresh'), false);
  assert.equal(t.seen.cleared, 1);
  assert.equal(t.seen.reloads, 1, 'the page may have come from the stranger: reload once');
});

test('a same-user holder behaves as today: no refusal, no reload, one check per transition', async () => {
  const t = setup([null]);
  await t.guard.onHealth(true, { uptime: 10 });
  await t.guard.onHealth(true, { uptime: 25 });
  for (let i = 0; i < 50; i++) t.cancelled('http://127.0.0.1:8000/api/v1/sessions/list');
  assert.equal(t.seen.checks, 2, 'one check per healthy poll, none per request');
  await t.guard.onHealth(false);
  await t.guard.onHealth(false);
  await t.guard.onHealth(true, { uptime: 1 });
  assert.equal(t.cancelled('http://127.0.0.1:8000/'), false);
  await t.guard.onHealth(true, { uptime: 16 });
  assert.equal(t.seen.checks, 4);
  assert.deepEqual([t.seen.refused.length, t.seen.cleared, t.seen.reloads], [0, 0, 0]);
});

test('a down that lands while a check is running keeps the block; a refused connection and an uptime reset are outages', async () => {
  const t = setup([null]);
  let release;
  t.guard.noteDown();
  const slow = new Promise((r) => { release = r; });
  const guard2 = (() => {
    const s = { webRequest: { onBeforeRequest(fn) { s.fn = fn; }, onErrorOccurred() {} } };
    const g = createWindowGuard({ getPort: () => 8000, verifyHolder: async () => { await slow; return null; },
      onRefused() {}, onCleared() {}, reloadWindows() {} });
    g.attach(s, 'http://127.0.0.1:8000');
    return { g, s };
  })();
  guard2.g.noteDown();
  const pending = guard2.g.onHealth(true, { uptime: 1 });
  guard2.g.noteDown();
  release();
  await pending;
  assert.equal(guard2.g.isBlocked(), true, 'a stale pass cannot unblock');
  t.fail('http://127.0.0.1:8000/ws/events', 'net::ERR_BLOCKED_BY_CLIENT');
  assert.equal(t.guard.isBlocked(), true);
  const u = setup([null]);
  await u.guard.onHealth(true, { uptime: 500 });
  await u.guard.onHealth(true, { uptime: 2 });
  assert.equal(u.seen.checks, 2);
  const e = setup([null]);
  e.fail('http://127.0.0.1:8000/ws/events', 'net::ERR_CONNECTION_REFUSED');
  assert.equal(e.cancelled('http://127.0.0.1:8000/'), true);
  const o = setup([null]);
  o.fail('http://127.0.0.1:8000/', 'net::ERR_BLOCKED_BY_CLIENT');
  assert.equal(o.cancelled('http://127.0.0.1:8000/'), false);
});

test('a stranger that takes the port with no failed poll and a body that looks fine is caught on the next healthy poll', async () => {
  const t = setup([null, { reason: 'not_yours', holder: { pid: 9, uid: 0 } }, null]);
  await t.guard.onHealth(true, { uptime: 100 });
  for (const body of [{}, 'ok', { uptime: 900 }]) {
    const u = setup([{ reason: 'not_yours', holder: { pid: 9, uid: 0 } }]);
    await u.guard.onHealth(true, body);
    assert.equal(u.cancelled('http://127.0.0.1:8000/api/v1/auth/refresh'), true, `body ${JSON.stringify(body)} blocks`);
    assert.equal(u.seen.refused.length, 1);
  }
  await t.guard.onHealth(true, { uptime: 115 });
  assert.equal(t.cancelled('http://127.0.0.1:8000/api/v1/auth/refresh'), true);
  await t.guard.onHealth(true, { uptime: 117 });
  assert.equal(t.cancelled('http://127.0.0.1:8000/api/v1/auth/refresh'), false);
  assert.equal(t.seen.reloads, 1);
});

test('a clean unblock reloads the windows when a page load was cancelled while blocked', async () => {
  const t = setup([null]);
  await t.guard.onHealth(false);
  assert.equal(t.cancelled('http://127.0.0.1:8000/'), true);
  await t.guard.onHealth(true, { uptime: 1 });
  assert.equal(t.cancelled('http://127.0.0.1:8000/'), false);
  assert.equal(t.seen.reloads, 1, 'the cancelled page would stay on the error page');
  assert.equal(t.seen.cleared, 0, 'no refusal to clear');
  const q = setup([null]);
  await q.guard.onHealth(false);
  await q.guard.onHealth(true, { uptime: 1 });
  assert.equal(q.seen.reloads, 0, 'nothing was cancelled: no reload');
});

test('the wired guard cannot stop the poll, and its refusal does not stop the supervisor', async () => {
  const { wireWindowGuard } = require(path.join(macDir, 'window-guard-wire.js'));
  const manager = { getPort: () => 5081, startBlockedReason: null, getHealth: async () => ({ uptime: 1 }) };
  const guard = wireWindowGuard({ getManager: () => manager, refreshTray: () => { throw new Error('tray boom'); }, reload: () => {} });
  guard.noteDown();
  guard.attach({ webRequest: { onBeforeRequest() {}, onErrorOccurred() {} } }, 'http://127.0.0.1:5081');
  const warn = console.warn; console.warn = () => {};
  try { await guard.onHealth(true, { uptime: 1 }); await guard.onStopped(); } finally { console.warn = warn; }
  const sm = fs.readFileSync(path.join(macDir, 'server-manager.js'), 'utf8');
  assert.match(sm, /this\.startBlockedReason !== this\.startBlockedByGuard/);
});

test('every window session is attached to the guard and main.js feeds it health', () => {
  assert.match(fs.readFileSync(path.join(macDir, 'window-host.js'), 'utf8'), /guard\.attach\(wc\.session, origin\)/);
  const main = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
  assert.match(main, /windowGuard\.onHealth\(Boolean\(health\), health\)/);
  assert.match(main, /guard: windowGuard/);
  assert.match(fs.readFileSync(path.join(macDir, 'window-guard-wire.js'), 'utf8'), /verifyEngineHolder\(getManager\(\)\)/);
});
