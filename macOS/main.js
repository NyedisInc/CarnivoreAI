const { app, Tray, Menu, shell, nativeImage, clipboard, dialog, nativeTheme, BrowserWindow, globalShortcut } = require('electron');
const path = require('path');
const { applyDevDockIcon } = require('./dev-dock-icon');
const { relocateUserData } = require('./userdata-migration');
const { applyProofMarker, readRunningPurpose } = require('./proof-marker');
applyProofMarker(app);

const userDataMigration = relocateUserData(app);

if (require('./engine-host/service-entry').runIfRequested({ app, argv: process.argv })) return;
require('./local-page').registerLocalPageScheme(require('electron').protocol);
const hasSingleInstanceLock = app.requestSingleInstanceLock();
if (!hasSingleInstanceLock) {
  app.quit();
  return;
}
const crashReports = require('./crash-reports');
crashReports.start({ app, crashReporter: require('electron').crashReporter, fs: require('fs') });
crashReports.wire({ app, process, fs: require('fs'), logPath: path.join(app.getPath('userData'), 'logs', 'crash-events.log') });
const lifecycle = require('./app-lifecycle-policy');
const { wireAppLinks } = require('./app-links');

const ServerManager = require('./server-manager');
const LaunchAgentInstaller = require('./launchagent-installer');

const launchArgs = () => (app.isPackaged
  ? [app.getPath('exe'), lifecycle.LOGIN_LAUNCH_ARG]
  : [app.getPath('exe'), app.getAppPath(), lifecycle.LOGIN_LAUNCH_ARG]);
const { bootstrapIfNeeded } = require('./bootstrap');
const trayTerminal = require('./tray-terminal');
const { createQuitHandler } = require('./quit-sequence');
const { createAppWindow } = require('./app-window');
const { createActivateHandler } = require('./dock-activate');
const qrWindow = require('./qr-window');
const { createStatusWindow } = require('./status-window');
const { createUpdateWindow, windowFacts } = require('./update-window');
const { updateUxFor, createNoticeMemo } = require('./update-ux');
const { createUpdateNotice } = require('./update-notice');
const { tokensCss } = require('./tray-menu/oc-token-values');
const rebindAfterPair = require('./rebind-after-pair');
const { createMember } = require('./member-window');
const { registerDesktopSettings } = require('./desktop-settings');
const { registerOpenInTerminal } = require('./open-in-terminal');
const { registerFolderTargets } = require('./folder-targets');
const { createFinderDrop, wireFinderDrop } = require('./finder-drop');
const { createTrayMenu } = require('./tray-menu/controller');
const { createTrayPresence, readMenuBarIcon } = require('./tray-presence');
const { createWindowState } = require('./window-state');
const { registerWindowIpc } = require('./window-ipc');
const { registerScreenReader } = require('./screen-reader');
const { createQuitNotice } = require('./quit-notice');
const { createEngineDialogs, ENGINE_QUIT } = require('./engine/engine-dialogs');
const loginItems = require('./login-items');
const venvRetire = require('./engine/venv-retire');
const { createLaunchApi } = require('./engine/launch-api');
const { TrayApiClient } = require('./tray-api');
const trayStrings = require('./tray-menu/strings');
const { createDockPresence } = require('./dock-presence');
const { sessionLink } = require('./tray-menu/actions/sessions');


function useRegularActivation() {
  if (process.platform !== 'darwin') return false;
  try {
    app.setActivationPolicy('regular');
    return true;
  } catch (err) {
    console.warn('[dock] could not set the regular activation policy:', err.message);
    return false;
  }
}

function activateForForeground() {
  try {
    app.focus({ steal: true });
  } catch (err) {
    console.warn('[dock] could not activate app:', err.message);
  }
}

function installDialogActivation() {
  for (const name of ['showErrorBox', 'showMessageBox', 'showMessageBoxSync']) {
    const original = dialog[name];
    if (typeof original !== 'function' || original.__frontsApp) continue;
    const wrapped = function (...args) {
      activateForForeground();
      return original.apply(dialog, args);
    };
    wrapped.__frontsApp = true;
    dialog[name] = wrapped;
  }
}

