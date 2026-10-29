'use strict';

const fs = require('fs');
const { menuBarIconWanted, trayPresenceDecision } = require('./app-lifecycle-policy');

function readMenuBarIcon(configPath, fsImpl) {
  if (!configPath) return true;
  try {
    const data = JSON.parse((fsImpl || fs).readFileSync(configPath, 'utf8'));
    const prefs = data && data.ui_preferences;
    return menuBarIconWanted(prefs && prefs.values ? prefs.values.desktop_menu_bar_icon : undefined);
  } catch (err) {
    if (err.code !== 'ENOENT') console.warn('[tray-presence] config not read, icon stays shown:', err.message);
    return true;
  }
}

function createTrayPresence({ Tray, nativeImage, nativeTheme, iconPath, updateIconPath, onTheme, log }) {
  const note = typeof log === 'function' ? log : () => {};
  let real = null;
  let tooltip = 'Carnivore';
  let ignoreDouble = null;
  let contextMenu = null;
  let iconState = 'normal';
  const handlers = [];

  function applyIcon() {
    if (!real) return;
    const update = iconState === 'update' && updateIconPath;
    const file = update ? updateIconPath : iconPath;
    const image = nativeImage.createFromPath(file);
    if (image.isEmpty()) {
      console.warn('Tray icon asset missing:', file);
      return;
    }
    if (!update) image.setTemplateImage(true);
    real.setImage(image);
  }

  function build() {
    real = new Tray(nativeImage.createEmpty());
    real.setToolTip(tooltip);
    if (ignoreDouble !== null) real.setIgnoreDoubleClickEvents(ignoreDouble);
    if (contextMenu) real.setContextMenu(contextMenu);
    for (const [event, fn] of handlers) real.on(event, fn);
    applyIcon();
  }

  function drop() {
    if (!real) return;
    real.destroy();
    real = null;
  }

  nativeTheme.on('updated', () => {
    applyIcon();
    if (onTheme) onTheme();
  });

  return {
    facade: {
      setToolTip(text) {
        tooltip = text;
        if (real) real.setToolTip(text);
      },
      setImage(image) { if (real) real.setImage(image); },
      setContextMenu(menu) {
        contextMenu = menu;
        if (real) real.setContextMenu(menu);
      },
      popUpContextMenu(menu) { if (real) real.popUpContextMenu(menu); },
      setIgnoreDoubleClickEvents(flag) {
        ignoreDouble = flag;
        if (real) real.setIgnoreDoubleClickEvents(flag);
      },
      on(event, fn) {
        handlers.push([event, fn]);
        if (real) real.on(event, fn);
      },
      destroy: drop,
    },
    apply(wanted) {
      const decision = trayPresenceDecision({ wanted, hasTray: Boolean(real) });
      if (decision === 'create') build();
      else if (decision === 'destroy') drop();
      if (decision !== 'keep') note(`menu bar icon ${decision === 'create' ? 'shown' : 'removed'}`);
      return decision;
    },
    setIconState(state) {
      const next = state === 'update' ? 'update' : 'normal';
      if (next === iconState) return;
      iconState = next;
      applyIcon();
    },
    tray: () => real,
    hasTray: () => Boolean(real),
  };
}

module.exports = { readMenuBarIcon, createTrayPresence };
