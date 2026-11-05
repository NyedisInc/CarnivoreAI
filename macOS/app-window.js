
'use strict';

const { Notification, ipcMain, app } = require('electron');
const policy = require('./app-window-policy');
const { createWindowHost } = require('./window-host');

const MAX_TITLE = 200;
const MAX_BODY = 1000;
const ASK_ID_PATTERN = /^[A-Za-z0-9_:.-]{1,200}$/;
const NEEDS_YOU = 'needs_you';
const NEEDS_YOU_SOUND = 'Glass';

/* grouped by session */
function bannerOptions(title, body, meta) {
  const opts = { title: title.slice(0, MAX_TITLE), body: body.slice(0, MAX_BODY) };
  const m = meta && typeof meta === 'object' ? meta : {};
  const ok = (v) => typeof v === 'string' && ASK_ID_PATTERN.test(v);
  if (ok(m.id)) opts.id = m.id;
  const groupId = ok(m.session_id) ? m.session_id : (ok(m.tmux_name) ? m.tmux_name : '');
  if (groupId) opts.groupId = groupId;
  if (typeof m.subtitle === 'string' && m.subtitle.trim()) opts.subtitle = m.subtitle.slice(0, MAX_TITLE);
  if (m.silent === true) opts.silent = true;
  else if (m.group === NEEDS_YOU) opts.sound = NEEDS_YOU_SOUND;
  return opts;
}

function createAppWindow({ getUrl, windowState, shouldMirror, guard }) {
  const host = createWindowHost({ getUrl, windowState, guard });
  let handlersWired = false;

  function mainOnPublishedOrigin() {
    return host.mainWindow() && host.mainOrigin() === policy.originOf(getUrl()) ? host.mainWindow() : null;
  }

  async function onNotify(event, title, body, askSessionId, meta) {
    const win = host.mainWindow();
    if (!win || event.sender !== win.webContents) return;
    if (!event.senderFrame || event.senderFrame !== event.sender.mainFrame) return;
    const frameUrl = event.senderFrame.url;
    if (policy.originOf(frameUrl) !== host.mainOrigin()) return;
    if (typeof title !== 'string' || typeof body !== 'string') return;
    if (meta && meta.group === NEEDS_YOU && app && app.dock && typeof app.dock.bounce === 'function') app.dock.bounce('informational');
    if (shouldMirror) {
      let mirror = true;
      try {
        mirror = (await shouldMirror(typeof askSessionId === 'string' ? askSessionId : '')) !== false;
      } catch (error) {
        console.warn('[app-window] the asks-only check failed, mirroring:', error && error.message);
      }
      if (!mirror) return;
    }
    if (!Notification.isSupported()) return;
    const opts = bannerOptions(title, body, meta);
    if (watched && win.isFocused() && meta && typeof meta === 'object' && meta.session_id === watched) { opts.silent = true; delete opts.sound; }
    const note = new Notification(opts);
    note.on('click', () => (askSessionId ? openApproval(askSessionId) : openTarget(meta)));
    if (opts.id) shown.set(opts.id, note);
    if (shown.size > MAX_HELD) shown.delete(shown.keys().next().value);
    note.show();
  }

  let watched = '';

  function onWatching(event, sessionId) {
    const win = host.mainWindow();
    if (!win || event.sender !== win.webContents || !event.senderFrame || event.senderFrame !== event.sender.mainFrame) return;
    if (policy.originOf(event.senderFrame.url) !== host.mainOrigin()) return;
    watched = typeof sessionId === 'string' && ASK_ID_PATTERN.test(sessionId) ? sessionId : '';
  }

  function watchedSession() {
    const win = host.mainWindow();
    return win && !win.isDestroyed() && win.isFocused() ? watched : '';
  }

  const shown = new Map();
  const MAX_HELD = 200;

  function onUnnotify(event, id) {
    const win = host.mainWindow();
    if (!win || event.sender !== win.webContents || !event.senderFrame || event.senderFrame !== event.sender.mainFrame) return;
    if (policy.originOf(event.senderFrame.url) !== host.mainOrigin()) return;
    if (typeof id !== 'string' || !ASK_ID_PATTERN.test(id)) return;
    shown.delete(id);
    if (typeof Notification.remove === 'function') Notification.remove(id);
  }

  function openTarget(meta) {
    const m = meta && typeof meta === 'object' ? meta : {};
    const id = typeof m.session_id === 'string' && ASK_ID_PATTERN.test(m.session_id) ? m.session_id : '';
    const tmux = typeof m.tmux_name === 'string' && ASK_ID_PATTERN.test(m.tmux_name) ? m.tmux_name : '';
    const before = mainOnPublishedOrigin();
    if (!open()) return false;
    if ((id || tmux) && before && host.mainWindow() === before) before.webContents.send('carnivore:notify-click', { session_id: id, tmux_name: tmux });
    return true;
  }

  function open(hash) {
    if (!handlersWired && policy.originOf(getUrl()) !== null) {
      ipcMain.on('carnivore:notify', onNotify);
      ipcMain.on('carnivore:unnotify', onUnnotify);
      ipcMain.on('carnivore:watching', onWatching);
      handlersWired = true;
    }
    return host.open(hash);
  }

  function openApproval(askSessionId) {
    const ask = typeof askSessionId === 'string' && ASK_ID_PATTERN.test(askSessionId) ? askSessionId : '';
    if (!ask) return open();
    const before = mainOnPublishedOrigin();
    if (!open(before ? undefined : `?approvals=${encodeURIComponent(ask)}`)) return false;
    if (before && host.mainWindow() === before) before.webContents.send('carnivore:open-approval', ask);
    return true;
  }

  function sendMenuCommand(verb) {
    const before = mainOnPublishedOrigin();
    if (!open()) return false;
    if (before && host.mainWindow() === before) before.webContents.send('carnivore:menu-command', verb);
    return true;
  }

  return { ...host, open, openApproval, sendMenuCommand, watchedSession };
}

module.exports = { createAppWindow };
