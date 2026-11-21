
'use strict';

const carnivore = require('./carnivore');
const file = require('./file');
const edit = require('./edit');
const view = require('./view');
const go = require('./go');
const session = require('./session');
const win = require('./window');
const help = require('./help');
const { explicitAccelerators } = require('./chords');

const MENUS = [carnivore, file, edit, view, go, session, win, help];

function buildTemplate(deps) {
  const built = MENUS.map((menu) => (menu === go ? null : menu.build(deps)));
  const taken = explicitAccelerators(built.filter(Boolean));
  return built.map((entry, i) => entry || MENUS[i].build({ ...deps, taken }));
}

async function installApplicationMenu(deps) {
  const log = deps.log || ((msg) => console.warn(msg));
  let current = (key) => key;
  let recent = [];
  let keys = {};
  const install = (t) => {
    current = t;
    deps.Menu.setApplicationMenu(deps.Menu.buildFromTemplate(buildTemplate({
      t, appName: deps.app.name, isPackaged: deps.app.isPackaged, appWindow: deps.appWindow, showAbout: deps.showAbout,
      quitAndStopEngine: deps.quitAndStopEngine, waiting: deps.waiting, exportDiagnostics: deps.exportDiagnostics,
      openUrl: (url) => { void deps.shell.openExternal(url); }, recent: () => recent, keys: () => keys,
    })));
  };
  if (deps.ipcMain && deps.fromMainPage) {
    deps.ipcMain.on(go.RECENT_CHANNEL, (event, labels) => {
      if (!event || !event.sender || event.senderFrame !== event.sender.mainFrame || !deps.fromMainPage(event)) return;
      const next = go.cleanRecent(labels);
      if (!next || next.join('\n') === recent.join('\n')) return;
      recent = next;
      install(current);
    });
    deps.ipcMain.on(go.KEYS_CHANNEL, (event, chords) => {
      if (!event || !event.sender || event.senderFrame !== event.sender.mainFrame || !deps.fromMainPage(event)) return;
      const next = go.cleanKeys(chords);
      if (!next || JSON.stringify(next) === JSON.stringify(keys)) return;
      keys = next;
      install(current);
    });
  }
  install(current);
  try {
    install(await deps.loadTranslator());
  } catch (err) {
    log(`[app-menu] string catalog did not load, menu keeps its keys: ${err && err.message}`);
  }
}

module.exports = { buildTemplate, installApplicationMenu };
