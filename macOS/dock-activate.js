/* popUpContextMenu() */

'use strict';

const { dockClickOrder } = require('./app-lifecycle-policy');

function createActivateHandler({ appWindow, isServerRunning, getTray, getTrayMenu, statusWindow }) {
  return function onActivate() {
    const tray = getTray();
    const steps = dockClickOrder({
      windowOpen: appWindow.isOpen(),
      serverRunning: isServerRunning(),
      statusWindowAvailable: Boolean(statusWindow),
      trayAvailable: Boolean(tray),
    });
    for (const step of steps) {
      if (step === 'raise' && appWindow.open()) return;
      if (step === 'open-window') {
        if (statusWindow) statusWindow.close();
        if (appWindow.open()) return;
      }
      if (step === 'open-status' && statusWindow.open()) return;
      if (step === 'tray-menu') {
        const menu = getTrayMenu();
        if (menu) tray.popUpContextMenu(menu);
        return;
      }
    }
  };
}

module.exports = { createActivateHandler };
