
'use strict';

const crypto = require('crypto');
const fs = require('fs');

const BIND_SETTINGS_ROUTE = '/api/v1/config/settings';

const PRIVATE_FILE_MODE = 0o600;

function writeDurably(target, text) {
  const tmp = `${target}.${process.pid}.${crypto.randomBytes(4).toString('hex')}.tmp`;
  try {
    const fd = fs.openSync(tmp, 'wx', PRIVATE_FILE_MODE);
    try {
      fs.fchmodSync(fd, PRIVATE_FILE_MODE);
      fs.writeSync(fd, text);
      fs.fsyncSync(fd);
    } finally {
      fs.closeSync(fd);
    }
    fs.renameSync(tmp, target);
  } catch (err) {
    fs.rmSync(tmp, { force: true });
    throw err;
  }
}

function writeConfigBindHost(configPath, ip) {
  try {
    const raw = fs.readFileSync(configPath, 'utf8');
    const parsed = JSON.parse(raw);
    parsed.server_prefs = Object.assign({}, parsed.server_prefs, { bind_host: ip });
    try {
      writeDurably(configPath + '.bak', raw);
    } catch (err) {
      console.warn('[bind-host] could not write config.json.bak, saving anyway:', err.message);
    }
    writeDurably(configPath, JSON.stringify(parsed, null, 2));
    return true;
  } catch (err) {
    console.warn('[bind-host] could not write config.json:', err.message);
    return false;
  }
}

async function persistBindHost(configPath, ip, api) {
  if (api) {
    try {
      const result = await api.sendAuthed(BIND_SETTINGS_ROUTE, { server_prefs: { bind_host: ip } }, 'PATCH');
      if (result && result.reachable) return true;
      console.warn('[bind-host] settings route refused or unreachable, writing config.json directly:', result && result.error);
    } catch (err) {
      console.warn('[bind-host] settings route call failed, writing config.json directly:', err.message);
    }
  }
  return writeConfigBindHost(configPath, ip);
}

module.exports = { persistBindHost, writeConfigBindHost, BIND_SETTINGS_ROUTE };
