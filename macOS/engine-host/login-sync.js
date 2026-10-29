'use strict';

const fs = require('fs');
const path = require('path');
const handoff = require('../engine/login-handoff');
const { CARRIED_BY, loginServiceReady } = require('./constants');

function markCarried(userData, slice, switchedBack = false) {
  const record = handoff.readRecord(userData);
  if (!record) return;
  const { switchedBack: _old, ...rest } = record;
  const next = { ...rest, carriedBy: slice };
  if (switchedBack === true) next.switchedBack = true;
  const file = path.join(userData, handoff.RECORD_FILE);
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, `${JSON.stringify(next)}\n`, { mode: 0o600 });
  fs.renameSync(tmp, file);
}

function markLoginOff(userData, warn = console.warn) {
  try {
    const record = userData ? handoff.readRecord(userData) : null;
    if (!record) return false;
    if (record.launchAtLogin === false) return true;
    const file = path.join(userData, handoff.RECORD_FILE);
    const tmp = `${file}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, `${JSON.stringify({ ...record, launchAtLogin: false })}\n`, { mode: 0o600 });
    fs.renameSync(tmp, file);
    return true;
  } catch (err) {
    warn(`[login-sync] could not record the login-off click: ${err.message}`);
    return false;
  }
}

function syncLogin({ strategy, userData, installer, service, fresh, windowAtLogin, recordOnly = false }) {
  const freeze = loginServiceReady(strategy) ? strategy : null;
  const record = handoff.recordPreviousChoice({ userData, installer, windowAtLogin, freeze });
  if (recordOnly) return { record, registered: false, retired: { retired: false, reason: 'record-only' } };
  const ready = loginServiceReady(strategy) && service !== null;
  let registered = false;
  if (ready && !record.carriedBy) {
    if (fresh || record.launchAtLogin === true || record.switchedBack === true) {
      registered = true;
      if (service.register() === 'enabled') markCarried(userData, CARRIED_BY);
    }
  }
  const retired = ready && record.carriedBy
    ? { retired: false, reason: 'already-carried' }
    : handoff.retireLaunchAgent({ userData, installer, ready, keepForBackground: record.launchAtLogin === true });
  return { record: handoff.readRecord(userData) || record, registered, retired };
}

function syncLoginSafe(args, warn = console.warn) {
  try {
    return syncLogin(args);
  } catch (err) {
    warn(`[login-sync] could not sync the login choice: ${err.message}`);
    return null;
  }
}

module.exports = { markCarried, markLoginOff, syncLogin, syncLoginSafe };
