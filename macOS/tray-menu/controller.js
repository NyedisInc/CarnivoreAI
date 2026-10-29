
'use strict';

const path = require('path');
const childProcess = require('child_process');
const fs = require('fs');
const strings = require('./strings');
const { loadStatusLed } = require('./need-you');
const { longestWaiting } = require('./longest-waiting');
const { menuCapabilities } = require('./capabilities');
const { buildMenuModel } = require('./model');
const { createPresenter } = require('./presenter');
const { createLedIcons } = require('./led-icons');
const { statusFacts, actionForClick } = require('./status-facts');
const { createTrayData } = require('./data');
const { gatherSnapshot, trayStatusInput } = require('./snapshot');
const { createDispatcher } = require('./actions');
const trayStatus = require('../tray-status');
const terminalOpen = require('../terminal-open');
const trayTerminal = require('../tray-terminal');
const { pickTmuxForSocket } = require('../engine/tmux-pick');
const { TrayApiClient } = require('../tray-api');
const { createBanners } = require('../banners');
const bannerLaunch = require('../banners/launch');
const { createScreenLock } = require('../screen-lock');
const notificationPermission = require('../notification-permission');

function createNamedIcons(nativeImage) {
  const files = { update: path.join(__dirname, '..', 'assets', 'iconUpdateMenu.png') };
  const cache = new Map();
  return {
    get(name) {
      if (!files[name] || !nativeImage) return undefined;
      if (!cache.has(name)) {
        const image = nativeImage.createFromPath(files[name]);
        cache.set(name, image.isEmpty() ? undefined : image);
      }
      return cache.get(name);
    },
  };
}

function createTrayMenu(deps) {
  const { electron, tray, serverManager } = deps;
  const clientDir = strings.resolveClientDir({ isPackaged: electron.app.isPackaged, resourcesPath: process.resourcesPath,
    appDir: path.join(__dirname, '..') });
  let t = strings.createTranslator(null, (entry) => String(entry));
  strings.loadTranslator(clientDir).then((loaded) => { t = loaded; }).catch((error) => {
    console.error('[tray-menu] string catalog did not load:', error && error.message);
  });
  let led = null;
  try {
    led = loadStatusLed(clientDir);
  } catch (error) {
    console.error('[tray-menu] status LED module did not load; Need You is off:', error && error.message);
  }

  let tmuxTools = null;
  const resolveTmux = async (serverDir) => {
    const socketPath = trayTerminal.serverSocketPath(serverDir, process.getuid());
    if (!tmuxTools) tmuxTools = await terminalOpen.resolveTools(terminalOpen.liveDeps(), socketPath);
    return (await pickTmuxForSocket(tmuxTools.tmuxCandidates, fs.existsSync(socketPath) ? socketPath : null, terminalOpen.liveDeps())) || tmuxTools.tmux;
  };
  const portDeps = () => ({ execFile: childProcess.execFile, myUid: process.getuid(), myPid: process.pid,
    kill: process.kill.bind(process), sleep: (ms) => new Promise((r) => setTimeout(r, ms)) });

  let presenter = null;
  const snapshot = (optionKey) => gatherSnapshot({ serverManager, data, autoUpdate: deps.autoUpdate, member: deps.member,
    launchAgentInstaller: deps.launchAgentInstaller, health: deps.getHealth(), appVersion: electron.app.getVersion(), optionKey });

  function refresh() {
    if (!presenter) return;
    tray.setToolTip(trayStatus.buildTooltip(trayStatusInput(snapshot(false))));
    presenter.refresh();
    if (deps.onListing) deps.onListing(data.parts().listing, { led, t: (k, p) => t(k, p) });
    if (deps.statusWindow) deps.statusWindow.update();
  }

  let banners = null;
  const data = createTrayData({ serverManager, member: deps.member, TrayApiClient, onChange: refresh, portDeps,
    offlineDeps: terminalOpen.liveDeps, resolveTmux,
    onAppUpdate: (result) => (deps.onAppUpdate ? deps.onAppUpdate(result) : undefined),
    onDesktopPrefs: (result) => (deps.onDesktopPrefs ? deps.onDesktopPrefs(result) : undefined),
    onApprovals: () => { if (banners) banners.onApprovals(); } });
  banners = createBanners({ platform: process.platform, getApi: () => data.api(), Notification: electron.Notification,
    readPermission: () => notificationPermission.readState({ dir: electron.app.getPath('userData') }), t: (k, p) => t(k, p),
    isWindowFocused: () => !!(deps.appWindow && deps.appWindow.isFocused && deps.appWindow.isFocused()),
    openApproval: (sessionId) => { if (deps.appWindow) deps.appWindow.openApproval(sessionId); },
    isLocked: createScreenLock(electron.powerMonitor).isLocked });
  void banners.coldLaunch(bannerLaunch.take()).catch((error) => console.warn('[banners] cold launch failed:', error && error.message));
  if (typeof electron.app.on === 'function') electron.app.on('browser-window-blur', () => banners.onApprovals());

  const dispatch = createDispatcher({
    ...electron, fs, exec: childProcess.exec, execFile: childProcess.execFile, serverManager, appWindow: deps.appWindow,
    launchAgentInstaller: deps.launchAgentInstaller, launchArgs: deps.launchArgs, autoUpdate: deps.autoUpdate, data,
    rebindAfterPair: deps.rebindAfterPair, rebindDeps: deps.rebindDeps, offerTakeOwnership: deps.offerTakeOwnership,
    reportStartFailure: deps.reportStartFailure, showAbout: deps.showAbout, qrWindow: deps.qrWindow,
    getTray: () => tray, refresh, stopStatsPolling: deps.stopStatsPolling, portDeps, t: (k, p) => t(k, p),
    setQuitIntent: deps.setQuitIntent, openInTerminal: deps.openInTerminal,
  });

  const ledIcons = electron.nativeImage && deps.nativeTheme
    ? createLedIcons({ nativeImage: electron.nativeImage, nativeTheme: deps.nativeTheme }) : null;
  const namedIcons = createNamedIcons(electron.nativeImage);
  const model = (optionKey) => buildMenuModel(snapshot(optionKey), { t, led });

  presenter = createPresenter(process.platform, {
    tray, Menu: electron.Menu, dispatch, iconFor: ledIcons ? ledIcons.iconFor : null,
    namedIcon: (name) => namedIcons.get(name),
    caps: menuCapabilities(process.platform, process.getSystemVersion ? process.getSystemVersion() : ''),
    buildItems: ({ optionKey }) => model(optionKey),
    onOpen: () => { data.refreshSide(); },
  });
  refresh();

  return {
    refresh,
    api: () => data.api(),
    isQuiet: () => {
      const { listing } = data.parts();
      if (!listing.rows || !listing.reachable) return null;
      return !listing.rows.some((r) => r && (r.activity_status === 'working' || r.activity_status === 'working_subagent'));
    },
    longestWaiting: () => longestWaiting(data.parts().listing.rows, led),
    onHealth: (health) => data.onHealth(health),
    bannersPosting: () => banners.posting(),
    mirrorAllowed: (askSessionId) => banners.mirrorAllowed(askSessionId),
    menuForDock: () => presenter.menuForDock(),
    statusFacts: () => statusFacts(snapshot(false), model(false), t),
    runAction: (action) => dispatch(action),
    runStatusAction(id) {
      const action = actionForClick(model(false), id);
      if (action) dispatch(action);
    },
    invalidateIcons: () => { if (ledIcons) ledIcons.invalidate(); },
    stop: () => { banners.closeAll(); data.stop(); },
  };
}

module.exports = { createTrayMenu };