function installWindowActivation() {
  app.on('browser-window-created', (_event, win) => {
    win.on('show', () => {
      activateForForeground();
      try {
        win.moveTop();
        win.focus();
      } catch (err) {
        console.warn('[dock] could not front window:', err.message);
      }
    });
  });
}

useRegularActivation();
applyDevDockIcon({ app, nativeImage });
installDialogActivation();
installWindowActivation();


let trayMenu = null;
let quitIntent = 'app';
let systemQuit = false;
let serverManager = null;

const autoUpdateModule = require('./auto-update');
const updateVerify = require('./update-verify');
const { createUpdateBridge } = require('./update-bridge');
const { createUpdateEngineControl } = require('./update-engine-control');
let autoUpdateInstance = null;

const autoUpdate = {
  get() {
    if (!autoUpdateInstance) {
      const { autoUpdater } = require('electron-updater');
      const configPath = () => (serverManager ? serverManager.getConfigPath() : null);
      autoUpdateInstance = autoUpdateModule.createUpdateController({
        updater: autoUpdater,
        getFeed: autoUpdateModule.createFeedSelector({
          configPath, packaged: app.isPackaged, buildPurpose: readRunningPurpose(), log: (msg) => console.log(msg)
        }),
        getAutoUpdate: () => autoUpdateModule.readAutoUpdate(configPath()),
        isQuiet: () => (trayMenu ? trayMenu.isQuiet() : null),
        verifyUpdate: (zipPath) => updateVerify.verifyStagedUpdate({ zipPath, currentVersion: app.getVersion(), currentPurpose: readRunningPurpose() }),
        beforeInstall: updateEngine.stopForInstall,
        recoverEngine: updateEngine.restartAfterFailedInstall,
        onChange: () => { refreshTray(); autoUpdate.bridge().push(); applyUpdateUx(); },
        log: (msg) => console.log(msg)
      });
    }
    return autoUpdateInstance;
  },
  bridge() {
    if (!autoUpdateBridge) {
      autoUpdateBridge = createUpdateBridge({
        controller: this,
        getApi: () => (trayMenu ? trayMenu.api() : null),
        appVersion: () => app.getVersion(),
        log: (msg) => console.log(msg)
      });
    }
    return autoUpdateBridge;
  },
  getState() { return this.get().getState(); },
  check() { return this.get().check(); },
  applyAutoUpdate() { return this.get().applyAutoUpdate(); },
  isAutoUpdate() { return this.get().isAutoUpdate(); },
  install() {
    if (!this.isAutoUpdate()) updateWindow.open();
    return this.get().install();
  }
};
let autoUpdateBridge = null;

const updateEngine = createUpdateEngineControl({
  getServerManager: () => serverManager, getHost: () => engineHostModule.getHost(), engineApi: () => engineApi(),
  stopStatsPolling: () => { if (statsUpdateInterval) clearTimeout(statsUpdateInterval); },
  startStatsPolling: () => startStatsPolling(), refreshTray: () => refreshTray(),
  setSystemQuit: (v) => { systemQuit = v; }, setWindowQuitting: (v) => appWindow.setQuitting(v)
});

function startAutoUpdate() {
  if (!app.isPackaged) return;
  autoUpdate.get().start();
}
const windowGuard = require('./window-guard-wire').wireWindowGuard({ getManager: () => serverManager, refreshTray: () => refreshTray(), reload: () => appWindow.reload() });
const appWindow = createAppWindow({
  guard: windowGuard,
  getUrl: () => (serverManager ? serverManager.getAppWindowUrl() : null),
  shouldMirror: (ask) => (trayMenu ? trayMenu.mirrorAllowed(ask) : true),
  windowState: createWindowState({
    dir: () => app.getPath('userData'), key: 'main', getDisplays: () => require('electron').screen.getAllDisplays(),
  }),
});
const dockPresence = createDockPresence({ app, Menu, platform: process.platform, sessionLink,
  openApp: (hash) => appWindow.open(hash || undefined), openApproval: (id) => appWindow.openApproval(id),
  isWindowFocused: () => appWindow.isFocused() });
