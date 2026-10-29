
'use strict';

const fs = require('fs');
const path = require('path');
const { markLoginOff } = require('./engine-host/login-sync');

const WINDOW_FLAG = 'login-window.flag';

const WHICH = Object.freeze(['engine', 'window', 'background']);

function readLogin({ installer, dir, fsImpl, service = null }) {
  const f = fsImpl || fs;
  if (!installer) return { engine: null, window: null, background: null };
  if (service) {
    const background = installer.isEnabled() === true;
    return { engine: service.isEnabled() === true, window: background && f.existsSync(path.join(dir, WINDOW_FLAG)), background };
  }
  const engine = installer.isEnabled() === true;
  return { engine, window: engine && f.existsSync(path.join(dir, WINDOW_FLAG)), background: null };
}

function validLoginRequest(which, enabled) {
  return typeof which === 'string' && WHICH.includes(which) && typeof enabled === 'boolean';
}

function setLogin({ installer, launchArgs, dir, which, enabled, fsImpl, service = null }) {
  const f = fsImpl || fs;
  const flag = path.join(dir, WINDOW_FLAG);
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

module.exports = { WINDOW_FLAG, WHICH, readLogin, validLoginRequest, setLogin };
