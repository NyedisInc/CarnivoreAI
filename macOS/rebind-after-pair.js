
'use strict';

const STUCK_AFTER_MS = 60000;
const TICK_MS = 2000;
const WATCH_WINDOW_MS = 10 * 60 * 1000;

const SETTLE_WAIT_MS = 3000;
const SETTLE_POLL_MS = 250;

const LOOPBACK_HOSTS = ['127.0.0.1', 'localhost', '::1', '[::1]'];

let autoOpenedThisLaunch = false;
let seen = null;
let autoRestartsThisLaunch = 0;
let attemptAt = null;
let armed = false;
let finished = false;
let finishedByStop = false;
let deadline = 0;
let reloadOwed = false;
let restartInFlight = false;
let restartPromise = null;

function decide(report, state) {
  if (!report) return 'wait';
  const host = report.bind && report.bind.effective_host;
  const joinedWide = report.joined === true && typeof host === 'string' && host !== '' &&
    !LOOPBACK_HOSTS.includes(host);
  if (report.setup_status !== 'complete' && !joinedWide) return 'wait';
  const member = report.joined === true;
  const needed = member ? joinedWide : joinedWide || Boolean(report.bind && report.bind.restart_required === true);
  if (!needed) return 'stop';
  if (!state.attempted) return 'restart';
  if (state.attemptAt !== null && state.now - state.attemptAt >= STUCK_AFTER_MS) return member ? 'stop' : 'stuck';
  return 'wait';
}

/* this app did not start */
function shouldAutoOpen(verdict, owned, holderPid, processPid, joined) {
  if (joined === true) return false;
  if (!verdict || verdict.status !== 'incomplete' || !Array.isArray(verdict.checks)) return false;
  const rest = verdict.checks.filter((c) => c.key !== 'totp_paired');
  return rest.every((c) => c.passed === true) &&
    verdict.checks.some((c) => c.key === 'totp_paired' && c.passed === false) &&
    owned === true && holderPid !== null && holderPid !== undefined && holderPid === processPid;
}

/* once per launch */
async function maybeAutoOpenFirstRun({ serverManager, appWindow, waitForServerHealth, settle }) {
  if (autoOpenedThisLaunch) return false;
  if (!(await waitForServerHealth())) return false;
  if (autoOpenedThisLaunch) return false;
  let holderPid;
  try {
    const verdict = serverManager.getSetupVerdict();
    holderPid = await serverManager.findPortHolderPid(serverManager.getPort());
    const report = serverManager.getBindReport ? serverManager.getBindReport() : {};
    if (!shouldAutoOpen(verdict, serverManager.ownedProcess, holderPid, serverManager.processPid, report.joined)) {
      return false;
    }
  } catch (err) {
    console.warn('[first-run] not auto-opening:', err.message);
    return false;
  }
  if (settle) {
    try {
      await settle();
    } catch (err) {
      console.warn('[first-run] settle failed, opening anyway:', err.message);
    }
    if (serverManager.startBlockedReason) return false;
  }
  if (autoOpenedThisLaunch) return false;
  autoOpenedThisLaunch = true;
  appWindow.open();
  return true;
}

async function restartByClick({ serverManager, offerTakeOwnership, dialog }) {
  try {
    const result = await serverManager.restart();
    if (result && result.refused) await offerTakeOwnership('restart', result);
  } catch (err) {
    dialog.showErrorBox('Carnivore could not restart the server', err.message);
  }
}

async function showStuckDialog(deps) {
  const answer = await deps.dialog.showMessageBox({
    type: 'warning',
    title: 'Carnivore is still on this computer only',
    message: 'Carnivore restarted once after pairing, but the server is still listening ' +
      'on this computer only, so your phone cannot reach it yet.',
    detail: 'Restart it again now, or later from Restart Server in the menu. ' +
      'If this keeps happening, check the address in Setup and Config.',
    buttons: ['Not now', 'Restart Server'],
    defaultId: 0,
    cancelId: 0,
  });
  if (answer && answer.response === 1) await restartByClick(deps);
}

function payReload(deps) {
  if (!reloadOwed) return false;
  reloadOwed = false;
  if (deps.appWindow) deps.appWindow.reload();
  return true;
}