const statusWindow = createStatusWindow({
  BrowserWindow, ipcMain: require('electron').ipcMain, tokensCss,
  getFacts: () => (trayMenu ? trayMenu.statusFacts() : null),
  runAction: (id) => { if (trayMenu) trayMenu.runStatusAction(id); },
});
let uxT = null;
const uxText = (key, params) => (uxT ? uxT(key, params) : key);
const updateWindow = createUpdateWindow({
  BrowserWindow, ipcMain: require('electron').ipcMain, tokensCss,
  getFacts: () => windowFacts(autoUpdate.getState(), uxText),
  runAction: () => { if (trayMenu) trayMenu.runAction({ kind: 'update.install' }); },
});
const updateNotice = createUpdateNotice({
  Notification: require('electron').Notification,
  memo: createNoticeMemo({ dir: () => app.getPath('userData') }), t: uxText,
  onInstall: () => { if (trayMenu) trayMenu.runAction({ kind: 'update.install' }); },
  bannersPosting: async () => (trayMenu ? trayMenu.bannersPosting() : false),
});
function applyUpdateUx() {
  const ux = updateUxFor(autoUpdate.getState(), autoUpdate.isAutoUpdate());
  trayPresence.setIconState(ux.trayIcon);
  updateNotice.onUx(ux);
  updateWindow.update();
}
require('./banners/launch').capture(app);
app.on('before-quit', () => { statusWindow.destroy(); updateWindow.destroy(); appWindow.setQuitting(true); });
const trayPresence = createTrayPresence({
  Tray, nativeImage, nativeTheme, iconPath: path.join(__dirname, 'assets', 'iconTemplate.png'),
  updateIconPath: path.join(__dirname, 'assets', 'iconUpdate.png'),
  onTheme: () => {
    if (trayMenu) trayMenu.invalidateIcons();
    refreshTray();
  },
  log: (msg) => console.log(`[tray-presence] ${msg}`),
});
const loadStrings = () => trayStrings.loadTranslator(trayStrings.resolveClientDir({
  isPackaged: app.isPackaged, resourcesPath: process.resourcesPath, appDir: __dirname,
}));
loadStrings().then((t) => { uxT = t; }).catch((err) => console.warn('[update-ux] strings not loaded:', err && err.message));
const quitNotice = createQuitNotice({ dir: () => app.getPath('userData'), dialog, loadTranslator: loadStrings });
const engineDialogs = createEngineDialogs({ dialog, loadTranslator: loadStrings, activate: () => app.focus({ steal: true }) });
const engineApi = () => (trayMenu ? trayMenu.api() : null);
const launchApi = createLaunchApi({ serverManager: { getLocalApiUrl: () => serverManager.getLocalApiUrl(), getCurrentOtp: () => require('./tray-pairing-hold').trayOtp(serverManager) }, member: { isJoined: () => member.isJoined(), tokens: () => member.tokens() }, TrayApiClient, trayApi: engineApi });

function quitWithoutNotice() {
  systemQuit = true;
  app.quit();
}

function quitAndStopEngine() {
  quitIntent = 'engine';
  app.quit();
}
let launchAgentInstaller = null, loginService = null, freshInstall = false;
const loginSyncArgs = () => ({ strategy: engineHostModule.getHost().name, userData: app.getPath('userData'), installer: launchAgentInstaller,
  service: loginService, fresh: freshInstall, windowAtLogin: loginItems.readLogin({ installer: launchAgentInstaller, dir: app.getPath('userData') }).window === true });
const engineHostModule = require('./engine-host');
const loginServiceFor = () => (engineHostModule.getHost().name === 'launchd-agent' ? loginService : null);
const member = createMember({
  ipcMain: require('electron').ipcMain, getServerManager: () => serverManager, appWindow, rebindAfterPair,
  rebindDeps: () => rebindDeps(), getInstaller: () => launchAgentInstaller, launchArgs: () => launchArgs(),
  dataDir: () => app.getPath('userData'), onChange: () => refreshTray(),
});
const desktopSettings = registerDesktopSettings({
  ipcMain: require('electron').ipcMain, appWindow, app, Notification: require('electron').Notification, shell,
  getInstaller: () => launchAgentInstaller, launchArgs: () => launchArgs(), dataDir: () => app.getPath('userData'), getLoginService: loginServiceFor,
  getServerManager: () => serverManager,
  bannersPosting: async () => (trayMenu ? trayMenu.bannersPosting() : false),
  beforeState: () => links.syncHotkey(),
});
registerWindowIpc({ ipcMain: require('electron').ipcMain, appWindow });
registerScreenReader({ ipcMain: require('electron').ipcMain, app, appWindow });
const openInTerminal = registerOpenInTerminal({
  ipcMain: require('electron').ipcMain, appWindow, dialog, api: engineApi, dataDir: () => app.getPath('userData'), loadTranslator: loadStrings,
});
registerFolderTargets({
  ipcMain: require('electron').ipcMain, appWindow, dialog, shell, api: engineApi, loadTranslator: loadStrings,
  spawn: require('child_process').spawn, dataDir: () => app.getPath('userData'),
});
let launchAgentMigration = null;
let launchAgentUpgrade = null;
let statsUpdateInterval = null;
let currentStats = null;

