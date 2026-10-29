'use strict';

const { SERVICE_LABEL, SERVICE_NAME } = require('./constants');

function createServiceControl({ app, execFile, uid }) {
  const opts = { type: 'agentService', serviceName: SERVICE_NAME };
  const status = () => {
    try {
      const settings = app.getLoginItemSettings(opts);
      return settings && typeof settings.status === 'string' ? settings.status : 'unknown';
    } catch (err) {
      return 'unknown';
    }
  };
  const set = (openAtLogin) => {
    app.setLoginItemSettings({ ...opts, openAtLogin });
    return status();
  };
  return {
    status,
    isEnabled: () => status() === 'enabled',
    register: () => set(true),
    unregister: () => set(false),
    stop: () => new Promise((resolve) => {
      execFile('/bin/launchctl', ['stop', SERVICE_LABEL], (err) => resolve(!err));
    }),
    kickstart: (kill = false) => new Promise((resolve) => {
      execFile('/bin/launchctl', ['kickstart', ...(kill ? ['-k'] : []), `gui/${uid}/${SERVICE_LABEL}`], (err) => resolve(!err));
    }),
  };
}

module.exports = { createServiceControl };
