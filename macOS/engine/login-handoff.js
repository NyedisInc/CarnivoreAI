
'use strict';

const fs = require('fs');
const path = require('path');

const RECORD_FILE = 'login-migration.json';

const LOGIN_SERVICE_READY = false;

function readRecord(userData) {
  try {
    const raw = JSON.parse(fs.readFileSync(path.join(userData, RECORD_FILE), 'utf8'));
    return raw && typeof raw === 'object' && typeof raw.launchAtLogin === 'boolean' ? raw : null;
  } catch (err) {
    return null;
  }
}

function recordPreviousChoice({ userData, installer, windowAtLogin, freeze = null }) {
  const existing = readRecord(userData);
  if (existing && typeof existing.carriedBy === 'string' && existing.carriedBy) return existing;
  if (existing && freeze && existing.frozenUnder === freeze) return existing;
  const record = {
    launchAtLogin: installer.isEnabled() === true,
    windowAtLogin: windowAtLogin === true,
    recordedAt: new Date().toISOString(),
    carriedBy: null,
  };
  if (freeze) record.frozenUnder = freeze;
  if (existing && existing.switchedBack === true) record.switchedBack = true;
  fs.mkdirSync(userData, { recursive: true });
  const file = path.join(userData, RECORD_FILE);
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, `${JSON.stringify(record)}\n`, { mode: 0o600 });
  fs.renameSync(tmp, file);
  return record;
}

function retireLaunchAgent({ userData, installer, ready = LOGIN_SERVICE_READY, keepForBackground = false }) {
  if (ready !== true) return { retired: false, reason: 'login-service-not-ready' };
  if (keepForBackground === true) return { retired: false, reason: 'background-toggle-on' };
  const record = readRecord(userData);
  if (!record) return { retired: false, reason: 'no-record' };
  if (typeof record.carriedBy !== 'string' || !record.carriedBy) return { retired: false, reason: 'not-carried' };
  installer.dropPlistFile();
  return { retired: true };
}

module.exports = { RECORD_FILE, LOGIN_SERVICE_READY, readRecord, recordPreviousChoice, retireLaunchAgent };
