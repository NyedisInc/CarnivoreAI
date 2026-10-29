
'use strict';

const { HELP_URL } = require('./commands');

function build({ t, openUrl, exportDiagnostics }) {
  return {
    id: 'help',
    role: 'help',
    label: t('menubar.menu.help'),
    submenu: [
      { id: 'help.docs', label: t('menubar.menu.help_docs'), click: () => openUrl(HELP_URL) },
      { id: 'help.export_diagnostics', label: t('menubar.menu.export_diagnostics'), click: () => exportDiagnostics() },
    ],
  };
}

module.exports = { build };
