'use strict';

const path = require('path');
const { execFile } = require('child_process');
const { SERVICE_ARG, UNREGISTER_ARG } = require('./constants');
const { runUnregister } = require('./unregister-entry');
const { appendEngineLog } = require('../engine/detached-spawn');
const { createReopenRouter, wireReopen } = require('./reopen');
const { installTermHandler } = require('./teardown');
const { ownedStop } = require('./owned-stop');
const { createRestartGuard, readDiskVersion } = require('./version-guard');
const { createServiceLoop, START_FAILURE_FILE, START_FAILURE_WINDOW_MS, MAX_START_FAILURES } = require('./service-loop');
const { decide: decideRebind } = require('../rebind-after-pair');

const TICK_MS = 15000;

function bundleOf(exe) {
  const bundle = path.resolve(exe, '..', '..', '..');
  return bundle.endsWith('.app') ? bundle : null;
}

function runIfRequested({ app, argv, proc = process }) {
  if (Array.isArray(argv) && argv.includes(UNREGISTER_ARG)) {
    runUnregister({ app, proc });
    return true;
  }
  if (!Array.isArray(argv) || !argv.includes(SERVICE_ARG)) return false;
  app.setActivationPolicy('prohibited');
  const logFile = path.join(app.getPath('userData'), 'logs', 'server.log');
  const log = (msg) => { console.log(msg); appendEngineLog(logFile, `${msg}\n`); };
  wireReopen({ app, router: createReopenRouter({ execFile, bundlePath: bundleOf(app.getPath('exe')), log }) });
  app.on('window-all-closed', () => {});
  app.whenReady().then(() => runService({ app, proc, log })).catch((err) => {
    console.error('[engine-service] failed to start:', err && err.message);
    app.exit(1);
  });
  return true;
}

async function runService({ app, proc, log }) {
  const ServerManager = require('../server-manager');
  const { bootstrapIfNeeded } = require('../bootstrap');
  const { TrayApiClient } = require('../tray-api');
  const manager = new ServerManager();
  const userData = app.getPath('userData');
  log(`[engine-service] starting, version ${app.getVersion()}, pid ${proc.pid}, log ${manager.logFile}`);
  let api = null;
  const getApi = () => {
    const url = manager.getLocalApiUrl();
    if (!url) return null;
    if (!api) api = new TrayApiClient({ baseUrl: url, getOtp: () => require('../tray-pairing-hold').trayOtp(manager) });
    else api.setBaseUrl(url);
    return api;
  };
  const stopEngine = ownedStop({ manager, stopEngine: () => manager.stopEngine({ getApi }) });
  const onTerm = installTermHandler({ proc, role: 'service', quit: () => app.quit(), stopEngine, exit: (code) => app.exit(code), log });
  app.on('before-quit', (event) => { event.preventDefault(); onTerm(); });
  const bundleResourcesDir = app.isPackaged ? path.join(app.getAppPath(), '..') : path.join(__dirname, '..', '..');
  const boot = await bootstrapIfNeeded({ serverDir: path.join(userData, 'server'), bundleResourcesDir,
    isPackaged: app.isPackaged, appVersion: app.getVersion(), onStateChange: (state) => log(`[engine-service] bootstrap ${state}`) });
  log(`[engine-service] bootstrap ${boot.status}`);
  const loop = createServiceLoop({
    manager, running: app.getVersion(), readDisk: () => readDiskVersion({ exe: app.getPath('exe') }),
    guard: createRestartGuard({ userData }), decideRebind,
    startGuard: createRestartGuard({ userData, file: START_FAILURE_FILE, max: MAX_START_FAILURES, windowMs: START_FAILURE_WINDOW_MS }), stopEngine, getApi, exit: (code) => app.exit(code), log,
  });
  const run = async () => {
    try {
      await loop.tick();
    } catch (err) {
      log(`[engine-service] tick failed: ${err.message}`);
    }
    setTimeout(run, TICK_MS);
  };
  await run();
}

module.exports = { TICK_MS, bundleOf, runIfRequested };
