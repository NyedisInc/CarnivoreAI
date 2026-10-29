
'use strict';

const path = require('path');
const { BrowserWindow, shell } = require('electron');
const policy = require('./app-window-policy');
const { chromeOptions, chromeState } = require('./window-chrome');

const DEFAULT_SIZE = Object.freeze({ width: 1280, height: 860 });
const MAX_WINDOWS = 24;
const BLUR_DELAY_MS = 1000;
const SAVED_KEY = /^popout:[\x20-\x7e]{1,160}$/;
const ROW_ID = /^\d{1,15}$/;
const WIDGET_ID = /^(?:core\.[a-z0-9][a-z0-9-]*|[a-z][a-z0-9]{1,23}\.[a-z][a-z0-9-]{0,31}:[a-z0-9][a-z0-9:_-]{0,63})$/;
const TEAR_SIZE = Object.freeze({ terminal: { width: 960, height: 640 }, widget: { width: 800, height: 600 } });

function createWindow(kind, origin, bounds) {
  const options = {
    ...bounds,
    ...chromeOptions(kind),
    show: false,
    title: 'Carnivore',
    backgroundColor: '#0b0d0e',
    webPreferences: {
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      backgroundThrottling: true,
      partition: policy.partitionForOrigin(origin),
      preload: path.join(__dirname, 'app-window-preload.js'),
    },
  };
  return new BrowserWindow(options);
}

