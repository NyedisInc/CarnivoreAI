
'use strict';

const carnivore = require('./carnivore');
const file = require('./file');
const edit = require('./edit');
const view = require('./view');
const session = require('./session');
const win = require('./window');
const help = require('./help');

const MENUS = [carnivore, file, edit, view, session, win, help];

function buildTemplate(deps) {
  return MENUS.map((menu) => menu.build(deps));
}

async function installApplicationMenu(deps) {
  const log = deps.log || ((msg) => console.warn(msg));
  const install = (t) => deps.Menu.setApplicationMenu(deps.Menu.buildFromTemplate(buildTemplate({
    t, appName: deps.app.name, isPackaged: deps.app.isPackaged, appWindow: deps.appWindow, showAbout: deps.showAbout,
    quitAndStopEngine: deps.quitAndStopEngine, waiting: deps.waiting, exportDiagnostics: deps.exportDiagnostics,
    openUrl: (url) => { void deps.shell.openExternal(url); },
  })));
  install((key) => key);
  try {
    install(await deps.loadTranslator());
  } catch (err) {
    log(`[app-menu] string catalog did not load, menu keeps its keys: ${err && err.message}`);
  }
}

module.exports = { buildTemplate, installApplicationMenu };
