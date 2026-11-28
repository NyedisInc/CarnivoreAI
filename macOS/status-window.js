
'use strict';

const path = require('path');
const { TOKEN_HEX } = require('./tray-menu/oc-token-values');
const { serveLocalPage } = require('./local-page');

const FACTS_CHANNEL = 'carnivore:status-facts';
const ACTION_CHANNEL = 'carnivore:status-action';
const PARTITION = 'carnivore-status-window';
const WIDTH = 460;
const HEIGHT = 380;

function createStatusWindow(deps) {
  let win = null;
  let wired = false;

  const fromWindow = (event) => Boolean(win && !win.isDestroyed() && event.sender === win.webContents
    && event.senderFrame && event.senderFrame === event.sender.mainFrame);

  function wire() {
    if (wired) return;
    wired = true;
    deps.ipcMain.handle(FACTS_CHANNEL, (event) => (fromWindow(event) ? deps.getFacts() : null));
    deps.ipcMain.on(ACTION_CHANNEL, (event, id) => {
      if (fromWindow(event) && typeof id === 'string') deps.runAction(id);
    });
  }

  function dispose() {
    const current = win;
    win = null;
    if (current && !current.isDestroyed()) current.destroy();
  }

  function create() {
    const created = new deps.BrowserWindow({
      width: WIDTH, height: HEIGHT, show: false, resizable: false, minimizable: false, maximizable: false,
      fullscreenable: false, title: (deps.getFacts() || {}).windowTitle || 'Carnivore', backgroundColor: TOKEN_HEX['--oc-ground-chrome'],
      webPreferences: {
        contextIsolation: true, sandbox: true, nodeIntegration: false,
        partition: PARTITION,
        preload: path.join(__dirname, 'status-window-preload.js'),
      },
    });
    const wc = created.webContents;
    wc.on('will-navigate', (event) => event.preventDefault());
    wc.setWindowOpenHandler(() => ({ action: 'deny' }));
    wc.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    wc.on('did-finish-load', () => {
      wc.insertCSS(deps.tokensCss()).catch((error) => console.warn('[status-window] tokens not applied:', error && error.message));
    });
    created.once('ready-to-show', () => created.show());
    created.on('closed', () => { if (win === created) win = null; });
    created.loadURL(serveLocalPage(wc.session, 'status', path.join(__dirname, 'status-window'), 'status.html'));
    return created;
  }

  function update() {
    if (!win || win.isDestroyed() || !win.isVisible()) return;
    const facts = deps.getFacts();
    if (!facts) {
      dispose();
      return;
    }
    win.webContents.send(FACTS_CHANNEL, facts);
  }

  return {
    open() {
      if (!deps.getFacts()) return false;
      wire();
      if (!win || win.isDestroyed()) win = create();
      else {
        if (win.isMinimized()) win.restore();
        win.show();
        win.focus();
        update();
      }
      return true;
    },
    close() {
      dispose();
    },
    isOpen: () => Boolean(win && !win.isDestroyed() && win.isVisible()),
    update,
    destroy() {
      dispose();
    },
  };
}

module.exports = { PARTITION, FACTS_CHANNEL, ACTION_CHANNEL, createStatusWindow };
