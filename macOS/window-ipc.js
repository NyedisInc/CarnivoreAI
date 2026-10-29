
'use strict';

const { senderAllowed } = require('./desktop-settings');
const { createFocusGate } = require('./deep-link');

const CHANNELS = Object.freeze({
  open: 'carnivore:open-session-window',
  focus: 'carnivore:focus-session-window',
  showInMain: 'carnivore:show-in-main',
  raise: 'carnivore:raise-window',
  chrome: 'carnivore:window-chrome',
  tearOff: 'carnivore:tear-off',
});

const ROW_ID = /^\d{1,15}$/;
const WIDGET_ID = /^(?:core\.[a-z0-9][a-z0-9-]*|[a-z][a-z0-9]{1,23}\.[a-z][a-z0-9-]{0,31}:[a-z0-9][a-z0-9:_-]{0,63})$/;
const MAX_COORD = 20000;

function validTearOff(kind, id, screenX, screenY) {
  if (typeof id !== 'string') return false;
  if (!((kind === 'terminal' && ROW_ID.test(id)) || (kind === 'widget' && WIDGET_ID.test(id)))) return false;
  return [screenX, screenY].every((n) => Number.isInteger(n) && Math.abs(n) <= MAX_COORD);
}

function registerWindowIpc({ ipcMain, appWindow, now = () => Date.now() }) {
  const gates = new WeakMap();
  const gateOpen = (sender) => {
    if (sender === null || typeof sender !== 'object') return true;
    if (!gates.has(sender)) gates.set(sender, createFocusGate({ now }));
    return gates.get(sender).allow();
  };
  const guard = (method, gated = false) => async (event, rowId) => {
    if (!senderAllowed(event, { appWindow }) || typeof rowId !== 'string' || !ROW_ID.test(rowId)) return false;
    if (gated && !gateOpen(event.sender)) return false;
    return appWindow[method](rowId) === true;
  };
  ipcMain.handle(CHANNELS.open, guard('openSolo', true));
  ipcMain.handle(CHANNELS.focus, guard('focusSolo', true));
  ipcMain.handle(CHANNELS.showInMain, guard('showInMain', true));
  ipcMain.handle(CHANNELS.raise, async (event) => senderAllowed(event, { appWindow }) && gateOpen(event.sender) && appWindow.raiseSender(event.sender) === true);
  ipcMain.handle(CHANNELS.tearOff, async (event, kind, id, screenX, screenY) => {
    if (!senderAllowed(event, { appWindow }) || !validTearOff(kind, id, screenX, screenY) || !gateOpen(event.sender)) return false;
    return appWindow.tearOff(kind, id, screenX, screenY) === true;
  });
  ipcMain.handle(CHANNELS.chrome, async (event) => (senderAllowed(event, { appWindow }) ? appWindow.chromeOf(event.sender) : null));
}

module.exports = { CHANNELS, registerWindowIpc, validTearOff };
