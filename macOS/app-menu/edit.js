
'use strict';

const ACCELERATORS_OWNED_BY_PAGE = false;

function pageRole(role) {
  return ACCELERATORS_OWNED_BY_PAGE ? { role, registerAccelerator: false } : { role };
}

function build({ t }) {
  return {
    id: 'edit',
    label: t('menubar.menu.edit'),
    submenu: [
      { role: 'undo' }, { role: 'redo' },
      { type: 'separator' },
      { role: 'cut' }, pageRole('copy'), pageRole('paste'), pageRole('selectAll'),
    ],
  };
}

module.exports = { build, ACCELERATORS_OWNED_BY_PAGE };