function createWindowHost({ getUrl, windowState, guard }) {
  /** @type {Map<string, {win: object, kind: string, path: string, origin: string}>} */
  const entries = new Map();
  let quitting = false;
  let restoring = false;
  let restored = false;

  function live(key) {
    const entry = entries.get(key);
    return entry && !entry.win.isDestroyed() ? entry : null;
  }

  function raise(win) {
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
  }

  function persist() {
    if (!windowState || restoring) return;
    const list = [];
    for (const [key, e] of entries) if (e.kind !== 'main' && !e.win.isDestroyed()) list.push({ key, kind: e.kind, path: e.path });
    windowState.writeOpen(list);
  }

  function createEntry({ key, kind, origin, path: relPath, seed, placed }) {
    const saver = windowState ? windowState.forKey(key) : null;
    const saved = saver ? saver.load() : null;
    const fallback = { width: seed && seed.width ? seed.width : DEFAULT_SIZE.width, height: seed && seed.height ? seed.height : DEFAULT_SIZE.height };
    const seedRect = seed && [seed.x, seed.y, seed.width, seed.height].every(Number.isFinite) ? seed : null;
    const bounds = saver ? saver.bounds(fallback, seedRect, placed === true) : fallback;
    const win = createWindow(kind, origin, bounds);
    const entry = { win, kind, path: relPath, origin };
    entries.set(key, entry);
    const wc = win.webContents;
    const route = (event, url) => {
      const verdict = policy.decideNavigation(url, origin);
      if (verdict === 'allow') return;
      event.preventDefault();
      if (verdict === 'external') shell.openExternal(url);
    };
    wc.on('will-navigate', route);
    wc.on('will-redirect', route);
    wc.on('will-frame-navigate', (details) => {
      if (details.isMainFrame || /^about:/i.test(details.url)) return;
      if (policy.decideNavigation(details.url, origin) !== 'allow') details.preventDefault();
    });
    wc.setWindowOpenHandler(({ url, disposition, frameName, features }) => {
      const verdict = policy.decideWindowOpen(url, origin, disposition);
      if (verdict === 'external') shell.openExternal(url);
      else if (verdict === 'native') openNative({ url, origin, frameName, features });
      return { action: 'deny' };
    });
    if (guard) guard.attach(wc.session, origin);
    wc.session.setPermissionRequestHandler((contents, permission, callback, details) => {
      callback(policy.isPermissionAllowed(permission, details.requestingUrl || contents.getURL(), origin));
    });
    wc.session.setPermissionCheckHandler((contents, permission, requestingOrigin) =>
      policy.isPermissionAllowed(permission, requestingOrigin, origin));
    if (saver) saver.track(win);
    const sendChrome = () => { if (!win.isDestroyed()) wc.send('carnivore:window-chrome', chromeState(win)); };
    win.on('enter-full-screen', sendChrome);
    win.on('leave-full-screen', sendChrome);
    const sendHidden = () => {
      if (win.isDestroyed()) return;
      const hidden = win.isMinimized() || !win.isVisible();
      wc.send('carnivore:window-hidden', hidden);
    };
    for (const name of ['minimize', 'restore', 'hide', 'show']) win.on(name, sendHidden);
    let blurTimer = null;
    let blurSent = false;
    const sendBlurred = (blurred) => {
      if (win.isDestroyed() || blurSent === blurred) return;
      blurSent = blurred;
      wc.send('carnivore:window-blurred', blurred);
    };
    const clearBlurTimer = () => { if (blurTimer) { clearTimeout(blurTimer); blurTimer = null; } };
    win.on('blur', () => { clearBlurTimer(); blurTimer = setTimeout(() => { blurTimer = null; sendBlurred(true); }, BLUR_DELAY_MS); });
    win.on('focus', () => { clearBlurTimer(); sendBlurred(false); });
    wc.on('did-finish-load', () => { clearBlurTimer(); blurSent = null; sendBlurred(!win.isFocused()); });
    win.once('ready-to-show', () => {
      if (saved && saved.fullScreen) win.setFullScreen(true);
      else if (saved && saved.maximized) win.maximize();
      win.show();
    });
    win.on('closed', () => {
      clearBlurTimer();
      if (entries.get(key) !== entry) return;
      entries.delete(key);
      if (!quitting && kind !== 'main') persist();
    });
    const first = () => { if (!win.isDestroyed()) win.loadURL(relPath === '/' ? origin : `${origin}${relPath}`); };
    if (guard && guard.whenClear) guard.whenClear(first); else first();
    if (kind !== 'main') persist();
    return win;
  }

  function openNative({ url, origin, frameName, features, key, placed }) {
    const target = policy.nativeTarget(url, origin);
    if (!target) return false;
    const wanted = target.kind === 'popout' && key && SAVED_KEY.test(key) ? key : policy.popoutWindowKey(url, frameName);
    const existing = live(wanted);
    if (existing) {
      raise(existing.win);
      return true;
    }
    if (entries.size >= MAX_WINDOWS) return false;
    createEntry({ key: wanted, kind: target.kind, origin, path: target.path, seed: policy.boundsFromFeatures(features), placed });
    return true;
  }

  const main = () => live('main');

  function dropOtherOrigins(origin) {
    for (const [key, e] of [...entries]) {
      if (e.origin === origin) continue;
      entries.delete(key);
      if (!e.win.isDestroyed()) e.win.destroy();
    }
  }

  function open(hash) {
    const origin = policy.originOf(getUrl());
    if (origin === null) return false;
    const current = main();
    if (current && current.origin === origin) {
      raise(current.win);
      if (hash) current.win.loadURL(`${origin}/${hash}`);
      return true;
    }
    dropOtherOrigins(origin);
    createEntry({ key: 'main', kind: 'main', origin, path: hash ? `/${hash}` : '/' });
    return true;
  }

  function openSolo(rowId) {
    const origin = policy.originOf(getUrl());
    if (origin === null || typeof rowId !== 'string' || !/^\d{1,15}$/.test(rowId)) return false;
    return openNative({ url: `${origin}/?solo=${rowId}`, origin });
  }

  function focusSolo(rowId) {
    const entry = typeof rowId === 'string' && /^\d{1,15}$/.test(rowId) ? live(`solo:row:${rowId}`) : null;
    if (entry) raise(entry.win);
    return !!entry;
  }

  function tearOff(kind, id, screenX, screenY) {
    const origin = policy.originOf(getUrl());
    if (origin === null || typeof id !== 'string' || !Number.isInteger(screenX) || !Number.isInteger(screenY)) return false;
    let url;
    let frameName;
    if (kind === 'terminal' && ROW_ID.test(id)) url = `${origin}/?solo=${id}`;
    else if (kind === 'widget' && WIDGET_ID.test(id)) {
      url = `${origin}/static/popout.html?widget=${encodeURIComponent(id)}`;
      frameName = `carnivore-widget-${id}`;
    } else return false;
    const size = TEAR_SIZE[kind];
    const features = `left=${screenX - 80},top=${screenY - 18},width=${size.width},height=${size.height}`;
    return openNative({ url, origin, frameName, features, placed: true });
  }

  function showInMain(rowId) {
    if (typeof rowId !== 'string' || !/^\d{1,15}$/.test(rowId) || !open()) return false;
    const wc = main().win.webContents;
    if (typeof wc.isLoading === 'function' && wc.isLoading()) wc.once('did-finish-load', () => wc.send('carnivore:show-row', rowId));
    else wc.send('carnivore:show-row', rowId);
    return true;
  }

  function restore() {
    const origin = policy.originOf(getUrl());
    if (restored || !windowState || origin === null) return 0;
    restored = true;
    let count = 0;
    restoring = true;
    try {
      for (const saved of windowState.readOpen()) {
        if (typeof saved.path !== 'string' || !saved.path.startsWith('/') || saved.path.startsWith('//')) continue;
        const before = entries.size;
        openNative({ url: `${origin}${saved.path}`, origin, key: saved.key });
        if (entries.size > before) count += 1;
      }
    } finally {
      restoring = false;
      persist();
    }
    return count;
  }

  function reload() {
    if (rehome()) return;
    for (const e of entries.values()) if (!e.win.isDestroyed()) e.win.webContents.reload();
  }

  function rehome() {
    const current = main();
    if (!current) return false;
    const origin = policy.originOf(getUrl());
    if (origin === null || origin === current.origin) return false;
    return open();
  }

  return {
    open,
    openNative,
    openSolo,
    focusSolo,
    showInMain,
    tearOff,
    restore,
    reload,
    rehome,
    mainWindow: () => (main() ? main().win : null),
    mainOrigin: () => (main() ? main().origin : null),
    anyOpen: () => [...entries.values()].some((e) => !e.win.isDestroyed()),
    isOpen: () => !!main(),
    isFocused: () => !!main() && main().win.isFocused(),
    ownsSender: (sender) => !!sender && [...entries.values()].some((e) => !e.win.isDestroyed() && e.win.webContents === sender),
    raiseSender: (sender) => {
      const entry = sender ? [...entries.values()].find((e) => !e.win.isDestroyed() && e.win.webContents === sender) : null;
      if (!entry) return false;
      raise(entry.win);
      return true;
    },
    chromeOf: (sender) => {
      const e = sender ? [...entries.values()].find((x) => !x.win.isDestroyed() && x.win.webContents === sender) : null;
      return e ? chromeState(e.win) : null;
    },
    sendAll: (channel, value) => {
      for (const e of entries.values()) if (!e.win.isDestroyed()) e.win.webContents.send(channel, value);
    },
    origin: () => {
      const e = main() || [...entries.values()].find((x) => !x.win.isDestroyed());
      return e ? e.origin : null;
    },
    list: () => [...entries].filter(([, e]) => !e.win.isDestroyed()).map(([key, e]) => ({ key, kind: e.kind, title: e.win.getTitle() })),
    setQuitting: (value) => { quitting = value === true; },
  };
}

module.exports = { createWindowHost, MAX_WINDOWS, BLUR_DELAY_MS };
