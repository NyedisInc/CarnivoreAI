'use strict';
const { verifyEngineHolder } = require('../../engine/engine-lifecycle');

const NAME = 'launchd-agent';
const SURVIVES_QUIT = true;
const MAX_VERSION_CHARS = 64;
const WAIT_MS = 45000;

async function start(manager, ctx) {
  const { service, log, sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)), waitMs = WAIT_MS, verifyHolder = verifyEngineHolder, kickstartGuard = null } = ctx;
  if (service && service.isEnabled()) {
    const health = await manager.getHealth();
    const stale = Boolean(health) && Boolean(health.version) && health.version !== manager.getBundleVersion();
    const usableVersion = stale && typeof health.version === 'string' && health.version.length <= MAX_VERSION_CHARS;
    let kickstart = true;
    if (stale) {
      const refusal = usableVersion ? await verifyHolder(manager) : null;
      if (!usableVersion) {
        log('[engine-host] not restarting the service: the listener reported a version that is not a short string');
        kickstart = false;
      } else if (refusal) {
        log(`[engine-host] not restarting the service: the listener on the engine port is not provably this user's own (${refusal.reason})`);
        kickstart = false;
      } else if (kickstartGuard && !kickstartGuard.allow(health.version)) {
        log(`[engine-host] not restarting the service again for the reported version ${JSON.stringify(String(health.version).slice(0, 64))}: the bound is spent`);
        kickstart = false;
      } else if (kickstartGuard) {
        kickstartGuard.record(health.version);
      }
    }
    if (kickstart && (!health || stale)) {
      log(`[engine-host] ${stale ? 'the service engine is older than this bundle' : 'no engine yet'}: kickstarting the service${stale ? ' (restart)' : ''}`);
      if (await service.kickstart(stale)) {
        const deadline = Date.now() + waitMs;
        while (Date.now() < deadline) {
          const now = await manager.getHealth();
          if (now && now.version === manager.getBundleVersion()) break;
          await sleep(500);
        }
      }
    }
  }
  return manager.start();
}

async function stop(manager, options, ctx) {
  const { service, log, sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)), waitMs = WAIT_MS } = ctx;
  if (service && service.isEnabled() && (await service.stop())) {
    const deadline = Date.now() + waitMs;
    while (Date.now() < deadline) {
      if (!(await manager.engineIsUp())) return { stopped: true, via: 'service', outcome: 'stopped' };
      await sleep(250);
    }
    log('[engine-host] the service stopped but the engine still answers: falling back to the shutdown route');
  }
  return manager.stopEngine(options);
}

module.exports = { NAME, SURVIVES_QUIT, WAIT_MS, start, stop };
