'use strict';

const { decideLifecycleAction, STOP_ENGINE_ACTION } = require('../ownership-policy');
const { execFile } = require('child_process');
const portTrust = require('../tray-menu/port-trust');
const { stopEngineViaRoute } = require('./engine-stop');
const { normalizeVersion } = require('../adoption-decision');
const setupVerdict = require('../setup-verdict');

async function verifyEngineHolder(manager) {
  try {
    return portTrust.holderRefusal(await portTrust.listeners(manager.getPort(), { execFile }), process.getuid());
  } catch (err) {
    return { reason: 'unknown', holder: null };
  }
}

async function recordEngine(pid, port, version) {
  const ident = pid ? await portTrust.processIdentity(pid, { execFile }) : null;
  return ident ? { pid, start: ident.start, exe: ident.exe, port, version } : null;
}

async function signalEngineHolders(manager) {
  const rec = manager.engineRecord;
  const refuse = (why) => ({ ok: false, error: `${why}; nothing was signalled` });
  if (!rec || !Number.isInteger(rec.pid) || !rec.start) return refuse('no adopted engine is recorded');
  let port;
  try { port = manager.getPort(); } catch (err) { return refuse('the engine port cannot be read'); }
  if (port !== rec.port) return refuse(`the engine port is now ${port}, not the adoption port ${rec.port}`);
  const holders = await portTrust.listeners(port, { execFile });
  if (!Array.isArray(holders) || holders.length !== 1) return refuse('the port does not have exactly one listener');
  const [holder] = holders;
  if (holder.pid !== rec.pid || holder.uid !== process.getuid()) return refuse('the listener is not the adopted engine');
  if (portTrust.NEVER_KILL.includes(holder.command)) return refuse(`${holder.command} is never stopped from here`);
  const ident = await portTrust.processIdentity(rec.pid, { execFile });
  if (!ident || ident.start !== rec.start || ident.exe !== rec.exe) return refuse('the adopted pid is no longer the same process');
  const health = await manager.getHealth();
  if (!portTrust.isCarnivoreHealth(health) || normalizeVersion(health.version) !== rec.version) return refuse('the listener does not answer as the adopted engine');
  try {
    process.kill(rec.pid, 'SIGTERM');
    return { ok: true };
  } catch (err) {
    return { ok: false, error: `could not signal the engine: ${err.code || err.message}` };
  }
}

function localSetupIncomplete(manager, getApi) {
  if (getApi && getApi()) return false;
  if (typeof manager.readSetupFacts !== 'function') return false;
  return setupVerdict.evaluateLocalSetup(manager.readSetupFacts()).status === 'incomplete';
}

async function stopEngine(manager, options = {}) {
  const verdict = decideLifecycleAction({ action: STOP_ENGINE_ACTION, owned: manager.ownedProcess });
  if (verdict.via === 'signal') return { ...(await manager.stop()), via: 'signal' };

  manager.stopRequested = true;
  manager.lastExitUnexpected = false;
  if (manager.slowRetry) manager.slowRetry.cancel();
  const result = await stopEngineViaRoute({
    getApi: options.getApi || (() => null), isUp: () => manager.engineIsUp(),
    verifyHolder: () => verifyEngineHolder(manager),
    setupIncomplete: () => localSetupIncomplete(manager, options.getApi),
    signalHolder: () => signalEngineHolders(manager),
    log: (message) => console.log(message),
  });
  if (!result.stopped) {
    manager.stopRequested = false;
    return { ...result, via: 'route' };
  }
  manager.process = null;
  manager.processPid = null;
  manager.ownedProcess = false;
  manager.adoptedVersion = null;
  manager.engineRecord = null;
  manager.state = 'stopped';
  manager.startTime = null;
  return { ...result, via: 'route' };
}

async function restartAdoptedEngine(manager, options = {}) {
  const stopped = await stopEngine(manager, options);
  if (!stopped.stopped) return { ok: false, outcome: stopped.outcome, error: stopped.error };
  manager.startBlockedReason = null;
  manager.adoptedVersion = null;
  await manager.start();
  return { ok: true };
}

module.exports = { recordEngine, verifyEngineHolder, stopEngine, restartAdoptedEngine };
