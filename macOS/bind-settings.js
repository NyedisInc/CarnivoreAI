
'use strict';

const fs = require('fs');

const BIND_SETTINGS_ROUTE = '/api/v1/config/settings';

function writeConfigBindHost(configPath, ip) {
  try {
    const parsed = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    parsed.server_prefs = Object.assign({}, parsed.server_prefs, { bind_host: ip });
    const tmp = configPath + '.menubar.tmp';
    fs.writeFileSync(tmp, JSON.stringify(parsed, null, 2), 'utf8');
    fs.renameSync(tmp, configPath);
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
