'use strict';

function setupPending(manager) {
  if (!manager || typeof manager.getSetupVerdict !== 'function') return false;
  try {
    const verdict = manager.getSetupVerdict();
    return Boolean(verdict) && verdict.status === 'incomplete';
  } catch (err) {
    console.warn('[tray-pairing] could not read the setup verdict, not holding:', err.message);
    return false;
  }
}

function trayOtp(manager) {
  return setupPending(manager) ? null : manager.getCurrentOtp();
}

module.exports = { setupPending, trayOtp };
