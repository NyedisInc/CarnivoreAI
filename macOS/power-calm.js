
'use strict';

const POOR_THERMAL = new Set(['serious', 'critical']);
const PMSET = '/usr/bin/pmset';
const PMSET_ARGS = ['-g'];
const PMSET_TIMEOUT_MS = 2000;
const DEBOUNCE_MS = 750;
const RECHECK_MS = 5 * 60 * 1000;
const EVENTS = ['on-battery', 'on-ac', 'thermal-state-change', 'resume', 'unlock-screen'];
const MODE_LINE = /^\s*(?:lowpowermode|powermode)\s+(\d)/m;

function parseLowPower(text) {
  const m = MODE_LINE.exec(typeof text === 'string' ? text : '');
  return !!m && m[1] === '1';
}

function registerPowerCalm({ powerMonitor, app, appWindow, execFile, log = () => {}, debounceMs = DEBOUNCE_MS, recheckMs = RECHECK_MS }) {
  let current = { calm: false, reason: '' };
  let debounce = null;
  let seq = 0;

  const apply = (reason) => {
    if (reason === current.reason) return;
    current = { calm: reason !== '', reason };
    appWindow.sendAll('carnivore:power-calm', current);
  };

  const thermalPoor = () => {
    try { return POOR_THERMAL.has(powerMonitor.getCurrentThermalState()); } catch { return false; }
  };

  const evaluate = () => {
    const mine = ++seq;
    if (thermalPoor()) { apply('thermal'); return; }
    try {
      execFile(PMSET, PMSET_ARGS, { timeout: PMSET_TIMEOUT_MS, windowsHide: true }, (err, stdout) => {
        if (mine !== seq) return;
        if (err) { log('[power-calm] pmset failed:', err.message); return; }
        apply(parseLowPower(String(stdout)) ? 'low-power' : '');
      });
    } catch (err) { log('[power-calm] pmset not runnable:', err.message); }
  };

  const schedule = () => {
    if (debounce) clearTimeout(debounce);
    debounce = setTimeout(() => { debounce = null; evaluate(); }, debounceMs);
    if (debounce.unref) debounce.unref();
  };

  const onLoad = (wc) => {
    wc.on('did-finish-load', () => {
      if (current.calm && appWindow.ownsSender(wc) && !wc.isDestroyed()) wc.send('carnivore:power-calm', current);
    });
  };

  for (const name of EVENTS) powerMonitor.on(name, schedule);
  app.on('web-contents-created', (_event, wc) => onLoad(wc));
  const recheck = setInterval(evaluate, recheckMs);
  if (recheck.unref) recheck.unref();
  evaluate();

  return {
    state: () => current,
    stop: () => {
      clearInterval(recheck);
      if (debounce) clearTimeout(debounce);
      for (const name of EVENTS) powerMonitor.removeListener(name, schedule);
    },
  };
}

module.exports = { registerPowerCalm, parseLowPower };
