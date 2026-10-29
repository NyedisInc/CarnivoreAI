
'use strict';

const { sessionLink } = require('./tray-menu/actions/sessions');

function createPressAction({ appWindow, waiting, onActivate }) {
  return function press() {
    if (appWindow.isFocused()) return;
    const target = waiting();
    if (target === null) {
      onActivate();
      return;
    }
    const opened = target.need === 'question' ? appWindow.openApproval(target.sessionId) : appWindow.open(sessionLink(target));
    if (!opened) onActivate();
  };
}

module.exports = { createPressAction };
