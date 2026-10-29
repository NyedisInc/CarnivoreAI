
'use strict';

const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('carnivoreDesktop', {
  contract: 1,
  capabilities: Object.freeze(['notify', 'localLogin', 'desktopState', 'setLoginItem', 'requestNotifications', 'openNotificationSettings', 'openFocusSettings',
    'openSessionWindow', 'focusSessionWindow', 'showInMain', 'openInTerminal', 'revealById', 'openInEditor', 'droppedPaths', 'raiseWindow', 'windowChrome', 'tearOff', 'screenReader']),
  notify(title, body, askSessionId) {
    ipcRenderer.send('carnivore:notify', String(title), String(body || ''), String(askSessionId || ''));
  },
  localLogin() {
    return ipcRenderer.invoke('carnivore:local-login');
  },
  desktopState() {
    return ipcRenderer.invoke('carnivore:desktop-state');
  },
  setLoginItem(which, enabled) {
    return ipcRenderer.invoke('carnivore:set-login-item', String(which), enabled);
  },
  /* permission prompt */
  requestNotifications() {
    return ipcRenderer.invoke('carnivore:request-notifications');
  },
  openNotificationSettings() {
    return ipcRenderer.invoke('carnivore:open-notification-settings');
  },
  openFocusSettings() {
    return ipcRenderer.invoke('carnivore:open-focus-settings');
  },
  openSessionWindow(rowId) {
    return ipcRenderer.invoke('carnivore:open-session-window', String(rowId));
  },
  focusSessionWindow(rowId) {
    return ipcRenderer.invoke('carnivore:focus-session-window', String(rowId));
  },
  showInMain(rowId) {
    return ipcRenderer.invoke('carnivore:show-in-main', String(rowId));
  },
  tearOff(kind, id, screenX, screenY) {
    return ipcRenderer.invoke('carnivore:tear-off', String(kind), String(id), Math.round(Number(screenX)), Math.round(Number(screenY)));
  },
  raiseWindow() {
    return ipcRenderer.invoke('carnivore:raise-window');
  },
  openInTerminal(sessionId) {
    return ipcRenderer.invoke('carnivore:open-in-terminal', String(sessionId));
  },
  revealById(id) {
    return ipcRenderer.invoke('carnivore:reveal-by-id', String(id));
  },
  openInEditor(id) {
    return ipcRenderer.invoke('carnivore:open-in-editor', String(id));
  },
  droppedPaths(files) {
    const list = Array.from(files || []).slice(0, 50);
    return list.map((file) => {
      if (!(file instanceof File)) return '';
      try {
        return String(webUtils.getPathForFile(file) || '');
      } catch (error) {
        return '';
      }
    });
  },
  screenReader() {
    return ipcRenderer.invoke('carnivore:screen-reader');
  },
  windowChrome() {
    return ipcRenderer.invoke('carnivore:window-chrome');
  },
});

ipcRenderer.on('carnivore:open-approval', (_event, sessionId) => {
  if (typeof sessionId === 'string' && sessionId) {
    window.postMessage({ type: 'carnivore.open-approval', session_id: sessionId }, window.location.origin);
  }
});

ipcRenderer.on('carnivore:menu-command', (_event, verb) => {
  if (typeof verb === 'string' && /^[a-z_.]{1,40}$/.test(verb)) {
    window.postMessage({ type: 'carnivore.menu-command', verb }, window.location.origin);
  }
});

ipcRenderer.on('carnivore:show-row', (_event, rowId) => {
  if (typeof rowId === 'string' && /^\d{1,15}$/.test(rowId)) {
    window.postMessage({ type: 'carnivore.show-row', row_id: rowId }, window.location.origin);
  }
});

ipcRenderer.on('carnivore:screen-reader', (_event, on) => {
  if (typeof on === 'boolean') window.postMessage({ type: 'carnivore.screen-reader', on }, window.location.origin);
});

//  hidden 
ipcRenderer.on('carnivore:window-hidden', (_event, hidden) => {
  if (typeof hidden === 'boolean') window.postMessage({ type: 'carnivore.window-hidden', hidden }, window.location.origin);
});

ipcRenderer.on('carnivore:window-chrome', (_event, state) => {
  const num = (n) => typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= 200;
  if (state && state.inset && num(state.inset.top) && num(state.inset.left) && typeof state.fullScreen === 'boolean') {
    window.postMessage({ type: 'carnivore.window-chrome', inset: { top: state.inset.top, left: state.inset.left }, fullScreen: state.fullScreen }, window.location.origin);
  }
});