const BOOTSTRAP_TOOLTIPS = {
  'checking': 'Carnivore: checking setup...',
  'syncing-assets': 'Carnivore: syncing bundled files...',
  'preparing': 'Carnivore: preparing first-run...',
  'copying-files': 'Carnivore: copying server files...',
  'creating-venv': 'Carnivore: creating Python venv...',
  'installing-deps': 'Carnivore: installing dependencies (60-120s)...',
  'generating-secrets': 'Carnivore: generating auth secrets...',
  'generating-config': 'Carnivore: writing config...',
  'ready': 'Carnivore',
};

function rebindDeps() {
  return { serverManager, offerTakeOwnership, reportStartFailure, dialog, appWindow, waitForServerHealth, whenGuardClear: windowGuard.whenClear };
}

async function waitForServerHealth(timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const health = await serverManager.getHealth();
    if (health) return true;
    await new Promise(r => setTimeout(r, 500));
  }
  return false;
}

function showAboutDialog() {
  require('./about-window').showAboutDialog({ app, BrowserWindow, shell });
}

app.on('window-all-closed', () => {
  if (lifecycle.windowCloseDecision({ platform: process.platform }).quitApp) app.quit();
});

app.whenReady().then(async () => {
  console.log('Carnivore starting...');
  trayTerminal.sweepAtStartup();
  void require('./app-menu').installApplicationMenu({ app, Menu, shell, appWindow, showAbout: showAboutDialog, quitAndStopEngine,
    waiting: () => (trayMenu ? trayMenu.longestWaiting() : null), loadTranslator: loadStrings,
    exportDiagnostics: () => { if (trayMenu) trayMenu.runAction({ kind: 'server.export_diagnostics' }); else console.warn('[app-menu] export diagnostics before the tray menu started'); } });
  require('electron').powerMonitor.on('shutdown', () => { systemQuit = true; });
  links.start();

  serverManager = new ServerManager();
  serverManager.onStartNote = (note) => loadStrings().then((t) => { if (!serverManager.startWait) return; serverManager.startNoteText = t(note.key, note.params); console.log(`[server] ${serverManager.startNoteText}`); refreshTray(); });
  startAutoUpdate();
  launchAgentInstaller = new LaunchAgentInstaller();
  loginService = require('./engine-host/service-control').createServiceControl({ app, execFile: require('child_process').execFile, uid: process.getuid() });
  engineHostModule.setHostFromSettings({ env: process.env, userData: app.getPath('userData'), service: loginService, log: console.log });
  require('./engine-host/teardown').installTermHandler({ proc: process, role: 'window', quit: () => app.quit(), onSignal: () => { systemQuit = true; }, log: console.log });
  serverManager.serviceOwnsEngine = () => engineHostModule.getHost().serviceOwnsEngine();

  launchAgentMigration = launchAgentInstaller.migrateLegacyIfNeeded(launchArgs());
  if (launchAgentMigration.ran) console.log('[launchagent] migration:', launchAgentMigration.details);
  launchAgentUpgrade = launchAgentInstaller.upgradePlistIfNeeded(launchArgs());
  if (launchAgentUpgrade.ran) console.log('[launchagent] upgrade:', launchAgentUpgrade.details);

  try {
    freshInstall = !require('fs').existsSync(path.join(app.getPath('userData'), 'server', '.env'));
    require('./engine-host/login-sync').syncLogin({ ...loginSyncArgs(), recordOnly: true });
  } catch (err) {
    console.warn('[login-handoff] could not record the previous choice:', err.message);
  }
  venvRetire.beginLaunch({ userData: app.getPath('userData'), hasPayload: !!serverManager.payload });

  startTrayMenu();

  const serverDir = path.join(app.getPath('userData'), 'server');
  const bundleResourcesDir = app.isPackaged
    ? path.join(app.getAppPath(), '..')
    : path.join(__dirname, '..');
  const bootstrapResult = await bootstrapIfNeeded({
    serverDir,
    bundleResourcesDir,
    isPackaged: app.isPackaged,
    appVersion: app.getVersion(),
    onStateChange: (state) => {
      const tooltip = BOOTSTRAP_TOOLTIPS[state] || `Carnivore: ${state}`;
      trayPresence.facade.setToolTip(tooltip);
      console.log('[bootstrap]', state);
    },
  });

  if (bootstrapResult.status === 'python-missing') {
    const { dialog, clipboard } = require('electron');
    const result = await dialog.showMessageBox({
      type: 'error',
      title: 'Python 3.12+ required',
      message: 'Carnivore needs Python 3.12 or later.',
      detail: 'Install via Homebrew:\n\n  brew install python@3.12\n\nThen re-launch Carnivore.',
      buttons: ['Copy command', 'Quit'],
      defaultId: 0,
    });
    if (result.response === 0) {
      clipboard.writeText('brew install python@3.12');
    }
    quitWithoutNotice();
    return;
  }

  if (bootstrapResult.status === 'python-too-new') {
    const { dialog, clipboard } = require('electron');
    const result = await dialog.showMessageBox({
      type: 'error',
      title: 'Python version not supported yet',
      message: 'Carnivore is proven on Python 3.12 to 3.14 only.',
      detail: `${bootstrapResult.details}\n\nInstall via Homebrew:\n\n  brew install python@3.12\n\nThen re-launch Carnivore.`,
      buttons: ['Copy command', 'Quit'],
      defaultId: 0,
    });
    if (result.response === 0) {
      clipboard.writeText('brew install python@3.12');
    }
    quitWithoutNotice();
    return;
  }

  if (bootstrapResult.status === 'error') {
    const { dialog } = require('electron');
    dialog.showErrorBox(
      'Carnivore setup failed',
      bootstrapResult.details || 'Unknown error during first-run provisioning. Check Console.app for [bootstrap] logs.'
    );
    quitWithoutNotice();
    return;
  }

  try {
    require('./engine-host/login-sync').syncLoginSafe(loginSyncArgs());
    await engineHostModule.getHost().start(serverManager);
  } catch (err) {
    await reportStartFailure(err);
  }
  if (systemQuit) return;

  // Force immediate health check
  const health = serverManager.startBlockedReason
    ? null
    : await serverManager.getHealth();
  if (health && serverManager.getState() !== 'running') {
    console.log('Initial health check succeeded, marking as running');
    serverManager.state = 'running';
    if (!serverManager.startTime) {
      serverManager.startTime = Date.now();
    }
  }

  void venvRetire.recordVenvOutcome({ serverManager, userData: app.getPath('userData'), serverDir });

  refreshTray();

  startStatsPolling();

  // once per launch
  rebindAfterPair.maybeAutoOpenFirstRun({ serverManager, appWindow, waitForServerHealth, settle: () => rebindAfterPair.settleBeforeFirstWindow(rebindDeps()) });
  if (!engineHostModule.getHost().serviceOwnsEngine()) rebindAfterPair.startWatch(rebindDeps());
  openWindowForThisLaunch();

  if (userDataMigration.migrated || launchAgentMigration.migrated) {
    dialog.showMessageBox({
      type: 'info',
      title: 'Carnivore replaces Cloude Code',
      message: 'This app moved from Cloude Code to Carnivore.',
      detail: 'Your sessions, database and settings moved with it, and ' +
              'auto-launch at login now points at this app. The old ' +
              'Cloude Code.app in /Applications is no longer used and can ' +
              'be trashed.',
      buttons: ['OK'],
    });
  }

  console.log('App ready!');
});