function startRestart(deps) {
  if (restartPromise) return restartPromise;
  autoRestartsThisLaunch = 1;
  attemptAt = Date.now();
  restartInFlight = true;
  restartPromise = (async () => {
    const { serverManager } = deps;
    try {
      const result = await serverManager.restart();
      restartInFlight = false;
      if (result && result.refused) {
        finished = true;
        payReload(deps);
        await deps.offerTakeOwnership('restart', result);
      } else {
        if (reloadOwed && deps.waitForServerHealth) await deps.waitForServerHealth();
        if (deps.whenGuardClear) deps.whenGuardClear(() => payReload(deps)); else payReload(deps);
      }
    } catch (err) {
      restartInFlight = false;
      finished = true;
      payReload(deps);
      await deps.reportStartFailure(err);
    }
  })();
  return restartPromise;
}

async function settleBeforeFirstWindow(deps) {
  if (restartPromise) {
    await restartPromise;
    if (deps.waitForServerHealth) await deps.waitForServerHealth();
    return true;
  }
  if (autoRestartsThisLaunch >= 1 || finished) return false;
  const manager = deps.serverManager;
  if ((manager.serviceOwnsEngine && manager.serviceOwnsEngine()) || manager.ownedProcess === false) return false;
  const until = Date.now() + SETTLE_WAIT_MS;
  for (;;) {
    if (deps.appWindow && deps.appWindow.isOpen && deps.appWindow.isOpen()) return false;
    if (restartPromise) break;
    const action = decide(manager.getBindReport(), { attempted: false, attemptAt: null, now: Date.now() });
    if (action === 'restart') break;
    if (action === 'wait' && (manager.getBindReport() || {}).setup_status === 'incomplete') return false;
    if (action !== 'wait' || Date.now() >= until) return false;
    await new Promise((resolve) => setTimeout(resolve, SETTLE_POLL_MS));
    try {
      await manager.getHealth();
    } catch (err) {
    }
  }
  await startRestart(deps);
  if (deps.waitForServerHealth) await deps.waitForServerHealth();
  return true;
}

async function tick(deps) {
  if (finished || Date.now() >= deadline) {
    armed = false;
    return;
  }
  const { serverManager } = deps;
  try {
    await serverManager.getHealth();
  } catch (err) {
  }
  const action = decide(serverManager.getBindReport(), {
    attempted: autoRestartsThisLaunch >= 1, attemptAt, now: Date.now(),
  });
  if (action === 'stop') {
    finished = true;
    finishedByStop = true;
    if (!payReload(deps) && deps.appWindow && deps.appWindow.rehome) deps.appWindow.rehome();
  } else if (action === 'stuck') {
    finished = true;
    payReload(deps);
    await showStuckDialog(deps);
  } else if (action === 'restart') {
    await startRestart(deps);
  }
  if (finished) {
    armed = false;
    return;
  }
  setTimeout(() => tick(deps), TICK_MS);
}

function observeHealth(deps) {
  const report = deps.serverManager.getBindReport();
  const joined = report.joined === undefined ? null : report.joined;
  const complete = report.setup_status === 'complete';
  const prev = seen;
  const windowOpen = deps.appWindow.isOpen();
  seen = { joined, complete, windowOpen };
  const becameJoined = Boolean(prev) && prev.windowOpen && prev.joined === false && joined === true;
  const left = Boolean(prev) && prev.joined === true && joined === false;
  const becameComplete = Boolean(prev) && prev.windowOpen && !prev.complete && complete;
  if (deps.onJoinedChange && joined !== null) deps.onJoinedChange(joined);
  const restartComing = becameComplete && !becameJoined && Boolean(report.bind && report.bind.restart_required === true) &&
    (restartInFlight || (autoRestartsThisLaunch === 0 && (!finished || finishedByStop)));
  if ((becameJoined || becameComplete) && deps.appWindow.isOpen()) {
    if (restartComing) reloadOwed = true;
    else deps.appWindow.reload();
  }
  if (left) deps.appWindow.open();
  const completedNow = Boolean(prev) && !prev.complete && complete;
  if (becameJoined || becameComplete || completedNow || report.rebind_requested === true) {
    if (finishedByStop) {
      finished = false;
      finishedByStop = false;
    }
    startWatch(deps);
  }
  return { joinedNow: joined, becameJoined, left };
}

function startWatch(deps) {
  if (finished) return;
  deadline = Date.now() + WATCH_WINDOW_MS;
  if (armed) return;
  armed = true;
  setTimeout(() => tick(deps), TICK_MS);
}

module.exports = {
  decide, shouldAutoOpen, maybeAutoOpenFirstRun, startWatch, observeHealth, settleBeforeFirstWindow,
  STUCK_AFTER_MS, TICK_MS, WATCH_WINDOW_MS,
};
