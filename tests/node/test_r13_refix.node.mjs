import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const macDir = path.join(import.meta.dirname, '..', '..', 'macOS');
const REPORT = { setup_status: 'complete', joined: false, bind: { restart_required: true }, rebind_requested: false };

function freshRebind() {
  const p = require.resolve(path.join(macDir, 'rebind-after-pair.js'));
  delete require.cache[p];
  return require(p);
}

test('guard: a stop flag that never resets still blocks the guard, and the holder check never runs during a stop', async () => {
  const lifecycle = require(path.join(macDir, 'engine', 'engine-lifecycle.js'));
  const realVerify = lifecycle.verifyEngineHolder;
  lifecycle.verifyEngineHolder = async () => ({ reason: 'unknown', holder: null });
  try {
    const wirePath = require.resolve(path.join(macDir, 'window-guard-wire.js'));
    delete require.cache[wirePath];
    const { wireWindowGuard } = require(wirePath);
    const manager = { stopRequested: true, getPort: () => 8000, getHealth: async () => null, startBlockedReason: null };
    const g = wireWindowGuard({ getManager: () => manager, refreshTray: () => {}, reload: () => {} });
    await g.onHealth(true, { uptime: 5 });
    assert.equal(manager.startBlockedReason, null, 'our own stop never raises a holder refusal');
    await g.onStopped();
    assert.equal(g.isBlocked(), true, 'the outage blocks window requests');
  } finally { lifecycle.verifyEngineHolder = realVerify; }
});

test('main.js: the first window waits for the settle, then stays closed when the start was refused', () => {
  const src = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
  const body = src.slice(src.indexOf('function openWindowForThisLaunch'));
  const settle = body.indexOf('settleBeforeFirstWindow');
  const blocked = body.indexOf('serverManager.startBlockedReason', settle);
  const open = body.indexOf('appWindow.open()', settle);
  assert.ok(settle > 0 && blocked > settle && open > blocked, 'settle, then the refusal check, then open');
});

test('settle: a service-owned or adopted engine is not restarted before the first window', async () => {
  for (const extra of [{ serviceOwnsEngine: () => true, ownedProcess: true }, { serviceOwnsEngine: () => false, ownedProcess: false }]) {
    const mod = freshRebind();
    let restarts = 0;
    const deps = {
      serverManager: { getBindReport: () => REPORT, restart: async () => { restarts++; return { refused: true }; }, ...extra },
      offerTakeOwnership: async () => { throw new Error('modal before the window'); },
      reportStartFailure: async () => {}, waitForServerHealth: async () => true,
    };
    assert.equal(await mod.settleBeforeFirstWindow(deps), false);
    assert.equal(restarts, 0);
  }
});
