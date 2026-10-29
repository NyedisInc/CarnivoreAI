'use strict';

const { execFile } = require('child_process');
const { createServiceControl } = require('./service-control');

const STILL_REGISTERED = new Set(['enabled', 'requires-approval']);

function runUnregister({ app, proc = process, log = console.log }) {
  app.setActivationPolicy('prohibited');
  app.on('window-all-closed', () => {});
  app.whenReady().then(() => {
    const control = createServiceControl({ app, execFile, uid: proc.getuid() });
    const before = control.status();
    const after = control.unregister();
    log(`[unregister-login-service] ${before} -> ${after}`);
    app.exit(STILL_REGISTERED.has(after) ? 1 : 0);
  }).catch((err) => {
    console.error('[unregister-login-service] failed:', err && err.message);
    app.exit(1);
  });
}

module.exports = { STILL_REGISTERED, runUnregister };
