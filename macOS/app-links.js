
'use strict';

const path = require('path');
const { createLinkRouter } = require('./link-router');
const { createHotkey, acceleratorOf, readPreference } = require('./hotkey');
const { createHotkeyStore } = require('./hotkey-store');
const { createPressAction } = require('./hotkey-action');
const { handleSecondInstance } = require('./second-instance');

const SCHEME = 'carnivore';

function registerProtocol(app) {
  try {
    const ok = process.defaultApp && process.argv[1]
      ? app.setAsDefaultProtocolClient(SCHEME, process.execPath, [path.resolve(process.argv[1])])
      : app.setAsDefaultProtocolClient(SCHEME);
    if (!ok) console.warn('[deep-link] could not register as the carnivore:// handler');
  } catch (error) {
    console.warn('[deep-link] protocol registration failed:', error && error.message);
  }
}

function wireAppLinks({ app, globalShortcut, appWindow, trayMenu, onActivate, setHotkeyStatus }) {
  const router = createLinkRouter({ appWindow });
  const press = createPressAction({
    appWindow, onActivate, waiting: () => { const tray = trayMenu(); return tray ? tray.longestWaiting() : null; },
  });
  let known = null;
  const hotkey = createHotkey({
    globalShortcut, onFire: press, report: setHotkeyStatus, readAccelerator: async () => known,
    store: createHotkeyStore(() => app.getPath('userData')),
  });

  app.on('open-url', (event, url) => {
    event.preventDefault();
    router.handle(url);
  });
  app.on('will-quit', () => hotkey.stop());

  return {
    start() {
      if (process.platform === 'darwin') registerProtocol(app);
      void hotkey.refresh();
    },
    secondInstance(argv) {
      const intent = handleSecondInstance(argv);
      let handled = false;
      for (const link of intent.links) handled = router.handle(link).ok || handled;
      if (intent.toggle) {
        press();
        handled = true;
      }
      if (!handled && intent.focus && app.isReady()) onActivate();
    },
    onServerUp: () => router.replay(),
    onDesktopPrefs(result) {
      const accelerator = acceleratorOf(result && result.status === 'ok' && result.data ? result.data.values : null);
      if (accelerator === null) return;
      known = accelerator;
      void hotkey.refresh();
    },
    async syncHotkey() {
      const tray = trayMenu();
      const accelerator = await readPreference(tray ? tray.api() : null);
      if (accelerator !== null) known = accelerator;
      return hotkey.refresh();
    },
  };
}

module.exports = { SCHEME, wireAppLinks };
