
'use strict';

function build({ t, appName, appWindow, showAbout, quitAndStopEngine }) {
  return {
    id: 'carnivore',
    label: appName,
    submenu: [
      { id: 'carnivore.about', label: t('menubar.about'), click: () => showAbout() },
      { type: 'separator' },
      { id: 'carnivore.settings', label: t('menubar.settings'), accelerator: 'Cmd+,', click: () => appWindow.open('#settings') },
      { type: 'separator' },
      { role: 'services' },
      { type: 'separator' },
      { role: 'hide' }, { role: 'hideOthers' }, { role: 'unhide' },
      { type: 'separator' },
      { id: 'carnivore.quit', label: t('menubar.quit'), accelerator: 'Cmd+Q', role: 'quit' },
      { id: 'carnivore.quit_engine', label: t('menubar.quit_stop'), click: () => quitAndStopEngine() },
    ],
  };
}

module.exports = { build };
