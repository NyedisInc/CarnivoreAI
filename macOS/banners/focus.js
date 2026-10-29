
'use strict';

const FOCUS_URL = 'x-apple.systempreferences:com.apple.Focus-Settings.extension';
const NOTIFICATIONS_URL = 'x-apple.systempreferences:com.apple.Notifications-Settings.extension';

async function openFocusSettings(shell) {
  try {
    await shell.openExternal(FOCUS_URL);
    return 'focus';
  } catch (error) {
    console.warn('[focus] the Focus pane was refused, opening Notifications:', error && error.message);
    await shell.openExternal(NOTIFICATIONS_URL);
    return 'notifications';
  }
}

module.exports = { FOCUS_URL, NOTIFICATIONS_URL, openFocusSettings };
