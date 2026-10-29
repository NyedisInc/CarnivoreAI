'use strict';

const { createWindowGuard } = require('./window-guard');
const { verifyEngineHolder } = require('./engine/engine-lifecycle');
const portTrust = require('./tray-menu/port-trust');

const BLOCKED_POLL_MS = 2000;

function wireWindowGuard({ getManager, refreshTray, reload }) {
  const guard = createWindowGuard({
    getPort: () => getManager().getPort(),
    verifyHolder: () => verifyEngineHolder(getManager()),
    onRefused: (refusal) => {
      const manager = getManager();
      console.warn(`[window-guard] ${portTrust.holderError(refusal, manager.getPort()).message}`);
      if (!manager.startBlockedReason) {
        manager.startBlockedReason = `holder-${refusal.reason}`;
        manager.startBlockedByGuard = manager.startBlockedReason;
      }
      refreshTray();
    },
    onCleared: () => {
      const manager = getManager();
      if (manager.startBlockedByGuard && manager.startBlockedReason === manager.startBlockedByGuard) manager.startBlockedReason = null;
      manager.startBlockedByGuard = null;
      refreshTray();
    },
    reloadWindows: reload,
    probe: () => getManager().getHealth(),
    log: (message) => console.log(message),
  });
  const safely = async (fn) => {
    try { await fn(); } catch (err) { console.warn('[window-guard] check failed:', err && err.message); }
  };
  return {
    ...guard,
    onHealth: (healthy, body) => (getManager().stopRequested ? Promise.resolve() : safely(() => guard.onHealth(healthy, body))),
    fastPoll: (state) => guard.isBlocked() && state !== 'stopped',
    onStopped: () => safely(async () => {
      if (getManager().stopRequested) { if (!guard.isBlocked()) guard.noteDown(); return; }
      if (!guard.isBlocked()) { guard.noteDown(); return; }
      const health = await getManager().getHealth();
      await guard.onHealth(Boolean(health), health);
    }),
    interval: BLOCKED_POLL_MS,
  };
}

module.exports = { wireWindowGuard };