function openWindowForThisLaunch() {
  const windowAtLogin = loginItems.readLogin({ installer: launchAgentInstaller, dir: app.getPath('userData') }).window === true;
  const launch = lifecycle.launchDecision({ argv: process.argv, windowAtLogin, startBlocked: !!serverManager.startBlockedReason });
  console.log(`[launch] ${launch.loginLaunch ? 'login launch' : 'user launch'}, window ${launch.openWindow ? 'opens' : 'stays closed'}`);
  if (!launch.openWindow) return;
  waitForServerHealth().then(async (up) => {
    if (!up) return; await rebindAfterPair.settleBeforeFirstWindow(rebindDeps());
    if (serverManager.startBlockedReason) return;
    if (!appWindow.isOpen()) appWindow.open();
    appWindow.restore();
  }).catch((err) => console.warn('[launch] window not opened:', err && err.message));
}

function refreshTray() {
  if (trayMenu) trayMenu.refresh();
}

function startTrayMenu() {
  trayMenu = createTrayMenu({
    electron: { app, Menu, shell, clipboard, dialog, BrowserWindow, nativeImage, Notification: require('electron').Notification, powerMonitor: require('electron').powerMonitor },
    onListing: (listing, env) => dockPresence.update(listing, env),
    nativeTheme, statusWindow, tray: trayPresence.facade, serverManager, member, appWindow, launchArgs,
    launchAgentInstaller: require('./engine-host/tray-login').trayLogin({ strategy: engineHostModule.getHost().name, installer: launchAgentInstaller, service: loginService, userData: app.getPath('userData') }), autoUpdate, rebindAfterPair,
    rebindDeps, offerTakeOwnership, reportStartFailure, showAbout: showAboutDialog, qrWindow, openInTerminal,
    setQuitIntent: (intent) => { if (lifecycle.QUIT_INTENTS.includes(intent)) quitIntent = intent; },
    stopStatsPolling: () => { if (statsUpdateInterval) clearTimeout(statsUpdateInterval); },
    getHealth: () => currentStats,
    onAppUpdate: (result) => autoUpdate.bridge().onServerStatus(result),
    onDesktopPrefs: (result) => {
      if (result && result.status === 'ok' && result.data && result.data.values) {
        trayPresence.apply(result.data.values.desktop_menu_bar_icon);
      }
      links.onDesktopPrefs(result);
    },
  });
  trayPresence.apply(readMenuBarIcon(serverManager.getConfigPath()));
}

