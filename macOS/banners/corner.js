
'use strict';

const path = require('path');

const PAGE = '/static/notify-corner.html';
const WIDTH = 380;
const MIN_HEIGHT = 80;
const MAX_HEIGHT = 560;
const MARGIN_RIGHT = 12;
const MARGIN_TOP = 96;
const MEASURE = "new Promise((r) => setTimeout(() => r((document.getElementById('notify-corner') || document.body).getBoundingClientRect().height), 120))";

function createCorner(deps) {
  const setTimer = deps.setTimer || setTimeout;
  const clearTimer = deps.clearTimer || clearTimeout;
  let win = null;
  let winOrigin = '';
  let loaded = null;
  let current = null;
  let timer = null;
  let wired = false;

  const fromWindow = (event) => !!win && !win.isDestroyed() && event.sender === win.webContents
    && !!event.senderFrame && event.senderFrame === event.sender.mainFrame;

  function wire() {
    if (wired) return;
    wired = true;
    deps.ipcMain.on('carnivore:corner-press', (event, id) => {
      if (fromWindow(event) && current && typeof id === 'string') deps.onPress(current.key, id);
    });
    deps.ipcMain.on('carnivore:corner-close', (event) => {
      if (!fromWindow(event) || !current) return;
      const { key } = current;
      hide();
      deps.onClose(key);
    });
  }

  function ensure(origin) {
    if (win && !win.isDestroyed() && winOrigin === origin) return;
    if (win && !win.isDestroyed()) win.destroy();
    win = new deps.BrowserWindow({
      width: WIDTH, height: MIN_HEIGHT, show: false, frame: false, transparent: true, hasShadow: true, resizable: false,
      focusable: false, skipTaskbar: true, type: 'panel', backgroundColor: '#00000000',
      webPreferences: {
        contextIsolation: true, sandbox: true, nodeIntegration: false, backgroundThrottling: false,
        partition: deps.partitionFor(origin), preload: path.join(__dirname, 'corner-preload.js'),
      },
    });
    winOrigin = origin;
    loaded = null;
    win.setAlwaysOnTop(true, 'floating');
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    win.webContents.on('will-navigate', (event) => event.preventDefault());
    win.on('closed', () => { win = null; loaded = null; });
    wire();
  }

  function load(origin) {
    if (!loaded) {
      const page = win;
      loaded = page.loadURL(`${origin}${PAGE}`).then(() => page.webContents.insertCSS('html,body{overflow:hidden}')).then(() => true, (error) => {
        console.warn('[corner] page did not load:', String((error && error.message) || error));
        loaded = null;
        return false;
      });
    }
    return loaded;
  }

  function hide() {
    if (timer !== null) { clearTimer(timer); timer = null; }
    current = null;
    if (win && !win.isDestroyed()) win.hide();
  }

  async function show(card) {
    const url = deps.getUrl();
    let origin = '';
    try { origin = url ? new URL(url).origin : ''; } catch (error) { origin = ''; }
    if (!origin) return false;
    ensure(origin);
    const mine = win;
    if (!(await load(origin)) || mine !== win || !win || win.isDestroyed()) return false;
    if (timer !== null) { clearTimer(timer); timer = null; }
    current = { key: card.key };
    win.webContents.send('carnivore:corner-card', card.shown);
    let height = MIN_HEIGHT;
    try {
      height = Number(await win.webContents.executeJavaScript(MEASURE)) || MIN_HEIGHT;
    } catch (error) {
      console.warn('[corner] could not measure the card:', String((error && error.message) || error));
    }
    if (!win || win.isDestroyed() || !current || current.key !== card.key) return false;
    height = Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, Math.ceil(height) + 2));
    const area = deps.screen.getPrimaryDisplay().workArea;
    win.setBounds({ x: area.x + area.width - WIDTH - MARGIN_RIGHT, y: area.y + MARGIN_TOP, width: WIDTH, height });
    win.showInactive();
    if (card.autoHideMs > 0) timer = setTimer(hide, card.autoHideMs);
    return true;
  }

  function hideKey(key) {
    if (current && current.key === key) hide();
  }

  return { show, hide, hideKey, currentKey: () => (current ? current.key : null), window: () => win };
}

module.exports = { PAGE, WIDTH, createCorner };
