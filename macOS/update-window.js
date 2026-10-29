
'use strict';

const path = require('path');
const { TOKEN_HEX } = require('./tray-menu/oc-token-values');
const { serveLocalPage } = require('./local-page');

const FACTS_CHANNEL = 'carnivore:update-facts';
const ACTION_CHANNEL = 'carnivore:update-action';
const PARTITION = 'carnivore-update-window';
const WIDTH = 460;
const HEIGHT = 250;
const RETRY_ACTION = 'update.install';

function windowFacts(update, t) {
  const version = (update && update.version) || '';
  const failed = update && (update.state === 'error' || update.state === 'update_refused');
  let phase = 'downloading';
  if (failed) phase = 'error';
  else if (update && ['verifying', 'installing', 'restarting'].includes(update.phase)) phase = update.phase;
  const downloading = phase === 'downloading';
  return {
    phase,
    title: t('menubar.update.window.title'),
    name: version,
    status: t(`menubar.update.window.${phase}`, { version, percent: (update && update.percent) || 0 }),
    percent: downloading ? Math.max(0, Math.min(100, Math.round((update && update.percent) || 0))) : null,
    detail: failed ? String((update && update.detail) || '') : '',
    retryLabel: failed ? t('menubar.update.window.retry') : null,
  };
}

function createUpdateWindow(deps) {
  let win = null;
  let wired = false;

  const fromWindow = (event) => Boolean(win && !win.isDestroyed() && event.sender === win.webContents
    && event.senderFrame && event.senderFrame === event.sender.mainFrame);

  function wire() {
    if (wired) return;
    wired = true;
    deps.ipcMain.handle(FACTS_CHANNEL, (event) => (fromWindow(event) ? deps.getFacts() : null));
    deps.ipcMain.on(ACTION_CHANNEL, (event, id) => {
      if (fromWindow(event) && id === RETRY_ACTION) deps.runAction(RETRY_ACTION);
    });
  }

  function create() {
    const created = new deps.BrowserWindow({
      width: WIDTH, height: HEIGHT, show: false, resizable: false, minimizable: false, maximizable: false,
      fullscreenable: false, title: deps.getFacts().title, backgroundColor: TOKEN_HEX['--oc-ground-chrome'],
      webPreferences: {
        contextIsolation: true, sandbox: true, nodeIntegration: false,
        partition: PARTITION,
        preload: path.join(__dirname, 'update-window-preload.js'),
      },
    });
    const wc = created.webContents;
    wc.on('will-navigate', (event) => event.preventDefault());
    wc.setWindowOpenHandler(() => ({ action: 'deny' }));
    wc.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    wc.on('did-finish-load', () => {
      wc.insertCSS(deps.tokensCss()).catch((error) => console.warn('[update-window] tokens not applied:', error && error.message));
    });
    created.once('ready-to-show', () => created.show());
    created.on('closed', () => { win = null; });
    created.loadURL(serveLocalPage(wc.session, 'update', path.join(__dirname, 'update-window'), 'update.html'));
    return created;
  }

  function update() {
    if (win && !win.isDestroyed()) win.webContents.send(FACTS_CHANNEL, deps.getFacts());
  }

  return {
    open() {
      wire();
      if (!win || win.isDestroyed()) win = create();
      else {
        if (win.isMinimized()) win.restore();
        win.show();
        win.focus();
        update();
      }
    },
    update,
    isOpen: () => Boolean(win && !win.isDestroyed()),
    destroy() {
      if (win && !win.isDestroyed()) win.destroy();
      win = null;
    },
  };
}

module.exports = { PARTITION, FACTS_CHANNEL, ACTION_CHANNEL, RETRY_ACTION, windowFacts, createUpdateWindow };