const STEADY_HEALTH_POLL_MS = 15000;

function startStatsPolling() {
  let pollInterval = STEADY_HEALTH_POLL_MS;
  let fastPollCount = 0;
  const maxFastPolls = 12;

  const poll = async () => {
    const state = serverManager.getState();

    if (state === 'starting' && fastPollCount < maxFastPolls) {
      pollInterval = 2000;
      fastPollCount++;
    } else {
      pollInterval = STEADY_HEALTH_POLL_MS;
      fastPollCount = 0;
    }
    if (windowGuard.fastPoll(state)) pollInterval = windowGuard.interval;

    if (state === 'running' || state === 'starting' || serverManager.isProcessRunning()) {
      const health = await serverManager.getHealth();
      serverManager.superviseTick(Boolean(health));
      await windowGuard.onHealth(Boolean(health), health);
      if (health) {
        currentStats = health;
        member.onHealth();
        if (state !== 'running') {
          console.log('Health check succeeded, marking as running');
          serverManager.state = 'running';
          if (!serverManager.startTime) {
            serverManager.startTime = Date.now();
          }
        }
      } else {
        if (serverManager.isProcessRunning() || serverManager.startWait) {
          if (state !== 'starting') {
            console.log('Process running but health check failed, marking as starting');
            serverManager.state = 'starting';
          }
        } else {
          if (state !== 'stopped') {
            console.log('No process detected and health check failed, marking as stopped');
            serverManager.state = 'stopped';
            serverManager.startTime = null;
          }
        }
        currentStats = null;
      }
    } else {
      currentStats = null;
      if (state !== 'stopped') {
        serverManager.state = 'stopped';
        serverManager.startTime = null;
      }
      await windowGuard.onStopped();
      await require('./engine-host/service-watch').watchForService(serverManager).catch((error) => console.warn('[supervisor] service re-adopt failed:', error && error.message));
    }

    if (trayMenu) {
      trayMenu.onHealth(currentStats)
        .then(() => { if (currentStats) { links.onServerUp(); void finderDrop.onServerUp(); } })
        .catch((error) => console.warn('[tray-menu] health hand-off failed:', error && error.message));
    }

    if (statsUpdateInterval) {
      clearTimeout(statsUpdateInterval);
    }
    statsUpdateInterval = setTimeout(poll, pollInterval);
  };

  poll();
}

