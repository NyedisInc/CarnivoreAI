
'use strict';

function build({ t }) {
  return {
    id: 'window',
    role: 'window',
    label: t('menubar.menu.window'),
    submenu: [
      { role: 'minimize' }, { role: 'zoom' },
      { type: 'separator' },
      { role: 'front' },
      { type: 'separator' },
      { role: 'toggleTabBar' }, { role: 'mergeAllWindows' }, { role: 'moveTabToNewWindow' },
    ],
  };
}

module.exports = { build };
