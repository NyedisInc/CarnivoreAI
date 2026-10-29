
'use strict';

function build({ t, isPackaged }) {
  const dev = isPackaged ? [] : [{ role: 'forceReload' }, { role: 'toggleDevTools' }];
  return {
    id: 'view',
    label: t('menubar.menu.view'),
    submenu: [
      { role: 'reload' }, ...dev,
      { type: 'separator' },
      { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' },
      { type: 'separator' },
      { role: 'togglefullscreen' },
    ],
  };
}

module.exports = { build };
