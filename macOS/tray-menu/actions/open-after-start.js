'use strict';

async function openWindowAfterStart(ctx, { timeoutMs = 60000, pollMs = 500, sleep = (ms) => new Promise((r) => setTimeout(r, ms)) } = {}) {
  const { serverManager, appWindow } = ctx;
  if (appWindow.isOpen()) return false;
  for (let waited = 0; waited <= timeoutMs; waited += pollMs) {
    if (serverManager.startBlockedReason) return false;
    if (await serverManager.getHealth()) {
      if (appWindow.isOpen() || serverManager.startBlockedReason) return false;
      if (ctx.rebindAfterPair && ctx.rebindDeps) {
        try {
          await ctx.rebindAfterPair.settleBeforeFirstWindow(ctx.rebindDeps());
        } catch (err) {
          console.warn('[start] settle failed, opening anyway:', err.message);
        }
        if (appWindow.isOpen() || serverManager.startBlockedReason) return false;
      }
      appWindow.open();
      return true;
    }
    await sleep(pollMs);
  }
  return false;
}

module.exports = { openWindowAfterStart };
