
'use strict';

const { Notification, ipcMain } = require('electron');
const policy = require('./app-window-policy');
const { createWindowHost } = require('./window-host');

const MAX_TITLE = 200;
const MAX_BODY = 1000;
const ASK_ID_PATTERN = /^[A-Za-z0-9_:.-]{1,200}$/;

function createAppWindow({ getUrl, windowState, shouldMirror, guard }) {
  const host = createWindowHost({ getUrl, windowState, guard });
  let handlersWired = false;

  function mainOnPublishedOrigin() {
    return host.mainWindow() && host.mainOrigin() === policy.originOf(getUrl()) ? host.mainWindow() : null;
  }

  async function onNotify(event, title, body, askSessionId) {
    const win = host.mainWindow();
    if (!win || event.sender !== win.webContents) return;
    if (!event.senderFrame || event.senderFrame !== event.sender.mainFrame) return;
    const frameUrl = event.senderFrame.url;
    if (policy.originOf(frameUrl) !== host.mainOrigin()) return;
    if (typeof title !== 'string' || typeof body !== 'string') return;
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
    const note = new Notification({ title: title.slice(0, MAX_TITLE), body: body.slice(0, MAX_BODY) });
    note.on('click', () => openApproval(askSessionId));
    note.show();
  }

  function open(hash) {
    if (!handlersWired && policy.originOf(getUrl()) !== null) {
      ipcMain.on('carnivore:notify', onNotify);
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

  return { ...host, open, openApproval, sendMenuCommand };
}

module.exports = { createAppWindow };
