
'use strict';

const { sendVerb, answerWaiting } = require('./commands');

function build({ t, appWindow, waiting }) {
  const verb = (id, key) => ({ id, label: t(key), click: () => sendVerb(appWindow, id) });
  return {
    id: 'session',
    label: t('menubar.menu.session'),
    submenu: [
      verb('session.restart', 'menubar.menu.restart'),
      verb('session.stop', 'menubar.menu.stop'),
      verb('session.rename', 'menubar.menu.rename'),
      { type: 'separator' },
      { id: 'session.answer', label: t('menubar.menu.answer'), click: () => answerWaiting(appWindow, waiting) },
      { type: 'separator' },
      verb('session.open_in', 'menubar.menu.open_in'),
      verb('session.reveal', 'menubar.menu.reveal'),
      verb('session.open_editor', 'menubar.menu.open_in_editor'),
    ],
  };
}

module.exports = { build };
