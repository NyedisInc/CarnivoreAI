'use strict';

const { pickStrategy } = require('./settings');
const { createRestartGuard } = require('./version-guard');
const path = require('path');
const { probeEngine } = require('./adopt');
const { appendEngineLog } = require('../engine/detached-spawn');
const detached = require('./strategies/detached');
const launchdAgent = require('./strategies/launchd-agent');
const child = require('./strategies/child');

const KICKSTART_FILE = 'engine-service-kickstarts.json';
const KICKSTART_WINDOW_MS = 30 * 60 * 1000;

const STRATEGY_MODULES = Object.freeze({ detached, 'launchd-agent': launchdAgent, child });

function createEngineHost({ name, service = null, log = () => {}, kickstartGuard = null }) {
  const strategy = STRATEGY_MODULES[name] || detached;
  const ctx = { service, log, kickstartGuard };
  return {
    name: STRATEGY_MODULES[name] ? name : 'detached',
    serviceOwnsEngine: () => name === 'launchd-agent' && service !== null && service.isEnabled(),
    survivesQuit: () => strategy.SURVIVES_QUIT,
    spawnEngine: (options) => require('./spawn').spawnEngine(strategy.NAME, options),
    start: (manager) => strategy.start(manager, ctx),
    stop: (manager, options) => (strategy.stop ? strategy.stop(manager, options, ctx) : manager.stopEngine(options)),
    status: (manager) => ({ strategy: strategy.NAME, state: manager.getState(), owned: manager.ownedProcess === true,
      pid: manager.processPid || null, service: service ? service.status() : null }),
    adopt: (manager) => probeEngine({ health: () => manager.getHealth(), bind: () => manager.isPortInUse(), listenPid: () => manager.findPortHolderPid(manager.getPort()) }),
    logPath: (manager) => manager.logFile,
  };
}

let current = createEngineHost({ name: 'detached' });

function unregisterForSwitchBack(service, log) {
  try {
    service.unregister();
  } catch (err) {
    log(`[engine-host] could not unregister the engine login service: ${err.message}; acting as launchd-agent`);
    return false;
  }
  const still = service.isEnabled();
  log(still ? '[engine-host] the engine login service is still enabled after unregister: acting as launchd-agent'
    : '[engine-host] the host reads detached: the engine login service was unregistered');
  return !still;
}

function clearCarriedQuietly(userData, log) {
  if (!userData) return;
  try { require('./login-sync').markCarried(userData, null, true); } catch (err) { log(`[engine-host] could not clear carriedBy: ${err.message}`); }
}

function setHostFromSettings({ env, userData, service = null, log = () => {} }) {
  const pick = pickStrategy({ env, userData });
  if (pick.warning) log(`[engine-host] ${pick.warning}`);
  if (pick.name === 'detached' && service && service.isEnabled()) {
    if (pick.source === 'default') {
      log('[engine-host] no explicit engine host setting: keeping the engine login service');
      pick.name = 'launchd-agent';
    } else if (unregisterForSwitchBack(service, log)) {
      clearCarriedQuietly(userData, log);
    } else pick.name = 'launchd-agent';
  }
  const logFile = userData ? path.join(userData, 'logs', 'server.log') : null;
  const both = (msg) => { log(msg); if (logFile) appendEngineLog(logFile, `${msg}\n`); };
  const kickstartGuard = userData ? createRestartGuard({ userData, file: KICKSTART_FILE, max: 1, windowMs: KICKSTART_WINDOW_MS }) : null;
  current = createEngineHost({ name: pick.name, service, log: both, kickstartGuard });
  return current;
}

const getHost = () => current;

module.exports = { createEngineHost, setHostFromSettings, getHost, pickStrategy };