/* this app did not start */
async function offerTakeOwnership(action, result) {
  const title =
    action === 'restart'
      ? 'Carnivore did not start this server'
      : 'Carnivore did not start this server';

  if (!result.offerTakeOwnership) {
    dialog.showErrorBox(title, result.reason);
    return;
  }

  const verb = action === 'restart' ? 'Restart' : 'Stop';
  const answer = await dialog.showMessageBox({
    type: 'warning',
    title,
    message: title,
    detail:
      `${result.reason}\n\n` +
      (result.pid ? `The running server is PID ${result.pid}.\n\n` : '') +
      `${verb} it anyway and let Carnivore take ownership? Claude sessions ` +
      'running in tmux keep running - tmux outlives the server - but anything ' +
      'connected through the web client will be disconnected.',
    buttons: ['Leave it alone', `${verb} it anyway`],
    defaultId: 0,
    cancelId: 0,
  });

  if (answer.response !== 1) {
    console.log(`User declined to take ownership for ${action}.`);
    return;
  }

  try {
    if (action === 'restart') {
      await serverManager.restart({ takeOwnership: true });
    } else {
      await serverManager.stop({ takeOwnership: true });
    }
  } catch (err) {
    dialog.showErrorBox(`Carnivore could not ${action} the server`, err.message);
  }
  refreshTray();
}

/* ADOPTION_REFUSED */
async function reportStartFailure(err) {
  if (!err || err.code !== 'ADOPTION_REFUSED') {
    dialog.showErrorBox('Carnivore could not start the server', err.message);
    return;
  }

  const choice = await engineDialogs.askRestart({ runningVersion: err.runningVersion, bundleVersion: err.bundleVersion });
  if (choice === ENGINE_QUIT) {
    console.log('User chose to quit and leave the other engine running.');
    quitWithoutNotice();
    return;
  }

  try {
    const restarted = await serverManager.restartAdoptedEngine({ getApi: launchApi });
    if (!restarted.ok) await engineDialogs.showRestartFailed(restarted.error || restarted.outcome || 'unknown');
  } catch (restartErr) {
    await engineDialogs.showRestartFailed(restartErr.message);
  }
  refreshTray();
}

app.on(
  'before-quit',
  createQuitHandler({
    teardown: async () => {
      const plan = lifecycle.quitPlan({
        intent: quitIntent, noticeShown: quitNotice.alreadyShown(),
        engineSurvivesQuit: engineHostModule.getHost().survivesQuit(), systemQuit,
      });
      if (plan.showNotice) await quitNotice.show();
      if (serverManager) serverManager.beginQuit();
      if (plan.stopEngine && serverManager) {
        const result = await engineHostModule.getHost().stop(serverManager, { getApi: engineApi });
        if (result.stopped === false) {
          serverManager.cancelQuit();
          appWindow.setQuitting(false);
          quitIntent = 'app';
          await engineDialogs.showStopFailed(result.error || result.outcome || 'unknown');
          return { cancelQuit: true };
        }
      }
      if (statsUpdateInterval) {
        clearTimeout(statsUpdateInterval);
      }
      if (trayMenu) {
        trayMenu.stop();
      }
      return null;
    },
    quit: () => app.quit(),
    log: (msg) => console.log(msg),
    onError: (msg, err) => console.error(msg, err && err.message),
  })
);

const onActivate = createActivateHandler({
  appWindow,
  isServerRunning: () => !!serverManager && serverManager.getState() === 'running',
  getTray: () => trayPresence.tray(),
  getTrayMenu: () => (trayMenu ? trayMenu.menuForDock() : null),
  statusWindow,
});
app.on('activate', onActivate);

const links = wireAppLinks({
  app, globalShortcut, appWindow, trayMenu: () => trayMenu, onActivate: () => onActivate(),
  setHotkeyStatus: (status) => desktopSettings.setHotkeyStatus(status),
});

const finderDrop = wireFinderDrop({
  app, opener: () => createFinderDrop({ api: engineApi, dialog, loadTranslator: loadStrings, appWindow }),
});

app.on('second-instance', (_event, argv) => links.secondInstance(argv));
