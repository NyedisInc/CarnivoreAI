'use strict';

const { REPLACE_BACKOFF_MS } = require('./engine-host/service-loop');
const { isForeignHolderRefusal } = require('./engine-host/holder-refusal');

function createSlowRetry(manager, { intervalMs = REPLACE_BACKOFF_MS, log = (msg) => console.log(msg) } = {}) {
  let timer = null;

  async function fire() {
    timer = null;
    if (manager.quitting || manager.stopRequested || manager.state === 'running' || manager.serviceOwnsEngine()) return;
    try {
      await manager.start();
      log('[supervisor] the port is free again: our engine started');
      manager.supervisor.recordUp();
    } catch (err) {
      if (isForeignHolderRefusal(err)) arm();
      else log(`[supervisor] slow retry stopped: ${err && err.message}`);
    }
  }

  function arm() {
    if (timer) return;
    timer = setTimeout(fire, intervalMs);
    if (timer && typeof timer.unref === 'function') timer.unref();
  }

  function cancel() {
    if (timer) clearTimeout(timer);
    timer = null;
  }

  function onGaveUp(decision, startError) {
    if (decision.action !== 'gave-up' || !isForeignHolderRefusal(startError)) return;
    log('[supervisor] the port is held by a program that is not ours: not stopping it; checking again about once a minute');
    arm();
  }

  return { onGaveUp, cancel, pending: () => timer !== null };
}

module.exports = { createSlowRetry };
