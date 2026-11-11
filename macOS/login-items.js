
'use strict';

const fs = require('fs');
const path = require('path');
const { markLoginOff } = require('./engine-host/login-sync');

const WINDOW_FLAG = 'login-window.flag';

const LAUNCH_WINDOW_OFF_FLAG = 'launch-window-off.flag';

const WHICH = Object.freeze(['engine', 'window', 'background', 'launchWindow']);

function readLogin({ installer, dir, fsImpl, service = null }) {
  const f = fsImpl || fs;
  const launchWindow = !f.existsSync(path.join(dir, LAUNCH_WINDOW_OFF_FLAG));
  if (!installer) return { engine: null, window: null, background: null, launchWindow };
  if (service) {
    const background = installer.isEnabled() === true;
    return { engine: service.isEnabled() === true, window: background && f.existsSync(path.join(dir, WINDOW_FLAG)), background, launchWindow };
  }
  const engine = installer.isEnabled() === true;
  return { engine, window: engine && f.existsSync(path.join(dir, WINDOW_FLAG)), background: null, launchWindow };
}

function validLoginRequest(which, enabled) {
  return typeof which === 'string' && WHICH.includes(which) && typeof enabled === 'boolean';
}

function setLogin({ installer, launchArgs, dir, which, enabled, fsImpl, service = null }) {
  const f = fsImpl || fs;
  const flag = path.join(dir, WINDOW_FLAG);
  if (which === 'launchWindow') {
    if (enabled) removeFlag(f, path.join(dir, LAUNCH_WINDOW_OFF_FLAG));
    else { f.mkdirSync(dir, { recursive: true }); f.writeFileSync(path.join(dir, LAUNCH_WINDOW_OFF_FLAG), `${new Date().toISOString()}\n`, { mode: 0o600 }); }
    return readLogin({ installer, dir, fsImpl: f, service });
  }
  if (service && installer) return setLoginWithService({ installer, service, launchArgs, dir, which, enabled, f, flag });
  if (!installer || which === 'background') return readLogin({ installer, dir, fsImpl: f });
  if (which === 'engine') {
    if (enabled && !installer.isEnabled()) installer.enable(launchArgs());
    if (!enabled) {
      if (installer.isEnabled()) installer.disable();
      removeFlag(f, flag);
      markLoginOff(dir);
    }
  } else if (enabled) {
    if (!installer.isEnabled()) installer.enable(launchArgs());
    f.mkdirSync(dir, { recursive: true });
    f.writeFileSync(flag, `${new Date().toISOString()}\n`, { mode: 0o600 });
  } else {
    removeFlag(f, flag);
  }
  return readLogin({ installer, dir, fsImpl: f });
}

function setLoginWithService({ installer, service, launchArgs, dir, which, enabled, f, flag }) {
  if (which === 'engine') {
    if (enabled && !service.isEnabled()) service.register();
    if (!enabled && service.isEnabled()) service.unregister();
    if (!enabled) markLoginOff(dir);
  } else if (which === 'background') {
    if (enabled && !installer.isEnabled()) installer.enable(launchArgs());
    if (!enabled) {
      if (installer.isEnabled()) installer.disable();
      removeFlag(f, flag);
    }
  } else if (enabled) {
    if (!installer.isEnabled()) installer.enable(launchArgs());
    f.mkdirSync(dir, { recursive: true });
    f.writeFileSync(flag, `${new Date().toISOString()}\n`, { mode: 0o600 });
  } else {
    removeFlag(f, flag);
  }
  return readLogin({ installer, dir, fsImpl: f, service });
}

function removeFlag(f, flag) {
  try {
    f.unlinkSync(flag);
  } catch (err) {
    if (err.code !== 'ENOENT') throw err;
  }
}

module.exports = { WINDOW_FLAG, LAUNCH_WINDOW_OFF_FLAG, WHICH, readLogin, validLoginRequest, setLogin };
