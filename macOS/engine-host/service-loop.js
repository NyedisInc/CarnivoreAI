'use strict';

const { decideVersionAction } = require('./version-guard');
const { adoptionReplaced, holdsEngine } = require('./owned-stop');
const { isForeignHolderRefusal } = require('./holder-refusal');

const MAX_START_FAILURES = 5;
const START_FAILURE_FILE = 'engine-service-start-failures.json';
const START_FAILURE_WINDOW_MS = 30 * 60 * 1000;
const HEALTH_WAIT_MS = 60000;
const HEALTH_POLL_MS = 1000;
const REPLACE_BACKOFF_MS = 60 * 1000;
const MISMATCH_RELOG_MS = 10 * 60 * 1000;

function createServiceLoop({ manager, running, readDisk, guard, decideRebind, stopEngine, startGuard, getApi = () => null, exit, log = () => {}, now = () => Date.now(),
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)), healthWaitMs = HEALTH_WAIT_MS }) {
  let rebindAt = null;
  let held = false;
  let cleared = false;
  let waiting = null;

  async function healthAnswers() {
    for (let waited = 0; waited <= healthWaitMs; waited += HEALTH_POLL_MS) {
      if (await manager.getHealth()) return true;
      if (manager.getState() === 'stopped') return false;
      await sleep(HEALTH_POLL_MS);
    }
    return false;
  }

  function failStart(reason) {
    const count = startGuard.record(running);
    log(`[engine-service] engine start failed (${count} of ${MAX_START_FAILURES}): ${reason}`);
    if (count >= MAX_START_FAILURES) { exit(0); return 'exit-start-failures'; }
    return 'ok';
  }

  return {
    async tick() {
      const disk = readDisk();
      const action = decideVersionAction({ running, disk, guard });
      if (action === 'restart') {
        const count = guard.record(disk);
        log(`[engine-service] bundle on disk is ${disk}, running ${running}: stopping the engine and exiting for a restart (${count})`);
        try {
          const result = await stopEngine();
          if (result && result.stopped === false) log(`[engine-service] engine not stopped before the update restart (${result.outcome}): ${result.error || 'no detail'}`);
        } catch (err) {
          log(`[engine-service] engine stop before the update restart failed: ${err.message}`);
        }
        exit(1);
        return 'exit-for-update';
      }
      if (action === 'hold') {
        if (!held) log(`[engine-service] bundle on disk is ${disk}, running ${running}: restart bound spent, holding still`);
        held = true;
        return 'hold';
      }
      if (disk && !cleared) { guard.clear(); cleared = true; }

      if (manager.getState() === 'stopped' || !(await manager.engineIsUp())) {
        if (!startGuard.allow(running)) {
          log('[engine-service] engine start failures bound spent: exiting 0 and staying down');
          exit(0);
          return 'exit-start-failures';
        }
        if (waiting && now() < waiting.retryAt) return 'ok';
        try {
          await manager.start();
          waiting = null;
          if (await healthAnswers()) {
            startGuard.clear();
            return 'started';
          }
          return failStart('the engine did not answer health after it was started');
        } catch (err) {
          if (isForeignHolderRefusal(err)) {
            const key = err.code === 'ADOPTION_REFUSED' ? `${String(err.outcome)} (holder pid ${err.pid || 'unknown'})` : err.message;
            const at = now();
            if (!waiting || waiting.key !== key || at - waiting.loggedAt >= MISMATCH_RELOG_MS) {
              const port = err.port || (typeof manager.getPort === 'function' ? manager.getPort() : 'unknown');
              log(`[engine-service] port ${port} is held by a process that is not ours (${key}): not stopping it; waiting, retrying about once a minute (the window asks the owner)`);
              waiting = { key, loggedAt: at, retryAt: at + REPLACE_BACKOFF_MS };
            } else waiting.retryAt = at + REPLACE_BACKOFF_MS;
            return 'ok';
          }
          return failStart(err.message);
        }
      }

      const health = await manager.getHealth();
      if (adoptionReplaced(manager, health)) {
        log(`[engine-service] the adopted engine (${manager.adoptedVersion}) was replaced by one reporting ${String(health.version)}: dropping the adoption, leaving the port holder alone`);
        manager.adoptedVersion = null;
        manager.state = 'stopped';
        return 'ok';
      }
      const verdict = decideRebind(manager.getBindReport(), { attempted: rebindAt !== null, attemptAt: rebindAt, now: now() });
      if (verdict === 'restart') {
        rebindAt = now();
        log('[engine-service] first-run rebind: restarting the engine once onto its configured address');
        try {
          const result = await manager.restart();
          if (result && result.refused) {
            if (await holdsEngine(manager)) await manager.restartAdoptedEngine({ getApi: getApi });
            else log('[engine-service] first-run rebind: the engine on the port is not the one this service adopted; not stopping it');
          }
        } catch (err) {
          log(`[engine-service] rebind restart failed: ${err.message}`);
        }
        return 'rebind';
      }
      return 'ok';
    },
  };
}

module.exports = { REPLACE_BACKOFF_MS, MISMATCH_RELOG_MS, MAX_START_FAILURES, START_FAILURE_FILE, START_FAILURE_WINDOW_MS, createServiceLoop };
