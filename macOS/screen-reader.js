
'use strict';

const { senderAllowed } = require('./desktop-settings');

const CHANNEL = 'carnivore:screen-reader';

function registerScreenReader({ ipcMain, app, appWindow }) {
  ipcMain.handle(CHANNEL, async (event) => senderAllowed(event, { appWindow }) && app.accessibilitySupportEnabled === true);
  app.on('accessibility-support-changed', (_event, enabled) => appWindow.sendAll(CHANNEL, enabled === true));
}

module.exports = { CHANNEL, registerScreenReader };
