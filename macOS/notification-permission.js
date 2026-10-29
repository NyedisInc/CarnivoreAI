
'use strict';

const fs = require('fs');
const path = require('path');

const REQUESTED_FILE = 'notification-requested.flag';

const SETTINGS_URL = 'x-apple.systempreferences:com.apple.Notifications-Settings.extension';

function readState({ dir, fsImpl }) {
  return (fsImpl || fs).existsSync(path.join(dir, REQUESTED_FILE)) ? 'unknown' : 'not_asked';
}

const WAITING_WINDOW_MS = 10 * 60 * 1000;

function isWaiting({ dir, fsImpl, now }) {
  const f = fsImpl || fs;
  const file = path.join(dir, REQUESTED_FILE);
  try {
    if (!f.existsSync(file)) return false;
    return (now === undefined ? Date.now() : now) - f.statSync(file).mtimeMs < WAITING_WINDOW_MS;
  } catch (error) {
    return false;
  }
}

function request({ dir, Notification, t, fsImpl }) {
  const f = fsImpl || fs;
  if (!Notification.isSupported()) return readState({ dir, fsImpl: f });
  new Notification({ title: t('desktop.settings.banners_on_title'), body: t('desktop.settings.banners_on_body') }).show();
  f.mkdirSync(dir, { recursive: true });
  f.writeFileSync(path.join(dir, REQUESTED_FILE), `${new Date().toISOString()}\n`, { mode: 0o600 });
  return readState({ dir, fsImpl: f });
}

module.exports = { REQUESTED_FILE, SETTINGS_URL, WAITING_WINDOW_MS, readState, isWaiting, request };
