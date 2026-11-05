
'use strict';

const fs = require('fs');
const path = require('path');

const REQUESTED_FILE = 'notification-requested.flag';

const PROBE_ID = 'carnivore-banners-on';
const DELIVERED = 'delivered ';
const BLOCKED = 'blocked ';

const SETTINGS_URL = 'x-apple.systempreferences:com.apple.Notifications-Settings.extension';

function readState({ dir, fsImpl }) {
  const f = fsImpl || fs;
  const file = path.join(dir, REQUESTED_FILE);
  if (!f.existsSync(file)) return 'not_asked';
  let text = '';
  try {
    text = String(f.readFileSync(file, 'utf8'));
  } catch (error) {
    return 'unknown';
  }
  if (text.startsWith(DELIVERED)) return 'allowed';
  if (text.startsWith(BLOCKED)) return 'blocked';
  return 'unknown';
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
  new Notification({ id: PROBE_ID, title: t('desktop.settings.banners_on_title'), body: t('desktop.settings.banners_on_body') }).show();
  f.mkdirSync(dir, { recursive: true });
  f.writeFileSync(path.join(dir, REQUESTED_FILE), `${new Date().toISOString()}\n`, { mode: 0o600 });
  return readState({ dir, fsImpl: f });
}

async function probe({ dir, Notification, fsImpl, now }) {
  const f = fsImpl || fs;
  const before = readState({ dir, fsImpl: f });
  if (before === 'not_asked' || before === 'allowed' || typeof Notification.getHistory !== 'function') return before;
  let found;
  try {
    const history = await Notification.getHistory();
    found = Array.isArray(history) && history.some((note) => note && note.id === PROBE_ID);
  } catch (error) {
    console.warn('[notification-permission] the history read failed:', error && error.message);
    return before;
  }
  if (!found && (before === 'blocked' || isWaiting({ dir, fsImpl: f, now }))) return before;
  f.writeFileSync(path.join(dir, REQUESTED_FILE), `${found ? DELIVERED : BLOCKED}${new Date().toISOString()}\n`, { mode: 0o600 });
  return readState({ dir, fsImpl: f });
}

module.exports = { REQUESTED_FILE, SETTINGS_URL, WAITING_WINDOW_MS, PROBE_ID, readState, isWaiting, request, probe };
