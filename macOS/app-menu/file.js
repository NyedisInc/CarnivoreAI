
'use strict';

const { sendVerb } = require('./commands');

function build({ t, appWindow }) {
  return {
    id: 'file',
    label: t('menubar.menu.file'),
    submenu: [
      { id: 'file.new_session', label: t('menubar.new_session'), accelerator: 'Cmd+N', click: () => sendVerb(appWindow, 'file.new_session') },
      { id: 'file.new_window', label: t('menubar.menu.new_window'), accelerator: 'Cmd+Shift+N', click: () => appWindow.open() },
      { id: 'file.open_project', label: t('menubar.menu.open_project'), accelerator: 'Cmd+O', click: () => sendVerb(appWindow, 'file.open_project') },
      { type: 'separator' },
      { id: 'file.reveal_project', label: t('menubar.menu.reveal_project'), click: () => sendVerb(appWindow, 'file.reveal_project') },
      { id: 'file.open_project_editor', label: t('menubar.menu.open_project_editor'), click: () => sendVerb(appWindow, 'file.open_project_editor') },
      { type: 'separator' },
      { role: 'close' },
    ],
  };
}

module.exports = { build };
