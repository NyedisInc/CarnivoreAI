
'use strict';

const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('carnivoreDesktop', {
  contract: 1,
  capabilities: Object.freeze(['notify', 'unnotify', 'watching', 'localLogin', 'desktopState', 'setLoginItem', 'requestNotifications', 'openNotificationSettings', 'openFocusSettings',
    'openSessionWindow', 'focusSessionWindow', 'showInMain', 'openInTerminal', 'revealById', 'openInEditor', 'droppedPaths', 'raiseWindow', 'windowChrome', 'tearOff', 'goRecent', 'screenReader']),
  notify(title, body, askSessionId, meta) {
    const m = meta && typeof meta === 'object' ? meta : {};
    const str = (v) => (typeof v === 'string' ? v : '');
    ipcRenderer.send('carnivore:notify', String(title), String(body || ''), String(askSessionId || ''), {
      id: str(m.id), group: str(m.group), subtitle: str(m.subtitle), session_id: str(m.session_id), tmux_name: str(m.tmux_name), silent: m.silent === true,
    });
  },
  watching(sessionId) {
    ipcRenderer.send('carnivore:watching', typeof sessionId === 'string' ? sessionId : '');
  },
  unnotify(id) {
    ipcRenderer.send('carnivore:unnotify', String(id || ''));
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
  goRecent(labels) {
    if (Array.isArray(labels)) ipcRenderer.send('carnivore:go-recent', labels.slice(0, 10).map(String));
  },
});

ipcRenderer.on('carnivore:notify-click', (_event, target) => {
  const t = target && typeof target === 'object' ? target : {};
  const ok = (v) => typeof v === 'string' && /^[A-Za-z0-9_:.-]{0,200}$/.test(v);
  if (ok(t.session_id) && ok(t.tmux_name) && (t.session_id || t.tmux_name)) {
    window.postMessage({ type: 'carnivore.notify-click', session_id: t.session_id, tmux_name: t.tmux_name }, window.location.origin);
  }
});

ipcRenderer.on('carnivore:open-approval', (_event, sessionId) => {
  if (typeof sessionId === 'string' && sessionId) {
    window.postMessage({ type: 'carnivore.open-approval', session_id: sessionId }, window.location.origin);
  }
});

ipcRenderer.on('carnivore:menu-command', (_event, verb) => {
  if (typeof verb === 'string' && /^[a-z0-9_.]{1,40}$/.test(verb)) {
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

ipcRenderer.on('carnivore:window-hidden', (_event, hidden) => {
  if (typeof hidden === 'boolean') window.postMessage({ type: 'carnivore.window-hidden', hidden }, window.location.origin);
});

ipcRenderer.on('carnivore:window-blurred', (_event, blurred) => {
  if (typeof blurred === 'boolean') window.postMessage({ type: 'carnivore.window-blurred', blurred }, window.location.origin);
});
ipcRenderer.on('carnivore:power-calm', (_event, state) => {
  if (state && typeof state.calm === 'boolean' && typeof state.reason === 'string' && /^[a-z-]{0,12}$/.test(state.reason)) {
    window.postMessage({ type: 'carnivore.power-calm', calm: state.calm, reason: state.reason }, window.location.origin);
  }
});

ipcRenderer.on('carnivore:window-chrome', (_event, state) => {
  const num = (n) => typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= 200;
  if (state && state.inset && num(state.inset.top) && num(state.inset.left) && typeof state.fullScreen === 'boolean') {
    window.postMessage({ type: 'carnivore.window-chrome', inset: { top: state.inset.top, left: state.inset.left }, fullScreen: state.fullScreen }, window.location.origin);
  }
});
