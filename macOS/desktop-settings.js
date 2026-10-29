
'use strict';

const loginItems = require('./login-items');
const permission = require('./notification-permission');
const focus = require('./banners/focus');
const policy = require('./app-window-policy');
const strings = require('./tray-menu/strings');
const tlsStatus = require('./tls-status');

const CHANNELS = Object.freeze({
  state: 'carnivore:desktop-state',
  login: 'carnivore:set-login-item',
  request: 'carnivore:request-notifications',
  openSettings: 'carnivore:open-notification-settings',
  openFocus: 'carnivore:open-focus-settings',
});

function senderAllowed(event, deps) {
  if (!event || !event.senderFrame || !event.sender || event.senderFrame !== event.sender.mainFrame) return false;
  const origin = deps.appWindow.origin();
  return deps.appWindow.ownsSender(event.sender) && origin !== null && policy.isLoopbackOrigin(origin)
    && policy.originOf(event.senderFrame.url) === origin;
}

function registerDesktopSettings(deps) {
  let hotkey = { registered: null, error: null };
  let translator = null;
  const translate = () => {
    if (!translator) {
      const clientDir = strings.resolveClientDir({ isPackaged: deps.app.isPackaged, resourcesPath: process.resourcesPath, appDir: __dirname });
      translator = strings.loadTranslator(clientDir).catch((error) => { translator = null; throw error; });
    }
    return translator;
  };
  const tlsLevel = () => {
    const manager = deps.getServerManager();
    const url = manager ? manager.getPublishedUrl() : null;
    return url ? tlsStatus.evaluateBinding({ url }).level : tlsStatus.LEVEL_UNKNOWN;
  };
  const bannersPosting = async () => {
    try {
      return deps.bannersPosting ? (await deps.bannersPosting()) === true : false;
    } catch (error) {
      return false;
    }
  };
  const snapshot = async () => ({
    login: loginItems.readLogin({ installer: deps.getInstaller(), dir: deps.dataDir(), service: deps.getLoginService ? deps.getLoginService() : null }),
    notifications: { state: permission.readState({ dir: deps.dataDir() }), waiting: permission.isWaiting({ dir: deps.dataDir() }), banners: { posting: await bannersPosting() } },
    hotkey,
    network: { tls: tlsLevel() },
  });
  const guarded = (channel, run) => deps.ipcMain.handle(channel, async (event, ...args) => {
    if (!senderAllowed(event, deps)) return null;
    return run(...args);
  });

  guarded(CHANNELS.state, async () => {
    try {
      if (deps.beforeState) await deps.beforeState();
    } catch (error) {
      console.warn('[desktop-settings] hotkey refresh failed:', error && error.message);
    }
    return snapshot();
  });
  guarded(CHANNELS.login, (which, enabled) => {
    if (!loginItems.validLoginRequest(which, enabled)) return null;
    return loginItems.setLogin({ installer: deps.getInstaller(), launchArgs: deps.launchArgs, dir: deps.dataDir(), which, enabled, service: deps.getLoginService ? deps.getLoginService() : null });
  });
  guarded(CHANNELS.request, async () => {
    const t = await translate();
    const state = permission.request({ dir: deps.dataDir(), Notification: deps.Notification, t });
    return { state, waiting: permission.isWaiting({ dir: deps.dataDir() }) };
  });
  guarded(CHANNELS.openSettings, async () => {
    await deps.shell.openExternal(permission.SETTINGS_URL);
  });
  guarded(CHANNELS.openFocus, () => focus.openFocusSettings(deps.shell));
  return { setHotkeyStatus: (status) => { hotkey = { registered: status.registered, error: status.error }; } };
}

module.exports = { CHANNELS, senderAllowed, registerDesktopSettings };
